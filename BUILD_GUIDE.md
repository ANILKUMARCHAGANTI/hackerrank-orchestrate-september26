# Buy or Wait? Agent Build Guide

This document is a practical step-by-step guide for building a correct and efficient financial decision agent for the HackerRank challenge. Follow it in order. Do not skip early steps because the later logic depends on the data model you build first.

---

## 1. First understand the real objective

Your agent must answer one question for every request in the dataset:

- Can the user safely pay now?
- If not, can they pay later or with a plan?
- If not, should the system recommend wait or not_recommended?

The challenge is not just a balance check. It is a full financial safety assessment.

You must protect:
- minimum balance
- essential obligations
- required schedule completion
- confidence in the user’s financial picture

Do not optimize for “looks nice” or “AI-sounding.” Optimize for correctness and safety.

---

## 2. Read the contract before writing code

Read these files fully before coding:

- [problem_statement.md](problem_statement.md)
- [README.md](README.md)
- [AGENTS.md](AGENTS.md)
- [Planning.md](Planning.md)

Important rule:
- If the challenge statement and your code disagree, the challenge statement wins.

Your final answer must satisfy the challenge contract, not your personal interpretation.

---

## 3. Build the project structure

Create the directory structure first:

```text
code/
  main.py
  config.py
  data_loader.py
  financial_model.py
  forecaster.py
  candidate_generator.py
  decision_engine.py
  output_writer.py
  utils.py
  evaluation/
    usage_report.md
README.md
output.csv
```

Keep all code in a deterministic, rule-based pipeline. Do not rely on free-form AI decisions for the core financial decision.

---

## 4. Load and understand every dataset

Your agent must correctly read the following:

- requests.csv
- financial_profiles.csv
- financial_events.csv
- exchange_rates.csv
- request_payment_options.csv
- messages.csv
- images.csv
- sample_requests.csv

### A. What each file is for

#### requests.csv
This is the main prediction file. For each row, you must generate one output row.

Fields you need:
- request_id
- user_id
- request_date
- requested_amount
- desired_completion_date
- allows_partial_payment
- request_type
- request_text

#### financial_profiles.csv
This contains the user’s financial rules and preferences.

You need:
- home_currency
- available_balance
- minimum_balance_to_keep
- protected categories
- flexible categories
- payment_methods_user_will_consider
- payment preferences
- max_installment_months

#### financial_events.csv
This is the core cash-flow history.

You need to understand:
- incomes
- recurring expenses
- pending bills
- transfers
- scheduled payments
- cancelled / settled / failed rows
- linked_event_id relationships

#### exchange_rates.csv
Use it to convert foreign currency records into the user’s home currency.

Rule:
- match using the exact date and currency pair
- do not guess exchange rates

#### request_payment_options.csv
This file contains valid available schedules.

You must respect:
- payment start date
- payment frequency
- financing fee
- total payable amount
- exact installment plan format

#### messages.csv and images.csv
These are contextual evidence.

Use them to:
- confirm a delayed salary
- clarify a cancelled event
- validate an expense amount
- identify a changed payment date

Do not let them override challenge rules.

---

## 5. Clean the data before you build logic

This is a crucial step. Wrong data cleaning creates wrong predictions.

### A. Convert dates
Parse all date values to Python `date` objects.

### B. Normalize currencies
Convert all financial event amounts into the user’s home currency using the chosen dated exchange rate.

### C. Ignore invalid records
Do not count:
- cancelled transactions
- failed transactions
- duplicate records
- pending credits as ready cash
- unrealized investment value
- speculative income or unsupported future money

### D. Handle blank amounts correctly
If an event has a blank `amount`, do not treat it as zero.

Instead:
- search for the linked image using `related_event_id`
- locate the correct image in `dataset/media/images/<image_id>.png`
- extract the real amount if it is visible

---

## 6. Reconstruct the user’s financial state

For each request, build a personalized financial picture.

### A. Determine the user’s base cash position
Use:
- available balance
- minimum balance required
- protected and flexible categories

