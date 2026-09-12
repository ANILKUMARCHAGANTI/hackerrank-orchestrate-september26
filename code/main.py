import os
import datetime
import pandas as pd

try:
    from code.config import OUTPUT_FILE, EVALUATION_DIR, REQUIRED_OUTPUT_COLUMNS
    from code.data_loader import DataLoader
    from code.forecaster import Forecaster
    from code.decision_engine import DecisionEngine
except ModuleNotFoundError:
    from config import OUTPUT_FILE, EVALUATION_DIR, REQUIRED_OUTPUT_COLUMNS
    from data_loader import DataLoader
    from forecaster import Forecaster
    from decision_engine import DecisionEngine

try:
    from code.evaluation.tracker import TokenTracker
except ModuleNotFoundError:
    from evaluation.tracker import TokenTracker

try:
    from code.multimodal_extractor import MultimodalExtractor
except ModuleNotFoundError:
    try:
        from multimodal_extractor import MultimodalExtractor
    except ModuleNotFoundError:
        MultimodalExtractor = None

try:
    from code.vision_ocr import VisionOCR
except ModuleNotFoundError:
    from vision_ocr import VisionOCR

try:
    from code.local_message_parser import LocalMessageParser
except ModuleNotFoundError:
    from local_message_parser import LocalMessageParser


