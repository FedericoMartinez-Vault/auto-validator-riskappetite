# Foundry Agent Regression Tests

Local **Instruction Compliance / Task Drift Resistance Test** runner for the Azure AI Foundry underwriting agent `AF-UW-RiskApetite` / `AF-UW-RiskAppetite`.

This project sends segmented Texas HNW P&C quote rows to the existing deployed Foundry agent, captures JSON classifications, and writes regression outputs for review. It is **segmented underwriting regression testing**, not cybersecurity testing.

## Project layout

```text
foundry-agent-regression-tests/
  .env.example
  .gitignore
  requirements.txt
  README.md
  data/
    input.csv
  outputs/
  src/
    run_tests.py
    foundry_client.py
    prompt_builder.py
    result_parser.py
    report_summary.py
    report_generator.py
    report_analyst.py
    run_progress.py
```

## Prerequisites

- Python 3.10+
- Azure CLI
- Access to project `azr-dev-proj-af-1617`
- A segmented underwriting CSV exported from the Texas query

## Setup

### 1. Sign in to Azure

```bash
az login
az account show
```

Authentication for the SDK uses `DefaultAzureCredential`, which picks up your Azure CLI login locally.

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
```

Windows PowerShell:

```bash
.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create `.env`

Copy the example file and fill in your values:

```bash
copy .env.example .env
```

Required variables:

```env
FOUNDRY_API_KEY=paste_api_key_here
FOUNDRY_PROJECT_ENDPOINT=paste_project_endpoint_here
AZURE_OPENAI_ENDPOINT=paste_azure_openai_endpoint_here
```

Do not commit `.env`.

### 5. Place your test CSV

Put the segmented underwriting export at:

```text
data/input.csv
```

The runner keeps evaluation-only columns such as `expected_agent_focus` and `guideline_track` in the output files, but does not send `expected_agent_focus` to the agent because it would bias the response.

## Run tests

From the `foundry-agent-regression-tests` directory:

```bash
python src/run_tests.py --input data/input.csv --limit 20
python src/run_tests.py --input data/input.csv
python src/run_tests.py --input data/input.csv --limit 20 --generate-report
python src/run_tests.py --input data/input.csv --generate-report
```

### CLI options

| Option | Description |
| --- | --- |
| `--input` | Path to input CSV (default: `data/input.csv`) |
| `--limit` | Maximum number of rows to run |
| `--start-index` | Zero-based row index to start from (used with `--fresh`, or to force a position) |
| `--fresh` | Ignore checkpoint and start over from `--start-index` |
| `--output-dir` | Output directory (default: `outputs/`) |
| `--sleep-seconds` | Optional delay between rows |
| `--generate-report` | Generate Markdown, Word, and chart reporting package during and after the run |
| `--report-every` | Refresh the reporting package every N completed tests (default: 10) |

## What the runner does

1. Reads each row from the input CSV.
2. Builds a prompt from the base underwriting instructions plus a JSON `Submission` block.
3. Creates a new Foundry thread for every test row.
4. Runs the existing deployed agent and polls until completion.
5. Parses the assistant JSON response.
6. Writes detailed results and a segment summary.

## Output files

After a run, check `outputs/`:

| File | Purpose |
| --- | --- |
| `agent_test_results.csv` | One row per test with classification and parse metadata |
| `agent_test_results.json` | Same results in JSON |
| `summary_by_segment.csv` | Aggregated metrics by `outcome_segment` and `territory_segment` |
| `run_log.txt` | Timestamped execution log |

When `--generate-report` is passed, the runner also creates:

| File | Purpose |
| --- | --- |
| `segment_analysis.md` | Markdown segment analysis and count tables |
| `results_analysis.md` | AI-generated conclusions (updated every N tests) |
| `AF-UW-RiskAppetite_Segmented_Underwriting_Test_Report.docx` | Concise Word report: methodology, charts, and AI conclusions |
| `charts/*.png` | Eight matplotlib charts inserted into the Word report |
| `run_progress.json` | Live progress snapshot with step, elapsed time, ETA, and retry count |

During long runs:

- **Auto-resume**: re-running the same command continues from `outputs/agent_test_results.json` without duplicating tests. Use `--fresh` to start over.
- Results are checkpointed to CSV/JSON after **every** test.
- The full reporting package is refreshed every **10** tests by default (`--report-every 10`).
- The Word report stays concise (no per-test matrix or detailed sections). Per-test data remains in JSON/CSV.
- `results_analysis.md` and the Word conclusions section are regenerated with an AI summary based on aggregated stats.
- `run_log.txt` and `run_progress.json` show the current step, elapsed time, ETA, and retry events.
- Rate-limit and transient API errors are retried up to 10 times with exponential backoff.

The console prints a run summary with total tests, parse success/failure counts, fit counts, average confidence, and output file paths.

## Expected agent response format

```json
{
  "classification": "Bad Fit",
  "confidence_score": 0.95,
  "summary": "...",
  "key_positive_factors": [],
  "risk_flags": [],
  "hnw_specific_risks": [],
  "guideline_references": [],
  "missing_information": []
}
```

If the agent returns markdown fences or extra text, the parser attempts to recover the first valid JSON object and marks `parse_status = recovered_json`.

## Notes

- The runner uses the existing deployed agent only; it does not create a new agent.
- If both `AF-UW-RiskApetite` and `AF-UW-RiskAppetite` exist, the corrected name `AF-UW-RiskAppetite` is used.
- Transient API failures are retried up to 5 times with exponential backoff.
- API keys and credentials are never printed to the console.
