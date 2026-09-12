# Buy or Wait? - Strict Challenge-Following Implementation Plan

## 1. Objective

Build a deterministic financial decision engine that follows the exact contract in [problem_statement.md](problem_statement.md) and [README.md](README.md), not a loose approximation. The output must be valid for every request in [dataset/requests.csv](dataset/requests.csv), and every recommendation must be safe under the challenge’s financial rules.

The system exists to answer one question for each request:

- Is the user safe to pay now?
- If not, what plan is safe?
- If no safe plan exists, should the recommendation be wait or not_recommended?

These choices must be derived from the supplied data, not from assumptions or unsupported guesses.

---

## 2. Non-Negotiable Contract Rules

The implementation must obey all of the following.

### 2.1 Output contract
- Write exactly one row per row in [dataset/requests.csv](dataset/requests.csv)
- Use the exact required column order:
  request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation
- `amount_safe_to_pay` must be between 0 and `requested_amount`
- `affordability_status` must be one of:
  `affordable_now`, `affordable_with_plan`, `affordable_later`, `not_affordable`
- `recommended_payment_method` must be one of:
  `full_payment`, `partial_payment`, `installments`, `wait`, `not_recommended`
- `payment_plan` must be chronological `YYYY-MM-DD:amount|...` or `none`
- For `partial_payment`, the plan must contain exactly two payments: first on `request_date`, second on `earliest_date_for_full_payment`
- `earliest_date_for_full_payment` equals `request_date` for `affordable_now`, otherwise it is empty if no safe full payment date exists within the forecast period
- `spending_changes_needed` must be `none` or up to three valid changes in the form `stop:<event_id>` or `reduce_to:<event_id>:<new_amount>`
- `decision_explanation` must be concise and grounded in actual financial facts from the data

### 2.2 Safety rules
- The user must never fall below `minimum_balance_to_keep` in the 90-day forecast
- Essential expenses must still be covered
- All recommended payments must complete by `desired_completion_date` when the plan is eligible
- Pending debits must be reserved; pending credits must not be counted as available cash
- Confirmed salary may be counted only on settlement date
- Unrealized investment value, failed or cancelled transactions, and duplicates must be ignored
- Do not invent unsupported future income, expense, or payment options

### 2.3 Method selection rules
- A payment method is eligible only if it is in `payment_methods_user_will_consider`
- `wait` is allowed only if the user accepts `full_payment` and full payment becomes safe later
- `partial_payment` is allowed only when `allows_partial_payment` is true and the user accepts it
- Installment plans must match a supplied payment option exactly
- Ranking must follow the challenge order precisely:
  1. complete by `desired_completion_date`
  2. no spending changes
  3. minimize total amount paid
  4. earlier start date
  5. fewer payments
  6. lowest `payment_option_id` tiebreaker

### 2.4 Spending-change rules
- Only flexible, non-protected recurring events may be modified
- Stopping and reducing the same event are mutually exclusive
- If multiple changes are needed, they must refer to different events
- Spending changes must be used only when necessary and must be limited to a maximum of three

### 2.5 Conflicts and evidence rules
When data conflicts, resolve in this order:
1. explicit cancellation, settlement, or amendment
2. newer record from the same source
3. settled event over estimate or forecast
4. financially safer interpretation when conflict cannot be resolved

Messages and images may clarify facts, but they are not authoritative and must not override the challenge rules.

---

## 3. Architecture

### 3.1 Recommended module layout
```text
code/
├── main.py                     # entry point
├── config.py                   # constants, paths, env handling
├── data_loader.py              # CSV ingestion and date/currency normalization
├── financial_model.py          # event cleaning, recurrence detection, conflict resolution
├── forecaster.py               # 90-day balance simulation and safety checks
├── candidate_generator.py      # build full, partial, installment, wait candidates
├── decision_engine.py          # validate, rank, and choose final plan
├── output_writer.py            # exact CSV writing and column validation
├── utils.py                    # date helpers, formatting, validation
├── evaluation/
│   └── usage_report.md         # token/cost summary for final run
└── README.md                   # setup and run instructions
```

### 3.2 Technology choices
- Python 3.10+
- Pandas for tabular joins and event aggregation
- Standard library `datetime`, `csv`, `itertools`, `collections`
- No unnecessary AI dependency in the core logic
- Optional LLM use only for message/image parsing or explanation generation when a dataset ambiguity requires it

The key design principle is deterministic rule-based logic first. AI should not drive the financial decision unless absolutely necessary.

