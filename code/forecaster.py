import pandas as pd
import datetime
from typing import List, Tuple

try:
    from code.utils import add_days, add_months
except ModuleNotFoundError:
    from utils import add_days, add_months

class Forecaster:
    def __init__(self, profiles: pd.DataFrame, events: pd.DataFrame):
        self.profiles = profiles
        self.base_events = events
        self._ledger_cache = {}

    def _as_date(self, value):
        if pd.isna(value):
            return None
        if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
            return value
        if isinstance(value, datetime.datetime):
            return value.date()
        try:
            return pd.to_datetime(value).date()
        except Exception:
            return None

    def _is_relevant_cash_event(self, row, request_date: datetime.date, end_date: datetime.date):
        # Only count settled or scheduled pending debits; ignore failed/cancelled duplications.
        status = str(row.get("status", "")).strip().lower()
        if status in {"failed", "cancelled"}:
            return False

        direction = str(row.get("direction", "")).strip().lower()
        if row.get("event_type", "").lower() in {"investment", "transfer", "refund"} and direction == "credit":
            return False

        if status in {"pending", "scheduled"} and direction == "credit":
            return False

        if status == "unrealized":
            return False

        event_date = self._as_date(row.get("event_date"))
        if event_date is None:
            return False
        if event_date < request_date or event_date > end_date:
            return False

        return True

    def _normalize_event_amount(self, row):
        amount = row.get("amount")
        if pd.isna(amount):
            return None
        try:
            return float(amount)
        except (TypeError, ValueError):
            return None

    def _inferred_recurrences(self, events: pd.DataFrame, request_date: datetime.date, end_date: datetime.date):
        inferred = []
        working = events.copy()
        working["_date"] = working["event_date"].map(self._as_date)
        working = working[working["_date"].notna() & (working["_date"] <= request_date)]
        working = working[working["status"].astype(str).str.lower().isin(["settled", "scheduled", "pending"])]
        working = working[working["direction"].astype(str).str.lower() == "debit"]

        for _, group in working.groupby(["category", "description", "direction"], dropna=False):
            dates = sorted(group["_date"].tolist())
            if len(dates) < 2:
                continue
            intervals = [(later - earlier).days for earlier, later in zip(dates, dates[1:])]
            typical = round(sum(intervals) / len(intervals))
            if not (6 <= typical <= 8 or 13 <= typical <= 15 or 26 <= typical <= 32 or 350 <= typical <= 380):
                continue

            latest = group.iloc[-1]
            amount = self._normalize_event_amount(latest)
            if amount is None:
                continue
            next_date = dates[-1]
            while True:
                if 6 <= typical <= 8:
                    next_date = add_days(next_date, 7)
                elif 13 <= typical <= 15:
                    next_date = add_days(next_date, 14)
                elif 26 <= typical <= 32:
                    next_date = add_months(next_date, 1)
                else:
                    next_date = add_days(next_date, 365)
                if next_date > end_date:
                    break
                if next_date >= request_date:
                    inferred.append({"date": next_date, "amount": amount, "direction": "debit"})
        return inferred

    def _list_projected_events(self, events: pd.DataFrame, request_date: datetime.date, end_date: datetime.date):
        ledger = []
        for _, row in events.iterrows():
            if not self._is_relevant_cash_event(row, request_date, end_date):
                continue

            event_date = self._as_date(row.get("event_date"))
            if event_date is None:
                continue

            amount = self._normalize_event_amount(row)
            if amount is None:
                continue
            direction = str(row.get("direction", "debit")).strip().lower()
            ledger.append({"date": event_date, "amount": amount, "direction": direction})

            if bool(row.get("is_recurring", False)) and pd.notna(row.get("frequency")):
                freq = str(row.get("frequency", "")).strip().lower()
                next_date = event_date
                while True:
                    if freq == "monthly":
                        next_date = add_months(next_date, 1)
                    elif freq == "weekly":
                        next_date = add_days(next_date, 7)
                    elif freq == "daily":
                        next_date = add_days(next_date, 1)
                    else:
                        break

                    if next_date > end_date:
                        break
                    ledger.append({"date": next_date, "amount": amount, "direction": direction})

        ledger.extend(self._inferred_recurrences(events, request_date, end_date))
        return ledger
        
    def get_user_state(self, user_id: str):
        profile = self.profiles[self.profiles["user_id"] == user_id].iloc[0]
        user_events = self.base_events[self.base_events["user_id"] == user_id].copy()
        return profile, user_events

    def simulate_plan(self, profile: pd.Series, events: pd.DataFrame, request_date: datetime.date,
                      proposed_payments: List[Tuple[datetime.date, float]],
                      spending_changes: List[str] = None) -> bool:
        """
        Simulates the 90-day balance. Returns True if balance >= min_balance at all times.
        spending_changes format: ["stop:event_14", "reduce_to:event_21:100"]
        """
        min_balance = profile["minimum_balance_to_keep"]
        current_balance = float(profile.get("current_available_balance", profile.get("available_balance", 0.0)))

        if spending_changes:
            for change in spending_changes:
                if change.startswith("stop:"):
                    eid = change.split(":")[1]
                    events = events[events["event_id"] != eid]
                elif change.startswith("reduce_to:"):
                    parts = change.split(":")
                    eid, amt = parts[1], float(parts[2])
                    events.loc[events["event_id"] == eid, "amount"] = amt

        end_date = add_days(request_date, 90)
        event_columns = ["event_id", "amount", "event_date", "status"]
        event_fingerprint = tuple(events[event_columns].itertuples(index=False, name=None))
        cache_key = (event_fingerprint, request_date, end_date)
        if spending_changes:
            projected_events = self._list_projected_events(events, request_date, end_date)
        else:
            projected_events = self._ledger_cache.get(cache_key)
            if projected_events is None:
                projected_events = self._list_projected_events(events, request_date, end_date)
                self._ledger_cache[cache_key] = projected_events
            projected_events = list(projected_events)

        ledger_by_date = {}
        for event in projected_events:
            event_date = event["date"]
            entry = ledger_by_date.setdefault(event_date, [0.0, 0.0])
            if event["direction"] == "credit":
                entry[0] += float(event["amount"])
            else:
                entry[1] += float(event["amount"])

        for p_date, p_amount in proposed_payments:
            if p_date and request_date <= p_date <= end_date:
                ledger_by_date.setdefault(p_date, [0.0, 0.0])[1] += float(p_amount)

        if not ledger_by_date:
            return current_balance >= min_balance

        balance = current_balance
        for event_date in sorted(ledger_by_date):
            credits, debits = ledger_by_date[event_date]
            balance += credits - debits
            if balance < min_balance:
                return False

        return balance >= min_balance

