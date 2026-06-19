# Risk Appetite Agent – Metal JSON Intake

Local Streamlit prototype for Vault / HNW P&C underwriting. Upload a Metal homeowners quote JSON, extract key submission fields, and send a compact structured prompt to the existing Azure AI Foundry **AF-UW-RiskApetite** agent (or configured alternative).

## Prerequisites

- Python 3.10+
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) (`az login`)
- Access to the Foundry project and Risk Appetite agent

## Setup

```bash
cd streamlit-risk-appetite-json
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Copy environment variables:

```bash
copy .env.example .env   # Windows
# cp .env.example .env   # macOS / Linux
```

Set at minimum:

- `FOUNDRY_PROJECT_ENDPOINT` – your Azure AI Foundry project endpoint
- `FOUNDRY_AGENT_NAME` – defaults to `AF-UW-RiskApetite`

Authentication uses `DefaultAzureCredential` after `az login` when `USE_AZURE_CLI_AUTH=true` (default). For service principal auth, set `USE_AZURE_CLI_AUTH=false` and provide `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and `AZURE_CLIENT_SECRET`.

## Run

```bash
az login
streamlit run app.py
```

1. Open the local URL shown in the terminal (typically http://localhost:8501).
2. Upload a Metal homeowners JSON export.
3. Review the submission summary and missing key fields.
4. Click **Analyze Submission** to call the Foundry agent.
5. Review classification, confidence, summary, risk flags, and missing information.

## Project structure

```
streamlit-risk-appetite-json/
  app.py
  requirements.txt
  .env.example
  README.md
  src/
    metal_parser.py       # Parse and flatten Metal JSON
    foundry_agent_client.py
    prompt_builder.py
    utils.py
```

## Security notes

- Do not commit `.env` (included in `.gitignore`).
- Uploaded JSON is processed in memory only; files are not persisted.
- PII is not logged to the console.
- The agent receives a compact structured summary, not the full raw JSON.

## Agent discovery

The client searches for agents in this order:

1. `FOUNDRY_AGENT_NAME` from `.env` (if set)
2. `AF-UW-RiskApetite`
3. `AF-UW-RiskAppetite`

Uses the Foundry **conversations + responses** API with `agent_reference` (same pattern as `foundry-agent-regression-tests`).

## Local E2E check

```bash
python scripts/e2e_test.py
```

This validates JSON parsing and (when credentials are configured) a live agent call.
