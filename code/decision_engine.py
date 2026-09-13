import datetime
import pandas as pd
from typing import Dict, List, Tuple
from itertools import combinations

try:
    from code.forecaster import Forecaster
    from code.utils import add_days, add_months
except ModuleNotFoundError:
    from forecaster import Forecaster
    from utils import add_days, add_months

class DecisionEngine:
    def __init__(self, forecaster: Forecaster):
        self.forecaster = forecaster

    def _get_flexible_events(self, profile: pd.Series, events: pd.DataFrame) -> List[str]:
        """Identifies recurring events that can be adjusted based on user profile."""
        adj_cats = str(profile.get("adjustable_categories", "")).split("|")
        prot_cats = str(profile.get("protected_categories", "")).split("|")
        
        adj_cats = [c.strip().lower() for c in adj_cats if c.strip()]
        prot_cats = [c.strip().lower() for c in prot_cats if c.strip()]
        
        flex_events = []
        for _, row in events.iterrows():
            if not row.get("is_recurring", False):
                continue
            cat = str(row.get("category", "")).strip().lower()
            if cat in prot_cats:
                continue
            # If adjustable categories are explicitly listed, it must be in there.
            if adj_cats and cat not in adj_cats:
                continue
            
            # Only consider debits
            if row.get("direction") == "credit":
                continue
                
            flex_events.append(row["event_id"])
            
        return flex_events

    def _generate_spending_change_sets(self, flex_events: List[str]) -> List[List[str]]:
        """Generates permutations of stopping up to 3 flexible events."""
        change_sets = []
        # Generate combinations of 1, 2, and 3 event stops
        for r in range(1, min(4, len(flex_events) + 1)):
            for combo in combinations(flex_events, r):
                change_sets.append([f"stop:{eid}" for eid in combo])
        return change_sets

    def _valid_installment_plan(self, request_row: pd.Series, payment_options: pd.DataFrame, profile: pd.Series, events: pd.DataFrame, requested_amount: float, spending_changes: List[str]):
        accepted = str(profile.get("payment_methods_user_will_consider", "")).split("|")
        accepted = [p.strip() for p in accepted if p.strip()]
        if "installments" not in accepted:
            return None

        candidate_rows = payment_options[
            (payment_options["request_id"] == request_row["request_id"]) &
            (payment_options["payment_method"] == "installments")
        ].copy()

        if candidate_rows.empty:
            return None

        candidate_rows = candidate_rows.sort_values(
            ["total_payable_amount", "first_payment_date", "number_of_payments", "payment_option_id"]
        ).reset_index(drop=True)
        request_date = request_row["request_date"]
        desired_date = request_row["desired_completion_date"]
        forecast_end = add_days(request_date, 90)
        
        max_months = profile.get("max_installment_months")
        max_months = None if pd.isna(max_months) or str(max_months).strip() == "" else int(max_months)

        for _, option in candidate_rows.iterrows():
            total = float(option.get("total_payable_amount", requested_amount))
            if total < requested_amount:
                continue
            first_date = pd.to_datetime(option["first_payment_date"]).date()
            count = int(option.get("number_of_payments", 0))
            if count <= 0:
                continue

            first_amount = float(option["payment_amount"])
            plan = [(first_date, first_amount)]
            spacing = int(option.get("payment_frequency_days", 30) or 30)
            for idx in range(1, count):
                plan.append((add_days(first_date, spacing * idx), first_amount))

            last_date = plan[-1][0]
            if first_date < request_date or last_date > desired_date or last_date > forecast_end:
                continue
            if max_months is not None and last_date > add_months(first_date, max_months):
                continue

            if self.forecaster.simulate_plan(profile, events, request_date, plan, spending_changes=spending_changes):
                return {
                    "payment_plan": "|".join(f"{d.strftime('%Y-%m-%d')}:{amount}" for d, amount in plan),
                    "amount_safe_to_pay": min(float(request_row["requested_amount"]), float(option["payment_amount"])),
                    "first_date": first_date,
                    "total_amount": total,
                    "option_id": option["payment_option_id"]
                }
        return None

    def _max_safe_today(self, request_row, profile, events, spending_changes):
        requested_amount = float(request_row["requested_amount"])
        low, high = 0.0, requested_amount
        for _ in range(24):
            middle = (low + high) / 2
            if self.forecaster.simulate_plan(profile, events, request_row["request_date"], [(request_row["request_date"], middle)], spending_changes=spending_changes):
                low = middle
            else:
                high = middle
        return round(low, 2)

    def _candidate_dates(self, request_date, events):
        dates = {request_date}
        for value in events.get("event_date", pd.Series(dtype=object)).tolist():
            try:
                date_value = pd.to_datetime(value).date()
                if request_date <= date_value <= add_days(request_date, 90):
                    dates.add(date_value)
            except (TypeError, ValueError):
                continue
        return sorted(dates)
        
    def _evaluate_candidates(self, request_row: pd.Series, payment_options: pd.DataFrame, 
                             profile: pd.Series, events: pd.DataFrame, spending_changes: List[str] = None):
        req_date = request_row["request_date"]
        req_amount = request_row["requested_amount"]
        desired_date = request_row["desired_completion_date"]
        accepted_methods = str(profile.get("payment_methods_user_will_consider", "")).split("|")
        accepted_methods = [m.strip() for m in accepted_methods if m.strip()]
        
        spending_changes = spending_changes or []
        sp_str = "|".join(spending_changes) if spending_changes else "none"
        
        safe_today = self._max_safe_today(request_row, profile, events, spending_changes)

        earliest_full = ""
        for test_date in self._candidate_dates(req_date, events):
            if self.forecaster.simulate_plan(profile, events, req_date, [(test_date, req_amount)], spending_changes=spending_changes):
                earliest_full = test_date.strftime('%Y-%m-%d')
                break

        candidates = []

        # 1. Full Payment
        if "full_payment" in accepted_methods and earliest_full == req_date.strftime('%Y-%m-%d'):
            candidates.append({
                "amount_safe_to_pay": req_amount,
                "affordability_status": "affordable_now" if not spending_changes else "affordable_with_plan",
                "recommended_payment_method": "full_payment",
                "payment_plan": f"{req_date.strftime('%Y-%m-%d')}:{req_amount}",
                "earliest_date_for_full_payment": earliest_full,
                "spending_changes_needed": sp_str,
                "must_finish_by_deadline": True,
                "total_cost": req_amount,
                "start_date": req_date,
                "num_payments": 1,
                "tie_breaker": 0
            })

        # 2. Partial Payment
        if request_row.get("allows_partial_payment", False) and "partial_payment" in accepted_methods and earliest_full:
            candidate_date = pd.to_datetime(earliest_full).date()
            if candidate_date <= desired_date:
                low, high = 0.0, float(req_amount)
                for _ in range(24):
                    middle = (low + high) / 2
                    if self.forecaster.simulate_plan(
                        profile, events, req_date,
                        [(req_date, middle), (candidate_date, req_amount - middle)],
                        spending_changes=spending_changes
                    ):
                        low = middle
                    else:
                        high = middle

                safe_amount = round(low, 2)
                second_amount = round(req_amount - safe_amount, 2)
                if 0 < safe_amount < req_amount and self.forecaster.simulate_plan(
                    profile, events, req_date,
                    [(req_date, safe_amount), (candidate_date, second_amount)],
                    spending_changes=spending_changes
                ):
                    candidates.append({
                        "amount_safe_to_pay": safe_amount,
                        "affordability_status": "affordable_with_plan",
                        "recommended_payment_method": "partial_payment",
                        "payment_plan": f"{req_date.strftime('%Y-%m-%d')}:{safe_amount}|{candidate_date.strftime('%Y-%m-%d')}:{second_amount}",
                        "earliest_date_for_full_payment": earliest_full,
                        "spending_changes_needed": sp_str,
                        "must_finish_by_deadline": True,
                        "total_cost": req_amount,
                        "start_date": req_date,
                        "num_payments": 2,
                        "tie_breaker": 0
                    })

        # 3. Installments
        install_plan = self._valid_installment_plan(request_row, payment_options, profile, events, req_amount, spending_changes)
        if install_plan and "installments" in accepted_methods and install_plan["first_date"] <= desired_date:
            candidates.append({
                "amount_safe_to_pay": float(install_plan["amount_safe_to_pay"]),
                "affordability_status": "affordable_with_plan",
                "recommended_payment_method": "installments",
                "payment_plan": install_plan["payment_plan"],
                "earliest_date_for_full_payment": earliest_full,
                "spending_changes_needed": sp_str,
                "must_finish_by_deadline": True,
                "total_cost": float(install_plan.get("total_amount", req_amount)),
                "start_date": install_plan["first_date"],
                "num_payments": len(install_plan["payment_plan"].split("|")),
                "tie_breaker": int(str(install_plan.get("option_id", "")).split("_")[-1]) if install_plan.get("option_id") else 999999
            })

        # 4. Wait
        if earliest_full and "full_payment" in accepted_methods and pd.to_datetime(earliest_full).date() <= desired_date:
            candidates.append({
                "amount_safe_to_pay": safe_today,
                "affordability_status": "affordable_later",
                "recommended_payment_method": "wait",
                "payment_plan": "none",
                "earliest_date_for_full_payment": earliest_full,
                "spending_changes_needed": sp_str,
                "must_finish_by_deadline": True,
                "total_cost": req_amount,
                "start_date": pd.to_datetime(earliest_full).date(),
                "num_payments": 1,
                "tie_breaker": 0
            })

        return candidates, earliest_full

    def generate_recommendation(self, request_row: pd.Series, payment_options: pd.DataFrame, 
                                profile: pd.Series, events: pd.DataFrame) -> Dict:
        def plan_key(item):
            return (
                0 if item["must_finish_by_deadline"] else 1,
                0 if item["spending_changes_needed"] == "none" else 1,
                float(item["total_cost"]),
                item["start_date"],
                item["num_payments"],
                item["tie_breaker"]
            )

        # Pass 1: Try finding plans with NO spending changes
        natural_candidates, natural_earliest_full = self._evaluate_candidates(request_row, payment_options, profile, events, spending_changes=None)
        
        best_candidates = []
        if natural_candidates:
            best_candidates.extend(natural_candidates)
        else:
            # Pass 2: If no safe plans, attempt permutations of spending changes
            flex_events = self._get_flexible_events(profile, events)
            if flex_events:
                change_sets = self._generate_spending_change_sets(flex_events)
                for sc in change_sets:
                    sc_candidates, _ = self._evaluate_candidates(request_row, payment_options, profile, events, spending_changes=sc)
                    best_candidates.extend(sc_candidates)

        if best_candidates:
            best_candidates = sorted(best_candidates, key=plan_key)
            best = best_candidates[0]
            return {
                "amount_safe_to_pay": float(best["amount_safe_to_pay"]),
                "affordability_status": best["affordability_status"],
                "recommended_payment_method": best["recommended_payment_method"],
                "payment_plan": best["payment_plan"],
                "earliest_date_for_full_payment": best["earliest_date_for_full_payment"],
                "spending_changes_needed": best["spending_changes_needed"]
            }

        # Absolute Fallback (Not affordable)
        safe_today = self._max_safe_today(request_row, profile, events, [])
        return {
            "amount_safe_to_pay": safe_today,
            "affordability_status": "not_affordable",
            "recommended_payment_method": "not_recommended",
            "payment_plan": "none",
            "earliest_date_for_full_payment": natural_earliest_full,
            "spending_changes_needed": "none"
        }