def main():
    print("Initializing Agent...")
    tracker = TokenTracker(model_name=os.getenv("MODEL_NAME", "deterministic-rule-engine"))
    os.environ.setdefault("ENABLE_LLM_EXPLANATIONS", "0")
    os.environ.setdefault("ENABLE_LLM_MESSAGES", "1")
    use_llm_explanations = os.getenv("ENABLE_LLM_EXPLANATIONS", "0") == "1"
    use_llm_messages = os.getenv("ENABLE_LLM_MESSAGES", "1") == "1"
    extractor = None
    if MultimodalExtractor is not None and (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        extractor = MultimodalExtractor(tracker)

    vision_ocr = VisionOCR()
    loader = DataLoader(image_extractor=vision_ocr)
    data = loader.load_all_data()
    local_message_parser = LocalMessageParser()

    forecaster = Forecaster(data["profiles"], data["events"])
    engine = DecisionEngine(forecaster)

    results = []

    print(f"Processing {len(data['requests'])} requests...")
    for _, req in data["requests"].iterrows():
        user_id = req["user_id"]
        profile, user_events = forecaster.get_user_state(user_id)

        if extractor is not None and use_llm_messages:
            relevant_messages = data["messages"][
                (data["messages"]["user_id"] == user_id) &
                (
                    data["messages"]["request_id"].eq(req["request_id"]) |
                    data["messages"]["request_id"].isna() |
                    data["messages"]["related_event_id"].isin(user_events["event_id"])
                )
            ]
            if not relevant_messages.empty:
                message_text = "\n".join(relevant_messages["message_text"].astype(str))
                events_context = user_events.to_json(orient="records", date_format="iso")
                modifications = extractor.parse_messages(message_text, events_context)
                user_events = _apply_event_modifications(user_events, modifications)
        elif local_message_parser.available:
            relevant_messages = data["messages"][
                (data["messages"]["user_id"] == user_id) &
                (
                    data["messages"]["request_id"].eq(req["request_id"]) |
                    data["messages"]["request_id"].isna() |
                    data["messages"]["related_event_id"].isin(user_events["event_id"])
                )
            ]
            if not relevant_messages.empty:
                message_text = "\n".join(relevant_messages["message_text"].astype(str))
                events_context = user_events.to_json(orient="records", date_format="iso")
                modifications = local_message_parser.parse(message_text, events_context)
                user_events = _apply_event_modifications(user_events, modifications)

        decision = engine.generate_recommendation(req, data["payment_options"], profile, user_events)
        decision["request_id"] = req["request_id"]
        _validate_decision(req, decision)

        if extractor is not None and use_llm_explanations:
            explanation_context = (
                f"Req Amount: {req['requested_amount']}, Safe: {decision['amount_safe_to_pay']}, "
                f"Method: {decision['recommended_payment_method']}, Plan: {decision['payment_plan']}"
            )
            decision["decision_explanation"] = extractor.generate_explanation(explanation_context)
        else:
            decision["decision_explanation"] = _deterministic_explanation(
                decision,
                profile["home_currency"],
                profile["minimum_balance_to_keep"],
                req["requested_amount"]
            )

        results.append({col: decision.get(col, "none") for col in REQUIRED_OUTPUT_COLUMNS})

    df_out = pd.DataFrame(results, columns=REQUIRED_OUTPUT_COLUMNS)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = OUTPUT_FILE.with_suffix(".csv.tmp")
    df_out.to_csv(temporary_output, index=False)
    if OUTPUT_FILE.exists():
        OUTPUT_FILE.unlink()
    os.replace(temporary_output, OUTPUT_FILE)
    print(f"✅ Saved predictions to {OUTPUT_FILE}")

    tracker.generate_report(EVALUATION_DIR / "usage_report.md", dataset_requests=len(data["requests"]))
    print("✅ Generated usage_report.md")


def _apply_event_modifications(events, modifications):
    events = events.copy()
    for modification in modifications:
        event_id = modification.get("event_id")
        if event_id not in set(events["event_id"]):
            continue
        mask = events["event_id"] == event_id
        action = modification.get("action")
        if action == "cancel":
            events.loc[mask, "status"] = "cancelled"
        elif action in {"amend", "confirm"}:
            if modification.get("new_amount") is not None:
                events.loc[mask, "amount"] = float(modification["new_amount"])
            if modification.get("new_date"):
                events.loc[mask, "event_date"] = pd.to_datetime(modification["new_date"]).date()
    return events


def _deterministic_explanation(decision, currency, minimum_balance, requested_amount):
    method = decision["recommended_payment_method"]
    safe_amount = decision["amount_safe_to_pay"]
    if method == "full_payment":
        return f"Pay {currency} {requested_amount:.2f} in full while preserving the {currency} {minimum_balance:.2f} minimum balance."
    if method == "installments":
        return f"Use the supplied installment schedule because it completes safely by the deadline while preserving the {currency} {minimum_balance:.2f} minimum balance."
    if method == "partial_payment":
        return f"Pay {currency} {safe_amount:.2f} now and the remaining amount by the safe completion date while preserving the minimum balance."
    if method == "wait":
        return f"Wait until {decision['earliest_date_for_full_payment']} because paying sooner would risk the {currency} {minimum_balance:.2f} minimum balance."
    return f"Do not proceed: only {currency} {safe_amount:.2f} is safe today and no eligible plan completes the request safely."


def _validate_decision(request_row, decision):
    requested_amount = float(request_row["requested_amount"])
    safe_amount = float(decision["amount_safe_to_pay"])
    status = decision["affordability_status"]
    method = decision["recommended_payment_method"]
    request_date = request_row["request_date"]
    desired_date = request_row["desired_completion_date"]
    forecast_end = request_date + datetime.timedelta(days=90)

    if not 0 <= safe_amount <= requested_amount:
        raise ValueError(f"Invalid safe amount for {request_row['request_id']}")

    allowed_statuses = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
    allowed_methods = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}
    if status not in allowed_statuses or method not in allowed_methods:
        raise ValueError(f"Invalid decision enums for {request_row['request_id']}")

    plan_text = decision.get("payment_plan", "none")
    if plan_text == "none":
        if method in {"full_payment", "partial_payment", "installments"}:
            raise ValueError(f"Immediate method without plan for {request_row['request_id']}")
        return

    payments = []
    for item in plan_text.split("|"):
        date_text, amount_text = item.split(":", 1)
        payment_date = datetime.date.fromisoformat(date_text)
        payment_amount = float(amount_text)
        payments.append((payment_date, payment_amount))

    if any(amount <= 0 for _, amount in payments):
        raise ValueError(f"Non-positive payment in {request_row['request_id']}")
    if payments != sorted(payments) or any(date < request_date or date > forecast_end for date, _ in payments):
        raise ValueError(f"Payment dates outside forecast for {request_row['request_id']}")
    if any(date > desired_date for date, _ in payments):
        raise ValueError(f"Payment plan misses deadline for {request_row['request_id']}")

    total = round(sum(amount for _, amount in payments), 2)
    if method == "full_payment":
        if len(payments) != 1 or payments[0][0] != request_date or round(payments[0][1], 2) != round(requested_amount, 2):
            raise ValueError(f"Invalid full-payment plan for {request_row['request_id']}")
    elif method == "partial_payment":
        if len(payments) != 2 or payments[0][0] != request_date or round(total, 2) != round(requested_amount, 2):
            raise ValueError(f"Invalid partial-payment plan for {request_row['request_id']}")
    elif method == "installments" and status != "affordable_with_plan":
        raise ValueError(f"Invalid installment status for {request_row['request_id']}")


if __name__ == "__main__":
    main()

