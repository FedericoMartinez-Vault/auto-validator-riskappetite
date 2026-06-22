# Deployment — Streamlit Risk Appetite (Azure VM)

## VM (DEV)

| | |
|--|--|
| VM | `VPSTREAMLIT-RISKAPP-01` |
| Resource group | `AZR-DEV-DATA-VM-RG` |
| Subscription | `VRMS Azure DEV Subscription` |
| Private IP | `10.72.128.197` |
| Public IP | `20.51.166.193` |
| Port | `8502` |
| URL (VPN) | `http://10.72.128.197:8502` |
| SSH | `ssh azureuser@20.51.166.193 -i ~/.ssh/id_rsa` |
| VM identity | `119a6e26-72c3-4852-8b69-5f1b7fdd3822` |

---

## What we deployed (step by step)

1. **Provisioned the VM** with `deploy/azure-provision.sh` (Ubuntu, NSG rules for SSH **22** and Streamlit **8502**).
2. **Deployed the app** with `deploy/azure-deploy.ps1` via `az vm run-command` (no SSH required).
3. **Configured systemd** service `risk-appetite-streamlit` listening on `0.0.0.0:8502`.
4. **Hit a Foundry auth blocker:** the VM managed identity does not have `Azure AI Developer` on the Foundry project, and we could not create a service principal or assign roles with the current Azure AD permissions.
5. **Workaround implemented:** `deploy/sync-env-from-azure.ps1` pulls Foundry settings and a short-lived **user access token** from your local `az login` session and writes them into `.env` on the VM during deploy.
6. **Updated the app client** (`src/foundry_agent_client.py`) to use `AZURE_ACCESS_TOKEN` from `.env` instead of the VM managed identity (which was being picked up incorrectly and failing with `agents/read` permission errors).
7. **Fixed `.env` upload:** `azure-deploy.ps1` now uploads `.env` separately (base64 chunks) because bundling it inside the tar was truncating the file.

---

## Foundry auth on the VM

The app loads credentials from `.env` only — no browser login at runtime.

### Option A — Automated token from `az login` (current DEV setup)

**Prerequisites:** you are logged in locally with access to Foundry (`az login`).

**1. Log in to Azure**

```powershell
az login
az account set --subscription "VRMS Azure DEV Subscription"
```

**2. Get a Foundry access token manually (optional — for inspection)**

```powershell
az account get-access-token --resource "https://ai.azure.com" -o json
```

The response includes:

- `accessToken` — JWT used by the SDK
- `expiresOn` — when it expires (~1 hour)

**3. Build `.env` and deploy (recommended — script does steps 2–3 for you)**

```powershell
cd streamlit-risk-appetite-json

# Writes .env with endpoint, tenant, token, expiry
.\deploy\sync-env-from-azure.ps1 -ForVm

# Syncs .env + app code to the VM and restarts the service
.\deploy\azure-deploy.ps1
```

`sync-env-from-azure.ps1 -ForVm` writes:

```env
FOUNDRY_PROJECT_ENDPOINT=https://azr-dev-foundry-af-1617.services.ai.azure.com/api/projects/azr-dev-proj-af-1617
FOUNDRY_AGENT_NAME=AF-UW-RiskApetite
AZURE_TENANT_ID=<from az account show>
USE_AZURE_CLI_AUTH=false
USE_MANAGED_IDENTITY=false
AZURE_ACCESS_TOKEN=<from az account get-access-token --resource https://ai.azure.com>
AZURE_TOKEN_EXPIRES_ON=<unix timestamp>
```

**Token refresh:** re-run `.\deploy\azure-deploy.ps1` (or `sync-env-from-azure.ps1 -ForVm` then redeploy) before the token expires.

**Local dev (no token in file):**

```powershell
.\deploy\sync-env-from-azure.ps1
# or copy .env.example and set USE_AZURE_CLI_AUTH=true
az login
streamlit run app.py
```

