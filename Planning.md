# Buy or Wait? - Comprehensive End-to-End Implementation Plan

## 1. System Architecture & Module Design

The solution will be structured into modular Python components, designed for testability, strict constraint checking, and deterministic output generation.

### 1.1 Folder & File Structure
```text
code/
├── main.py                     # Entry point; orchestrates the end-to-end pipeline
├── config.py                   # Environment variables, API keys, file paths, and constants
├── data_loader.py              # Handles reading CSVs, joins, and currency standardization
├── multimodal_extractor.py     # Interfaces with Vision/Text LLMs for unstructured data
├── forecaster.py               # The core 90-day daily balance simulation engine
├── decision_engine.py          # Generates, validates, and ranks payment plan candidates
├── utils.py                    # Date math, string formatting, logging helpers
├── prompts/                    # Stored LLM prompt templates (to keep code clean)
└── evaluation/                 # Contains the token tracker and usage_report.md generator
```

### 1.2 Tech Stack Specifics
- **Python 3.10+**: With strict type hinting.
- **Pandas**: Crucial for optimized tabular joins (e.g., mapping exchange rates) and daily simulation math over a 90-day time series.
- **Pydantic**: Defining strict JSON schemas for LLM outputs to guarantee format compliance.
- **LLM Provider**: Gemini 1.5 Pro or OpenAI GPT-4o for complex reasoning (parsing messages, extracting numbers from images, writing explanations).

---

## 2. Granular Data Pipeline

### 2.1 Tabular Ingestion (`data_loader.py`)
- Read all datasets: `requests.csv`, `financial_profiles.csv`, `financial_events.csv`, `exchange_rates.csv`, `request_payment_options.csv`, `messages.csv`, `images.csv`.
- Convert all `date` strings to Python `datetime.date` objects.
- **Currency Standardization**: Join `financial_events.csv` with `exchange_rates.csv` on the exact `date` and `currency` pair. Multiply event amounts by the rate to normalize everything to the user's `home_currency`.

### 2.2 Unstructured Data Extraction (`multimodal_extractor.py`)
This step runs *before* any financial simulation to create a fully resolved, tabular financial state.

**Step A: Vision Extraction for Missing Amounts**
1. Filter `financial_events` where `amount` is null/blank.
2. Join with `images.csv` using `related_event_id` to fetch the `image_id`.
3. Load the corresponding image from `dataset/media/images/<image_id>.png`.
4. Call the Vision LLM with a strict prompt: *"Extract the transaction amount from this receipt/image. Return ONLY a JSON object: `{"amount": <float>}`."*
5. Update `financial_events` in memory with the extracted float.

**Step B: Message Parsing for Event Modifications**
1. Group `messages.csv` by `user_id`.
2. Feed relevant messages to the LLM along with the user's base `financial_events`.
3. Instruct the LLM to identify changes and output a JSON list of modifications.
   Schema: `[{"action": "cancel"|"amend"|"confirm", "event_id": "...", "new_date": "...", "new_amount": ...}]`
4. Apply these modifications to `financial_events` (e.g., dropping cancelled events). **Conflict Rules**: Explicit cancellation > Newer record > Settled > Financially safer interpretation.

---

## 3. The 90-Day Forecaster Engine (`forecaster.py`)

A deterministic, daily tick-based simulator for a single user/request context.

### 3.1 Initialization
- `start_date` = `request_date`
- `end_date` = `request_date + 90 days`
- `current_balance` = `financial_profiles.available_balance`
- `min_balance` = `financial_profiles.minimum_balance_to_keep`

### 3.2 Compiling the Ledger
For the 90-day forecast window, project all transactions into a time-series ledger:
- **Income**: Add confirmed, recurring salary on its scheduled settlement dates. *Crucially, do NOT count pending credits, lottery, refunds, bonuses, or unrealized investments.*
- **Expenses**: Project recurring essential and flexible expenses using historical frequency. Add pending debits and scheduled one-off payments. Reserve pending debits immediately on `request_date`.

