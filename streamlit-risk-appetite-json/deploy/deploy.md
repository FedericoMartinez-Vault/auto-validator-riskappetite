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
5. **Workaround (legacy):** `-AuthMode Token` injects a short-lived user token (~1 hour). Use only until infra grants the VM managed identity.
6. **Permanent fix:** `USE_MANAGED_IDENTITY=true` — VM gets tokens from Azure automatically after `grant-vm-foundry-role.sh` (one-time).

---

## Foundry auth on the VM

The app loads credentials from `.env` only — no browser login at runtime.

### Option A — Managed identity (permanent, recommended)

**One-time infra step** (needs Owner / User Access Admin on Foundry):

```bash
az login
az account set --subscription "VRMS Azure DEV Subscription"
bash deploy/grant-vm-foundry-role.sh
```

That grants **Azure AI Developer** to the VM identity `119a6e26-72c3-4852-8b69-5f1b7fdd3822`. After this, the VM obtains tokens automatically from Azure — **no access token in `.env`, no hourly redeploy**.

**Deploy once** (default auth mode):

```powershell
az login
cd streamlit-risk-appetite-json
.\deploy\azure-deploy.ps1
```

VM `.env` (written automatically):

```env
FOUNDRY_PROJECT_ENDPOINT=https://azr-dev-foundry-af-1617.services.ai.azure.com/api/projects/azr-dev-proj-af-1617
FOUNDRY_AGENT_NAME=AF-UW-RiskApetite
AZURE_TENANT_ID=<tenant-id>
USE_AZURE_CLI_AUTH=false
USE_MANAGED_IDENTITY=true
```

**Later code updates** (auth unchanged on the VM):

```powershell
.\deploy\azure-deploy.ps1 -SkipEnvSync
```

### Option A2 — `az login` on the VM (your user account, no token in `.env`)

Use this when infra has not granted the VM managed identity on Foundry, but **your user** already has access. One interactive login on the VM; Azure CLI refreshes tokens automatically (weeks/months, not ~1 hour).

**1. Deploy with Azure CLI auth mode**

```powershell
.\deploy\azure-deploy.ps1 -AuthMode AzureCli
```

**2. SSH to the VM** (VPN) and log in **as `azureuser`** (same user as the systemd service):

```bash
ssh azureuser@20.51.166.193 -i ~/.ssh/id_rsa
az login --use-device-code
az account set --subscription "VRMS Azure DEV Subscription"
sudo systemctl restart risk-appetite-streamlit
```

**3. Verify**

```bash
az account show --query "{user:user.name, subscription:name}" -o table
```

VM `.env`:

```env
USE_AZURE_CLI_AUTH=true
USE_MANAGED_IDENTITY=false
```

Credentials live in `/home/azureuser/.azure/` (MSAL cache). No redeploy for auth until the refresh token expires or password/MFA policy forces a new login.

**Caveats:** tied to your user (not ideal for production); if you leave the company, login stops working; conditional access may require re-login occasionally.

### Option B — Service principal in Key Vault (permanent alternative)

If infra prefers an app registration instead of MI on Foundry:

1. Create SP with **Azure AI Developer** on Foundry.
2. Store in Key Vault `AZR-DEV-AI-AF-RDOH-KV`:
   - `foundry-sp-client-id`
   - `foundry-sp-client-secret`
3. Run:

```bash
bash deploy/grant-vm-keyvault-role.sh
bash deploy/grant-vm-foundry-role.sh   # only if SP is not used for Foundry; skip if SP has the role
```

4. Deploy:

```powershell
.\deploy\azure-deploy.ps1 -AuthMode KeyVault
```

The app reads SP secrets from Key Vault at startup using the VM managed identity.

### Option C — Service principal in `.env` (permanent)

```env
USE_AZURE_CLI_AUTH=false
USE_MANAGED_IDENTITY=false
AZURE_TENANT_ID=<tenant-id>
AZURE_CLIENT_ID=<app-id>
AZURE_CLIENT_SECRET=<secret>
```

Secret does not expire until rotated — redeploy only when the secret changes.

### Option D — Short-lived user token (legacy dev only)

Only while waiting for infra to run `grant-vm-foundry-role.sh`:

```powershell
.\deploy\azure-deploy.ps1 -AuthMode Token
```

Token expires in ~1 hour. Re-run the same command to refresh.

```powershell
az account get-access-token --resource "https://ai.azure.com" -o json
```

**Local dev** (no token file):

```powershell
.\deploy\sync-env-from-azure.ps1
az login
streamlit run app.py
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

Fast path: **one** `az vm run-command` — the VM `git pull`s from GitHub (public repo). No tar/base64 upload.

```powershell
az login
cd streamlit-risk-appetite-json
.\deploy\azure-deploy.ps1
```

What happens on the VM (`deploy/vm-deploy.sh`):

1. **Bootstrap once** (apt packages) — skipped on later runs
2. **`git clone` / `git pull`** from `main`
3. **Cached `pip install`** — skipped if `requirements.txt` hash unchanged
4. **Writes `.env`** with `USE_MANAGED_IDENTITY=true` (no access token)
5. **Restarts** `risk-appetite-streamlit`

Code-only update (keep `.env` on VM):

```powershell
.\deploy\azure-deploy.ps1 -SkipEnvSync
```

Push to `main` before deploy so the VM pulls your latest commit.

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
| `azure-deploy.ps1` | Git-based deploy to VM (single run-command) |
| `vm-deploy.sh` | On-VM script: clone, cache pip, write .env, restart |
| `sync-env-from-azure.ps1` | Build `.env` from Azure CLI + Key Vault |
| `grant-vm-foundry-role.sh` | Grant Foundry role to VM identity |
| `grant-vm-keyvault-role.sh` | Grant Key Vault read to VM identity |
| `configure-firewall.sh` | Enable ufw on VM |
| `risk-appetite-streamlit.service` | systemd unit |
| `test-connectivity.ps1` | Test ports from Windows |