---

## 4. Data Pipeline

### 4.1 Read all input data
Load these files from [dataset/](dataset/):
- requests.csv
- financial_profiles.csv
- financial_events.csv
- exchange_rates.csv
- request_payment_options.csv
- messages.csv
- images.csv
- sample_requests.csv (for reference only; never use it as labels)

### 4.2 Convert and normalize data
- Parse all dates as Python `date` objects
- Normalize all amounts to the user’s home currency using the matching exchange rate row
- Join events to rates using exact `date` and currency-pair data
- Preserve original context fields needed for conflict resolution

### 4.3 Event cleaning and normalization
- Deduplicate repeated representations of the same event
- Ignore cancelled, failed, duplicate, or non-cash entries when they do not count as available cash
- Treat `amount` blank as missing, not zero
- If a blank amount is tied to an image, resolve it using the linked image and `related_event_id`
- Convert all event amounts to home currency before the forecast

### 4.4 Use messages and images carefully
- Relevant messages may confirm, cancel, amend, delay, or clarify financial facts
- Message or image content may be used only when relevant to a particular event or claim
- They never override explicit challenge rules
- They never justify unsupported assets, future income, or fake payment options

---

## 5. Financial State Reconstruction

For each user request, reconstruct the financial state using the support tables and the challenge rules.

### 5.1 User profile fields
From `financial_profiles.csv`, extract:
- home currency
- available balance
- minimum balance to keep
- protected categories
- flexible categories
- payment methods user will consider
- payment preferences
- max installment months if the user accepts installments

### 5.2 Expense classification
Separate events into:
- income
- essential recurring expense
- flexible recurring expense
- one-off expense
- one-off income
- pending debit
- pending credit
- non-cash / unrealized entries
- transfers or internal adjustments

Recurring expenses must be identified conservatively and only when supported by history.

### 5.3 Cash-flow rules
- Pending credits are not counted as available funds
- Investment gains are not cash available until settled
- Confirmed salary is counted on its settlement date only
- Past and scheduled debits must be reserved in the forecast
- Essential obligations must be treated as priority obligations

### 5.4 Conflict resolution workflow
When event records disagree, apply the challenge precedence strictly:
1. explicit cancellation / settlement / amendment
2. newer same-source record
3. settled event over estimate or forecast
4. financially safer interpretation

This is required in both event reconciliation and message/image evidence interpretation.

---

## 6. 90-Day Forecast Engine

The core engine must simulate the user’s future balance over the next 90 days.

### 6.1 Forecast window
- `start_date = request_date`
- `end_date = request_date + 90 days`
- Use daily iteration from start to end

### 6.2 Balancing logic
For each day:
- add confirmed income expected that day
- subtract essential obligations due that day
- subtract flexible recurring costs expected that day
- subtract pending debits and scheduled payments due that day
- subtract any planned payment from the candidate plan on that date

The balance must never fall below `minimum_balance_to_keep` at any point in the forecast.

### 6.3 Do not count unsupported amounts
Do not include:
- pending credits
- failed or cancelled transactions
- duplicate records
- unrealized investment value
- future bonuses, refunds, lottery proceeds, or speculative gains

### 6.4 Plan safety check
A plan is safe only if:
- the balance stays above minimum balance throughout the 90-day window
- all essential obligations remain covered
- the request is completed by the required date if relevant
- all planned payments fit within the forecasted cash flow

A candidate that fails safety must be rejected.

---

## 7. Candidate Generation

Generate all plausible candidate plans before ranking.

### 7.1 Full payment candidate
- A single payment on `request_date`
- Only valid if the plan passes the 90-day safety check and is allowed by the user’s payment preferences

### 7.2 Partial payment candidate
- Only if `allows_partial_payment` is true
- Only if the request allows partial payment and the user accepts it
- `amount_safe_to_pay` is the amount that can be paid safely on `request_date`
- Remaining balance is paid on `earliest_date_for_full_payment`
- Payment schedule must contain exactly two payments
- Total must equal `requested_amount`
- Second payment must be on or before `desired_completion_date`

### 7.3 Installment candidate
- For every valid supplied payment option in [dataset/request_payment_options.csv](dataset/request_payment_options.csv)
- Validate that the schedule matches the option exactly
- Validate that the installment plan is safe under forecast rules
- Reject any installment option that violates minimum balance or user payment preferences

### 7.4 Wait candidate
- Determine if a future date exists where full payment becomes safe without violating the safety check
- Only valid if the user accepts full payment and the future date is within the relevant acceptable window
- If no safe future date exists, `wait` is not eligible