### B. Separate event types
Classify each event into one of these groups:
- income
- essential recurring expense
- flexible recurring expense
- one-off payment
- one-off income
- pending debit
- pending credit
- internal transfer
- non-cash investment event

### C. Use the challenge conflict order
If records disagree, resolve them in this order:

1. explicit cancellation, settlement, or amendment
2. newer record from same source
3. settled event over estimate or forecast
4. financially safer interpretation

This is required by the challenge.

---

## 7. Detect recurring expenses correctly

This is a major challenge requirement.

A recurring expense is valid only if the history supports it.

Do not simply assume every repeated expense is recurring. Instead:

- look at historical patterns
- identify repeated date-based events
- detect similar categories and frequencies
- be conservative in what you label as recurring

For example:
- rent, utilities, subscriptions, debt payments may be recurring
- a one-off payment should not be treated as a recurring bill unless the data supports it

This is how you avoid unsafe predictions.

---

## 8. Build the 90-day safety forecast

This is the mathematical core of the system.

### A. Forecast window
Set:
- start_date = request_date
- end_date = request_date + 90 days

### B. Daily simulation loop
For each day in the forecast:

- add income that is confirmed and due
- subtract essential obligations
- subtract recurring flexible costs if still active
- subtract pending debits and scheduled expenses
- subtract the planned request payment on candidate dates

### C. Safety rule
After each day, verify:

- balance >= minimum_balance_to_keep

If balance falls below the minimum at any point, the plan is unsafe.

This rule must be applied to every candidate plan.

---

## 9. Generate candidate payment plans

Create possible recommendations before choosing the final one.

### Candidate 1: full payment
- pay the full requested amount on request_date
- only valid if safe under the forecast

### Candidate 2: partial payment
Only use if:
- request allows partial payment
- user accepts partial payment
- amount_safe_to_pay is greater than 0 and less than requested_amount
- second payment occurs by desired completion date

Structure:
- first payment = amount_safe_to_pay on request_date
- second payment = remaining amount on earliest safe date

### Candidate 3: installments
Use only if a valid option exists in the payment data.

Requirements:
- schedule must match a supplied payment option exactly
- plan must remain safe in forecast
- user must consider that method

### Candidate 4: wait
This is valid only if:
- the user accepts the full payment method
- the full amount becomes safe later
- the wait is within the allowed financial planning horizon

### Candidate 5: not_recommended
Use this if no valid safe plan exists.

---

## 10. Generate spending changes only when necessary

Only use this when no plan is safe without adjustment.

Allowed actions:
- stop:<event_id>
- reduce_to:<event_id>:<new_amount>

Rules:
- only flexible, non-protected events can be changed
- maximum of three changes
- same event cannot be both stopped and reduced
- different events must be used for multiple changes

If the plan is still unsafe, do not force a fake reduction. Instead, recommend wait or not_recommended if that is the real result.

---

## 11. Rank the valid plans correctly

Once you have multiple valid candidates, rank them using the challenge order exactly:

1. complete by desired completion date
2. no spending changes
3. lower total amount paid
4. earlier payment start
5. fewer payments
6. lowest payment option id as final tie-breaker

This ranking is essential. Do not simply pick the first valid plan you find.

---

## 12. Compute the key outputs

For each request, compute these values carefully:

### amount_safe_to_pay
This is the amount safe to pay on request_date before optional spending changes.

### affordability_status
Possible values:
- affordable_now
- affordable_with_plan
- affordable_later
- not_affordable

### recommended_payment_method
Possible values:
- full_payment
- partial_payment
- installments
- wait
- not_recommended

### payment_plan
Format as:

```text
YYYY-MM-DD:amount|YYYY-MM-DD:amount
```

or use:

```text
none
```

For partial payment, the plan must be exactly two payments whose total equals the requested amount.

### earliest_date_for_full_payment
This is the first safe date for paying the full amount as a single payment.