### Option B — Service principal (recommended for production)

Ask infra for an app registration with **Azure AI Developer** on Foundry, then:

```env
USE_AZURE_CLI_AUTH=false
USE_MANAGED_IDENTITY=false
AZURE_TENANT_ID=<tenant-id>
AZURE_CLIENT_ID=<app-id>
AZURE_CLIENT_SECRET=<secret>
FOUNDRY_PROJECT_ENDPOINT=https://azr-dev-foundry-af-1617.services.ai.azure.com/api/projects/azr-dev-proj-af-1617
FOUNDRY_AGENT_NAME=AF-UW-RiskApetite
```

Redeploy: `.\deploy\azure-deploy.ps1`

### Option C — Managed identity

Ask infra to run (needs elevated Azure permissions):

```bash
bash deploy/grant-vm-foundry-role.sh
```

Then on the VM `.env`:

```env
USE_MANAGED_IDENTITY=true
USE_AZURE_CLI_AUTH=false
FOUNDRY_PROJECT_ENDPOINT=...
FOUNDRY_AGENT_NAME=AF-UW-RiskApetite
```

---

## Provision VM (Azure CLI)

```bash
az login
az account set --subscription "VRMS Azure DEV Subscription"
bash deploy/azure-provision.sh
```

Creates NSG rules for **22** and **8502**, Ubuntu VM, SSH key at `~/.ssh/id_rsa`.

---

## Deploy / update app

```powershell
az login
cd streamlit-risk-appetite-json
.\deploy\azure-deploy.ps1
```

`azure-deploy.ps1` automatically:

1. Runs `sync-env-from-azure.ps1 -ForVm` to refresh `.env`
2. Uploads app code via `az vm run-command`
3. Uploads `.env` separately (full token preserved)
4. Restarts `risk-appetite-streamlit`

---

## UAT VM (`VPUATDATAAI01`)

| | |
|--|--|
| Private IP | `10.72.64.196` |
| Public IP | `20.228.231.195` |
| App path | `~/apps/auto-validator-riskappetite/streamlit-risk-appetite-json` |

SSH key: store locally outside the repo (e.g. `~/.ssh/vault-keys/AI_UAT.pem`). Do not commit PEM files.

Pending: NSG inbound rule **TCP 8502** in Azure Portal.

---

## Useful commands

```bash
# Service status on DEV VM
az vm run-command invoke -g AZR-DEV-DATA-VM-RG -n VPSTREAMLIT-RISKAPP-01 \
  --command-id RunShellScript \
  --scripts "systemctl status risk-appetite-streamlit; ss -tlnp | grep 8502"

# Public IP
az vm show -g AZR-DEV-DATA-VM-RG -n VPSTREAMLIT-RISKAPP-01 -d --query publicIps -o tsv

# Test Foundry auth on VM (after deploy)
az vm run-command invoke -g AZR-DEV-DATA-VM-RG -n VPSTREAMLIT-RISKAPP-01 \
  --command-id RunShellScript \
  --scripts "cd /home/azureuser/apps/streamlit-risk-appetite-json && sudo -u azureuser env PYTHONPATH=. .venv/bin/python -c \"from src.foundry_agent_client import FoundryAgentClient; c=FoundryAgentClient(); print(c.find_agent()); c.close()\""
```

---

## `deploy/` files

| File | Purpose |
|------|---------|
| `azure-provision.sh` | Create VM + NSG |
| `azure-deploy.ps1` | Sync `.env`, upload app, restart service |
| `sync-env-from-azure.ps1` | Build `.env` from Azure CLI + Key Vault |
| `grant-vm-foundry-role.sh` | Grant Foundry role to VM identity |
| `configure-firewall.sh` | Enable ufw on VM |
| `risk-appetite-streamlit.service` | systemd unit |
| `test-connectivity.ps1` | Test ports from Windows |