### 7.5 Not recommended fallback
- If no safe eligible plan exists, output `not_recommended`
- The fallback is a valid answer when the user cannot safely complete the request under the challenge rules

---

## 8. Spending-Change Generation

Spending changes are optional and must only be used when needed to make the plan safe.

### 8.1 Valid actions
- `stop:<event_id>`
- `reduce_to:<event_id>:<new_amount>`

### 8.2 Valid targets
Only recurring, flexible, non-protected events may be modified.

### 8.3 Limits
- maximum of three actions
- same event cannot be both stopped and reduced
- different events must be used if multiple changes are needed
- if no allowed spending change creates a safe plan, do not invent one

### 8.4 When to use changes
Try to generate a plan with zero spending changes first. Only if required, then generate candidates that include valid spending changes and re-run the safety check.

---

## 9. Decision Ranking and Final Selection

After generating all valid candidate plans, rank them by the challenge rules in this exact order:
1. complete the request by `desired_completion_date`
2. prefer no spending changes
3. minimize total amount paid
4. start earlier
5. use fewer payments
6. break ties by lowest `payment_option_id`

Only rank candidates that are both:
- safe under the 90-day forecast
- eligible under the user’s payment preferences and payment methods

The winner becomes the recommended method and plan.

---

## 10. Output Construction

The final output row must be produced from the chosen plan.

### 10.1 Fields to populate
1. `request_id`: pass through directly
2. `amount_safe_to_pay`: amount paid on `request_date` for the chosen plan
3. `affordability_status`:
   - `affordable_now` if the full requested amount is safe immediately
   - `affordable_with_plan` if a partial payment, installment, or spending change plan is chosen
   - `affordable_later` if the safe plan is `wait`
   - `not_affordable` if no safe eligible plan exists
4. `recommended_payment_method`: chosen method
5. `payment_plan`: chronological schedule or `none`
6. `earliest_date_for_full_payment`: first safe date for a full single payment without optional spending changes; equals `request_date` if affordable now
7. `spending_changes_needed`: valid action list or `none`
8. `decision_explanation`: concise explanation based on supported financial facts

### 10.2 Explanation rules
- Mention real facts like cash balance, minimum reserve, confirmed income, scheduled expense dates, and protected categories
- Do not invent or overstate unknowns
- Keep it short but grounded

---

## 11. Validation Before Writing Output

Before writing final predictions, validate each candidate and each row strictly.

### 11.1 Required checks
- one row per request
- exact output column order
- `0 <= amount_safe_to_pay <= requested_amount`
- method allowed by problem contract
- plan safe in 90-day forecast
- payment schedule matches format
- installment plan matches a valid payment option
- spending changes target only valid flexible events
- `earliest_date_for_full_payment` consistent with forecast

If a validation check fails, the recommendation must be rejected and replaced by a safer valid plan or a fallback recommendation.

---

## 12. Final Submission Workflow

### 12.1 Code deliverables
- working Python entry point in [code/main.py](code/main.py)
- setup and run instructions in [README.md](README.md)
- final output file at repository root: `output.csv`
- zip file for final submission: `code.zip`
- required evaluation report: [code/evaluation/usage_report.md](code/evaluation/usage_report.md)

### 12.2 Usage report requirements
The usage report must include:
- model provider and model name
- number of model calls
- input tokens
- output tokens
- total tokens
- average tokens per request
- estimated total cost
- estimated per-request cost
- separate totals if more than one model is used

### 12.3 Chat transcript requirement
- keep the log file in the repo root per AGENTS instructions
- do not add secrets to the transcript
- submit the final log as the `chat_transcript`

---

## 13. Practical Implementation Priority

The actual implementation should proceed in this order:

1. Load and normalize all data
2. Resolve conflicts and clean financial events
3. Build the 90-day forecast engine
4. Generate full/partial/installment/wait candidates
5. Validate safety and constraints
6. Rank candidates exactly by problem rules
7. Write final output and validate schema
8. Add optional message/image enrichment only if needed
9. Add token/cost reporting for the final run

This order keeps the solution aligned with the challenge contract and reduces the risk of getting a low-quality but superficially plausible answer.

---

## 14. Final Rule

The implementation must never optimize for “looks smart” or “sounds plausible.” It must optimize for the exact challenge contract. If a decision cannot be justified by the dataset and the rules in [problem_statement.md](problem_statement.md), it is not valid.
