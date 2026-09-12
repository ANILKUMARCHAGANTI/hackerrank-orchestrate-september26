# HackerRank Orchestrate

Repository for the **HackerRank Orchestrate** 24-hour hackathon (September 2026).

## Buy or Wait?

Build an AI-powered financial agent that decides whether a user can safely afford a requested expense.

A user may ask: **"Can I afford this laptop?"**

Answering well takes more than the current balance. The agent must account for recurring expenses, pending payments, essential spending, confirmed income, available payment options, and relevant details buried in messages and images.

For every request, the agent decides whether the user should pay in full, pay partially, use installments, wait, or not proceed. The recommendation must be personalized: two users with the same balance can deserve different answers based on their commitments, priorities, payment preferences, and willingness to adjust flexible expenses.

A recommendation is safe only if the user can complete the full payment plan, cover essential expenses, and stay above their preferred minimum balance throughout the forecast period.

Read [`problem_statement.md`](./problem_statement.md) for the full task spec, input/output schema, allowed values, conflict-resolution rules, and submission format.

For the implementation design, data flow, module responsibilities, evidence handling, and submission checklist, see [`ARCHITECTURE.md`](./ARCHITECTURE.md).

---

## Quick Start

Clone the repository and move into the project directory:

```bash
git clone https://github.com/interviewstreet/hackerrank-orchestrate-september26.git
cd hackerrank-orchestrate-september26
```

Build your solution in `code/main.py`, or use another language and document its entry point clearly.

The implemented agent:

- reconstructs each user's financial state from the supplied CSV files
- fills blank event amounts from linked image OCR before forecasting
- converts foreign-currency events using the supplied dated exchange rates
- forecasts cash flow for 90 days while protecting essential spending and the minimum balance
- evaluates full payment, partial payment, installments, waiting, and rejection
- extracts explicit message amendments with local Ollama `llama3.2`
- uses Google Cloud Vision OCR for image-linked missing amounts
- keeps the deterministic financial engine authoritative over OCR and Llama evidence

Your solution must:

- Read the input files from `dataset/`
- Generate one prediction for every request
- Write the final predictions to `output.csv` in the repository root

Run the starter Python entry point with:

```powershell
python -m pip install pandas google-cloud-vision
```

Do not commit API keys, service-account files, `.env` files, or private credentials.

## Run the Agent

### Windows PowerShell

```powershell
$env:ENABLE_LOCAL_MESSAGES="1"
$env:LOCAL_LLM_MODEL="llama3.2"
python code/main.py
```

### macOS or Linux

```bash
export ENABLE_LOCAL_MESSAGES=1
export LOCAL_LLM_MODEL=llama3.2
python3 code/main.py
```

The command processes every request, writes `output.csv`, and generates `code/evaluation/usage_report.md`.

## Configure Google Cloud Vision

Google Vision is used when an event has a blank amount and an image is linked to that event through `images.csv`.

Authenticate with Application Default Credentials:

```powershell
gcloud auth application-default login
```

The extractor stores successful results in `image_ocr_cache.json`. Later runs reuse cached OCR results. The cache supports the linked dataset images and stores both extracted text and amounts.

The Vision client also supports the standard `GOOGLE_APPLICATION_CREDENTIALS` environment variable for service-account deployments. Never place credential paths or credential contents in source control.

## Configure Ollama and Llama

Start Ollama and install the local model:

```powershell
ollama serve
ollama pull llama3.2
```

Then run the agent with:

```powershell
$env:ENABLE_LOCAL_MESSAGES="1"
$env:LOCAL_LLM_MODEL="llama3.2"
python code/main.py
```

The message parser:

- sends only relevant message text and linked event context
- requests JSON containing explicit event modifications
- caches successful results in `message_parser_cache.json`
- ignores null or malformed optional fields safely
- never chooses affordability or payment plans

Qwen can be used by changing `LOCAL_LLM_MODEL` to an installed Ollama model, but the documented configuration uses `llama3.2`.

## Important File Locations

```text
dataset/        Input data and the blank output template. Do not modify the input data.
code/           Your solution code.
output.csv      Final generated predictions in the repository root.
code.zip        ZIP file containing your complete solution for submission.
```

The blank template at `dataset/output.csv` is provided as a reference. Your final generated file must be the root-level `output.csv`.

---

## Repository Layout

```text
250 rows
250 unique request IDs
the exact required output columns
```

Also confirm:

- no request IDs are missing or duplicated
- safe amounts are within request bounds
- payment plans use valid dates and amounts
- the usage report describes the same run that produced `output.csv`
- no credentials or secrets are tracked by Git

## Submission Checklist

The HackerRank submission package should contain:

1. `code.zip` with the runnable code, README, architecture document, and `code/evaluation/usage_report.md`
2. the completed root `output.csv`
3. the required chat transcript from `log.txt`

Before packaging:

```powershell
python code/main.py
git status
```

Do not include API keys, credential files, local private configuration, or unrelated temporary files.

## Project Links

- [`problem_statement.md`](problem_statement.md) - full challenge rules
- [`ARCHITECTURE.md`](ARCHITECTURE.md) - detailed implementation architecture
- [`Planning.md`](Planning.md) - planning and design notes
- [`code/main.py`](code/main.py) - executable entry point
- [`code/evaluation/usage_report.md`](code/evaluation/usage_report.md) - final usage report
