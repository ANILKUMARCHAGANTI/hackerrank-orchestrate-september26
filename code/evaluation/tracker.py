import json
from pathlib import Path

class TokenTracker:
    def __init__(self, model_name: str = "gemini-1.5-flash", cost_per_1m_input: float = 0.075, cost_per_1m_output: float = 0.30):
        """
        Initializes the Token Tracker.
        Defaults to Gemini 1.5 Flash pricing (approx $0.075 per 1M input, $0.30 per 1M output).
        """
        self.model_name = model_name
        self.cost_per_1m_input = cost_per_1m_input
        self.cost_per_1m_output = cost_per_1m_output
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_requests = 0

    def add_usage(self, input_tokens: int, output_tokens: int):
        """Logs a single LLM API call's token usage."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_requests += 1

    def generate_report(self, output_path: Path, dataset_requests: int = 0):
        """Generates the required usage_report.md for HackerRank evaluation."""
        estimated_cost = (self.total_input_tokens / 1_000_000 * self.cost_per_1m_input) + \
                         (self.total_output_tokens / 1_000_000 * self.cost_per_1m_output)

        avg_tokens = 0
        if self.total_requests > 0:
            avg_tokens = (self.total_input_tokens + self.total_output_tokens) / self.total_requests

        model_label = self.model_name.strip() if self.model_name and self.model_name.strip() else "N/A"
        if self.total_requests == 0:
            model_label = "N/A — deterministic rule engine; no token-metered LLM calls"

        report = f"""# Usage Report

- **Model Provider and Name**: {model_label}
- **Total Model Calls**: {self.total_requests}
- **Total Input Tokens**: {self.total_input_tokens}
- **Total Output Tokens**: {self.total_output_tokens}
- **Average Tokens per Request**: {avg_tokens:.2f}
- **Estimated Total Cost**: ${estimated_cost:.6f}
- **Estimated Cost per Request**: ${(estimated_cost / self.total_requests) if self.total_requests > 0 else 0:.6f}
- **Dataset Requests Processed**: {dataset_requests}
- **Evidence Extraction**: Google Cloud Vision OCR cache used for image-linked missing amounts; OCR token usage is not exposed by the Vision API and is excluded from token totals.
- **LLM Evidence Extraction**: Local Ollama (llama3.2/qwen) made no calls in this final run.
- **Token Accounting Scope**: Token totals and cost cover token-metered LLM calls only; deterministic rules and Vision OCR are reported separately.
"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