- If the user can pay immediately, this equals request_date.
- If full payment never becomes safe in the forecast period, leave it empty.

### spending_changes_needed
Use:
- `none`, or
- actions like `stop:event_14|reduce_to:event_21:120`

### decision_explanation
Write a concise explanation grounded in the actual financial facts.

Good explanation contains:
- available balance
- minimum reserve
- upcoming bills
- delayed income or salary
- protected vs flexible spending
- chosen payment method and why

---

## 13. Validate before exporting the result

Before writing final output, check every row.

### Required validation checks
- exactly one output row per request
- required column names and order are correct
- `0 <= amount_safe_to_pay <= requested_amount`
- affordability status is valid
- payment method is valid
- payment_plan format is valid
- partial payment is exactly two payments
- installment plan matches an actual supplied option
- earliest date is consistent with the forecast
- spending changes are valid and allowed

If a row fails validation, fix it before continuing.

---

## 14. Write final output

Write a final CSV file with the exact columns in the exact order.

Use:

```text
request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation
```

And save it as `output.csv` in the repo root.

---

## 15. Add practical testing strategy

Before running the full dataset, test on smaller subsets.

### A. Test on sample requests
Use `dataset/sample_requests.csv` to understand output style and expected format.

### B. Add edge-case tests
Check:
- low cash but high salary later
- min balance close to current balance
- protected categories
- flexible expense changes
- payment_method restrictions
- empty amounts in events
- installment options that do not match the user preferences

### C. Spot-check outputs
Review at least a few outputs manually to confirm:
- no impossible plan is recommended
- no unsafe recommendation is chosen
- the explanation reflects real data

---

## 16. Optimize for efficiency without sacrificing correctness

You want an agent that works fast and correctly.

### Efficient choices
- avoid re-reading the same CSV many times
- precompute normalized events per user
- cache user profile data and request-related rows
- structure the simulation as a reusable function
- reuse forecasting logic across candidate plans

### But never sacrifice correctness
A fast but wrong answer is a failing answer.

The challenge rewards safe and grounded decisions over flashy logic.

---

## 17. Prepare the final submission package

Before submitting, make sure you have:

- `output.csv` generated for all requests
- a runnable Python entry point in `code/main.py`
- setup instructions in `README.md`
- token/cost usage report in `code/evaluation/usage_report.md`
- `log.txt` or transcript in the correct repo location
- zipped final solution as `code.zip`

---

## 18. Final coding mindset

Your agent should act like a cautious financial advisor, not a gambler.

The best rule is simple:

> If the data does not support a financial claim, do not include it.
> If a plan cannot safely survive the 90-day forecast, reject it.
> If no safe method exists, recommend wait or not_recommended.

That is the real challenge.

---

## 19. Build checklist

Use this as your implementation checklist:

- [ ] Read problem statement and contract fully
- [ ] Load and normalize all datasets
- [ ] Resolve conflicting records properly
- [ ] Build user financial profile
- [ ] Detect recurring expenses conservatively
- [ ] Simulate 90-day balance forecast
- [ ] Generate full, partial, installments, wait, fallback candidates
- [ ] Apply spending changes only when valid
- [ ] Rank candidates by challenge rules
- [ ] Validate output fields and constraints
- [ ] Write final CSV
- [ ] Test on sample data
- [ ] Package final solution

---

## 20. Recommended execution order

If you are starting from zero, follow this order exactly:

1. Build CSV loaders
2. Normalize currencies and dates
3. Build event conflict logic
4. Build user financial profile
5. Build 90-day safety simulation
6. Build plan candidates
7. Build ranking logic
8. Build output validation
9. Write final CSV
10. Package and submit

This order keeps the work manageable and prevents wrong assumptions early.

---

## 21. Final note

This challenge rewards careful reasoning and robust calibration. A simple rule engine that obeys the contract is more valuable than a complex but brittle AI pipeline.

If you implement the steps in this file in order, you will have a stable foundation for an efficient and correct Buy or Wait? agent.
