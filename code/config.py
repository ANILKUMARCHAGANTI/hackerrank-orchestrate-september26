import os
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parents[1]
CODE_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "dataset"
MEDIA_DIR = DATA_DIR / "media" / "images"
IMAGE_OCR_CACHE = ROOT_DIR / "image_ocr_cache.json"
MESSAGE_CACHE = ROOT_DIR / "message_parser_cache.json"
OUTPUT_FILE = ROOT_DIR / "output.csv"
EVALUATION_DIR = CODE_DIR / "evaluation"

# LLM Config
# Keep this optional. The challenge is primarily solved by deterministic rule-based logic.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "none")
MODEL_NAME = os.getenv("MODEL_NAME", "")

# Schema definitions and constants
REQUIRED_OUTPUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation"
]

AFFORDABILITY_STATUSES = {
    "now": "affordable_now",
    "plan": "affordable_with_plan",
    "later": "affordable_later",
    "not": "not_affordable"
}

PAYMENT_METHODS = {
    "full": "full_payment",
    "partial": "partial_payment",
    "installments": "installments",
    "wait": "wait",
    "none": "not_recommended"
}

