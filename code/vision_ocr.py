import json
import os
from pathlib import Path
from typing import Optional

try:
    from google.cloud import vision
except ImportError:
    vision = None

try:
    from code.config import IMAGE_OCR_CACHE, MEDIA_DIR
except ModuleNotFoundError:
    from config import IMAGE_OCR_CACHE, MEDIA_DIR


class VisionOCR:
    """One-time Google Cloud Vision OCR with a persistent JSON cache."""

    def __init__(self, cache_path: Path = IMAGE_OCR_CACHE, media_dir: Path = MEDIA_DIR):
        self.cache_path = cache_path
        self.media_dir = media_dir
        self.cache = self._load_cache()
        self.client = None
        if vision is not None:
            try:
                # The client automatically uses Application Default Credentials.
                self.client = vision.ImageAnnotatorClient()
            except Exception:
                self.client = None

    def _load_cache(self):
        if not self.cache_path.exists():
            return {}
        try:
            with self.cache_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.cache_path.with_suffix(".json.tmp")
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(self.cache, handle, indent=2, sort_keys=True)
        os.replace(temporary_path, self.cache_path)

    def extract_image_record(self, image_id: str):
        cached = self.cache.get(image_id)
        if cached and cached.get("status") == "success":
            return cached
        image_path = self.media_dir / f"{image_id}.png"
        if self.client is None or not image_path.exists():
            return None

        try:
            content = image_path.read_bytes()
            response = self.client.text_detection(
                image=vision.Image(content=content),
                timeout=30,
            )
            if response.error.message:
                raise RuntimeError(response.error.message)
            text = response.text_annotations[0].description if response.text_annotations else ""
            amount = self._extract_amount_from_text(text)
            if amount is None:
                return None

            record = {"status": "success", "amount": amount, "text": text}
            self.cache[image_id] = record
            self._save_cache()
            return record
        except Exception:
            return None

    def extract_amount_from_image(self, image_id: str) -> Optional[float]:
        record = self.extract_image_record(image_id)
        if not record:
            return None
        return float(record["amount"])

    @staticmethod
    def _extract_amount_from_text(text: str) -> Optional[float]:
        import re

        priority_patterns = (
            r"(?is)net\s+pay\s*:?\s*(?:[A-Z]{3}\s*)?([0-9][0-9,\. ]*)",
            r"(?is)transferred\s+to.*?\b(?:IDR|INR|USD|EUR)\s*([0-9][0-9,\. ]*)",
        )
        for pattern in priority_patterns:
            match = re.search(pattern, text)
            if match:
                raw = match.group(1).replace(" ", "")
                try:
                    value = float(raw.replace(",", ""))
                except ValueError:
                    continue
                if value > 0:
                    return value

        layout_patterns = (
            r"(?is)total\s+order\s+bill\s+details.*?[*€$₹]?\s*([0-9][0-9,\. ]*)",
            r"(?is)total\s+amount\s+received.*?[*€$₹]\s*([0-9][0-9,\. ]*)",
        )
        for pattern in layout_patterns:
            match = re.search(pattern, text)
            if match:
                raw = match.group(1).replace(" ", "")
                try:
                    value = float(raw.replace(",", ""))
                except ValueError:
                    continue
                if value > 0:
                    return value

        if "citycab service" in text.lower():
            currency_values = re.findall(r"[$]\s*([0-9][0-9,]*\.[0-9]{2})", text)
            if len(currency_values) >= 3:
                return float(currency_values[2].replace(",", ""))

        candidates = []
        for match in re.finditer(r"(?i)(?:total|amount|payable|due)[^0-9]{0,20}([0-9][0-9,\. ]*)", text):
            raw = match.group(1).replace(" ", "")
            if raw.count(",") and raw.count("."):
                raw = raw.replace(",", "")
            elif raw.count(",") == 1 and len(raw.rsplit(",", 1)[1]) != 2:
                raw = raw.replace(",", "")
            elif raw.count(".") > 1:
                raw = raw.replace(".", "")
            try:
                value = float(raw.replace(",", ""))
            except ValueError:
                continue
            if value > 0:
                candidates.append(value)
        return candidates[-1] if candidates else None
