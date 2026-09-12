import pandas as pd
from pathlib import Path

try:
    from code.config import DATA_DIR
except ModuleNotFoundError:
    from config import DATA_DIR

class DataLoader:
    def __init__(self, data_dir: Path = DATA_DIR, image_extractor=None):
        self.data_dir = data_dir
        self.image_extractor = image_extractor
        
    def load_all_data(self):
        """Loads all required CSVs into pandas DataFrames."""
        
        # Load CSVs
        self.requests = pd.read_csv(self.data_dir / "requests.csv")
        self.profiles = pd.read_csv(self.data_dir / "financial_profiles.csv")
        self.events = pd.read_csv(self.data_dir / "financial_events.csv")
        self.exchange_rates = pd.read_csv(self.data_dir / "exchange_rates.csv")
        self.payment_options = pd.read_csv(self.data_dir / "request_payment_options.csv")
        self.messages = pd.read_csv(self.data_dir / "messages.csv")
        self.images = pd.read_csv(self.data_dir / "images.csv")
        
        # Convert date columns to datetime
        self._convert_dates()

        # Resolve missing event amounts before currency normalization.
        self._resolve_image_amounts()
        
        # Standardize currency amounts
        self._standardize_currency()
        
        return {
            "requests": self.requests,
            "profiles": self.profiles,
            "events": self.events,
            "exchange_rates": self.exchange_rates,
            "payment_options": self.payment_options,
            "messages": self.messages,
            "images": self.images
        }

    def _resolve_image_amounts(self):
        if self.image_extractor is None or self.events.empty or self.images.empty:
            return

        missing = self.events["amount"].isna()
        linked_images = self.images[self.images["related_event_id"].notna()]
        image_by_event = dict(zip(linked_images["related_event_id"], linked_images["image_id"]))

        for index in self.events.index[missing]:
            event_id = self.events.at[index, "event_id"]
            image_id = image_by_event.get(event_id)
            if not image_id:
                continue
            extractor = getattr(self.image_extractor, "extract_image_record", None)
            if callable(extractor):
                image_record = extractor(image_id)
                if isinstance(image_record, dict):
                    amount = image_record.get("amount")
                    if amount is not None and float(amount) > 0:
                        self.events.at[index, "amount"] = float(amount)
                        continue
            amount = self.image_extractor.extract_amount_from_image(image_id)
            if amount is not None and amount > 0:
                self.events.at[index, "amount"] = amount
        
    def _convert_dates(self):
        """Converts relevant date columns to Python date objects using actual dataset column names."""
        # requests.csv
        self.requests["request_date"] = pd.to_datetime(self.requests["request_date"]).dt.date
        self.requests["desired_completion_date"] = pd.to_datetime(self.requests["desired_completion_date"]).dt.date

        # financial_events.csv
        if "event_date" in self.events.columns:
            self.events["event_date"] = pd.to_datetime(self.events["event_date"]).dt.date
        if "settlement_date" in self.events.columns:
            self.events["settlement_date"] = pd.to_datetime(self.events["settlement_date"]).dt.date

        # exchange_rates.csv
        if "rate_date" in self.exchange_rates.columns:
            self.exchange_rates["rate_date"] = pd.to_datetime(self.exchange_rates["rate_date"]).dt.date
        
    def _standardize_currency(self):
        """
        Converts all financial events to the user's home currency using exchange rates.
        """
        if self.events.empty or self.exchange_rates.empty:
            return

        events_with_profile = self.events.merge(
            self.profiles[["user_id", "home_currency"]], on="user_id", how="left"
        )

        foreign_mask = events_with_profile["currency"].notna() & (
            events_with_profile["currency"] != events_with_profile["home_currency"]
        )
        foreign_events = events_with_profile[foreign_mask].copy()

        if foreign_events.empty:
            return

        merged = foreign_events.merge(
            self.exchange_rates,
            left_on=["event_date", "currency", "home_currency"],
            right_on=["rate_date", "from_currency", "to_currency"],
            how="left"
        )

        merged["rate"] = merged["rate"].fillna(1.0)
        merged["converted_amount"] = merged["amount"] * merged["rate"]
        merged["currency"] = merged["home_currency"]

        conversion_map = dict(zip(merged["event_id"], merged["converted_amount"]))
        currency_map = dict(zip(merged["event_id"], merged["currency"]))

        self.events["amount"] = self.events.apply(
            lambda row: conversion_map.get(row["event_id"], row["amount"]), axis=1
        )
        self.events["currency"] = self.events.apply(
            lambda row: currency_map.get(row["event_id"], row["currency"]), axis=1
        )