### 3.3 The Simulation Loop (`simulate_plan`)
Inputs: `proposed_payments` (list of date/amount tuples), `proposed_spending_changes`
1. Create a deep copy of the base 90-day ledger.
2. Apply `proposed_spending_changes` (remove stopped events, lower amounts for reduced events).
3. Insert `proposed_payments` into the ledger on their specific dates.
4. Iterate day by day from `start_date` to `end_date`:
   - `daily_balance = previous_balance + sum(income_today) - sum(expenses_today)`
   - **Constraint Check**: If `daily_balance < min_balance` at *any* point in the 90 days, return `False` (Plan Failed).
5. If the loop reaches `end_date` successfully, return `True` (Plan Safe).

---

## 4. Decision Generation & Ranking (`decision_engine.py`)

### 4.1 Plan Candidate Generation
Generate standard candidates for the request:
1. **Full Payment**: `[{date: request_date, amount: requested_amount}]`
2. **Partial Payment** (if `allows_partial_payment` is true):
   - Determine `amount_safe_to_pay` today (iteratively test amounts).
   - Find earliest secondary date before `desired_completion_date` for the remaining balance.
   - `[{date: request_date, amount: X}, {date: Y, amount: requested_amount - X}]`
3. **Installments**:
   - For each valid option in `request_payment_options.csv`, construct the payment dates based on frequency/start rules, adding explicit fees to the amounts.
4. **Wait**:
   - Check if `full_payment` becomes safe at a future date <= `desired_completion_date`.

### 4.2 Filtering & Spending Adjustments
- Run `simulate_plan()` on all candidates with zero spending changes.
- If no candidates are safe, generate permutations of stopping/reducing *flexible, non-protected* expenses (max 3 changes allowed). Avoid categories marked as protected. Re-run `simulate_plan()`.

### 4.3 Ranking the Safe Plans
Filter out plans that use payment methods the user explicitly rejects in `payment_methods_user_will_consider` (Note: `wait` is acceptable if `full_payment` is in the considered list).
Rank the remaining safe plans sequentially:
1. `completion_date <= desired_completion_date` (Must be True)
2. `len(spending_changes_needed) == 0` (Prefer plans without lifestyle changes)
3. `total_amount_paid` (Ascending - minimize fees)
4. `start_date` (Ascending - start earlier)
5. `number_of_payments` (Ascending - simpler plans)
6. `payment_option_id` (Ascending, final tie-breaker)

Select the Rank 1 plan as the final recommendation.

---

## 5. Output Construction

Map the winning plan to the exact CSV format requirements:
1. **`request_id`**: Passed straight through.
2. **`amount_safe_to_pay`**: The specific amount paid on `request_date` in the winning plan.
3. **`affordability_status`**: 
   - `affordable_now` (if Full Payment on request_date)
   - `affordable_with_plan` (if Partial, Installments, or required spending changes)
   - `affordable_later` (if Wait)
   - `not_affordable` (if no plans passed safety checks)
4. **`recommended_payment_method`**: mapped from the winning candidate.
5. **`payment_plan`**: Formatted exactly as `YYYY-MM-DD:amount|YYYY-MM-DD:amount` or `none`.
6. **`earliest_date_for_full_payment`**: Independently calculated by simulating `full_payment` on a sliding window of future dates *without* spending changes, ignoring user payment preferences. Equals `request_date` if `affordable_now`.
7. **`spending_changes_needed`**: Formatted as `stop:<event_id>|reduce_to:<event_id>:<amount>` or `none`.
8. **`decision_explanation`**: Call LLM with the final context to write a 1-2 sentence justification (e.g., *"Recommend installments because it preserves your $500 minimum balance while avoiding changes to your flexible dining budget."*).

Append the row directly to `dataset/output.csv`.

---

## 6. Evaluation & Submission Workflow

1. **Cost & Token Tracking**: Wrap all LLM calls in a global `TokenCounter` class.
2. **Report Generation**: On script completion, automatically generate `evaluation/usage_report.md` detailing:
   - Model Provider and Name (e.g., `OpenAI gpt-4o`)
   - Total Input/Output Tokens
   - Average Tokens per Request
   - Estimated Total and Per-Request Cost
3. **Packaging**: A utility bash/python script to zip `code/`, `evaluation/`, and `README.md` into `code.zip` for the final upload to HackerRank.
