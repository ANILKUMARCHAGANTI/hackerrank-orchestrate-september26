import os
import json
from typing import List, Optional

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

try:
    from PIL import Image
except ImportError:
    Image = None

from pydantic import BaseModel

try:
    from code.config import MEDIA_DIR
    from code.evaluation.tracker import TokenTracker
except ModuleNotFoundError:
    from config import MEDIA_DIR
    from evaluation.tracker import TokenTracker

# Configure Gemini API only when an API key is present.
API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

class ImageAmount(BaseModel):
    amount: float

class EventModification(BaseModel):
    action: str  # "cancel", "amend", "confirm"
    event_id: str
    new_date: Optional[str] = None
    new_amount: Optional[float] = None

class ModificationList(BaseModel):
    modifications: List[EventModification]

class ExplanationOutput(BaseModel):
    explanation: str


IMAGE_AMOUNT_SCHEMA = {
    "type": "OBJECT",
    "properties": {"amount": {"type": "NUMBER"}},
    "required": ["amount"]
}

MODIFICATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "modifications": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "action": {"type": "STRING", "enum": ["cancel", "amend", "confirm"]},
                    "event_id": {"type": "STRING"},
                    "new_date": {"type": "STRING", "nullable": True},
                    "new_amount": {"type": "NUMBER", "nullable": True}
                },
                "required": ["action", "event_id"]
            }
        }
    },
    "required": ["modifications"]
}

EXPLANATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {"explanation": {"type": "STRING"}},
    "required": ["explanation"]
}

class MultimodalExtractor:
    def __init__(self, tracker: TokenTracker, model_name: Optional[str] = None):
        self.tracker = tracker
        self.model_name = model_name or os.getenv("MODEL_NAME", "gemini-3.6-flash")
        self.client = genai.Client(api_key=API_KEY) if genai is not None and API_KEY else None
        self.quota_exhausted = False
        self.quota_warning_printed = False

    def _require_model(self):
        if self.client is None:
            raise RuntimeError("Gemini model is not configured. Set GEMINI_API_KEY or disable LLM support.")

    def _record_usage(self, response):
        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            self.tracker.add_usage(
                getattr(usage, "prompt_token_count", 0) or 0,
                getattr(usage, "candidates_token_count", 0) or 0
            )

    def _generate_json(self, contents, schema):
        if self.quota_exhausted:
            raise RuntimeError("Gemini quota is exhausted for this run")

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema
                )
            )
        except Exception as exc:
            if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
                self.quota_exhausted = True
                if not self.quota_warning_printed:
                    print("Warning: Gemini quota exhausted; disabling further API calls for this run.")
                    self.quota_warning_printed = True
            raise

        self._record_usage(response)
        return json.loads(response.text)

    def extract_amount_from_image(self, image_id: str) -> Optional[float]:
        """Uses Gemini Vision to read a receipt PNG and extract the numerical amount."""
        if self.client is None or Image is None:
            return None

        image_path = MEDIA_DIR / f"{image_id}.png"
        if not image_path.exists():
            return None

        img = Image.open(image_path)
        prompt = "Extract the final total transaction amount from this receipt or invoice. Ignore dates, tax rates, invoice numbers, and subtotals. Return ONLY JSON with one positive float field named amount."

        try:
            data = self._generate_json([prompt, img], IMAGE_AMOUNT_SCHEMA)
        except Exception as exc:
            if not self.quota_exhausted:
                print(f"Warning: image extraction failed for {image_id}: {exc}")
            return None

        amount = data.get("amount")
        return float(amount) if amount is not None and float(amount) > 0 else None

    def parse_messages(self, messages_text: str, events_context: str) -> List[dict]:
        """Reads user messages and identifies cancellations or amendments to events."""
        self._require_model()

        prompt = f"""
You are a strict financial data extraction agent.
Read the following user messages and the current financial events context.
Identify any cancellations, amendments (change in amount/date), or confirmations of events.
Rules:
- Action must be 'cancel', 'amend', or 'confirm'.
- Provide 'new_amount' or 'new_date' (YYYY-MM-DD) ONLY if explicitly amended.

Events Context:
{events_context}

Messages:
{messages_text}
"""
        try:
            data = self._generate_json(prompt, MODIFICATION_SCHEMA)
        except Exception as exc:
            if not self.quota_exhausted:
                print(f"Warning: message extraction failed: {exc}")
            return []

        return data.get("modifications", [])

    def generate_explanation(self, reasoning_context: str) -> str:
        """Generates the concise 1-sentence decision_explanation for the final output."""
        if self.client is None:
            return (
                "The recommendation is based on the user's minimum-balance safety check and the best valid "
                "payment plan supported by the available financial data."
            )

        prompt = f"""
You are an AI financial agent. Based on the following simulation result, provide a single, concise sentence explaining why the specific payment method was chosen or rejected.
Keep it strictly grounded in the facts (e.g., minimum balance rules, deadlines). Do not invent facts.

Context:
{reasoning_context}
"""
        try:
            data = self._generate_json(prompt, EXPLANATION_SCHEMA)
        except Exception:
            return "The recommendation is based on the minimum-balance safety check and available financial data."

        return data.get("explanation", "")

