# Deployment — Streamlit Risk Appetite (Azure VM)

Guide for deploying and operating the app on **VPSTREAMLIT-RISKAPP-01**. All deploy scripts run from your **Windows workstation** with Azure CLI (`az login`). You do **not** need SSH for deploy or token refresh.

---

## DEV environment

| | |
|--|--|
| VM | `VPSTREAMLIT-RISKAPP-01` |
| Resource group | `AZR-DEV-DATA-VM-RG` |
| Subscription | `VRMS Azure DEV Subscription` |
| Private IP (VPN) | `10.72.128.197` |
| Public IP | `20.51.166.193` |
| Port | `8502` |
| App URL (use VPN) | http://10.72.128.197:8502 |
| App on VM | `/home/azureuser/apps/auto-validator-riskappetite/streamlit-risk-appetite-json` |
| systemd service | `risk-appetite-streamlit` |
| VM managed identity | `119a6e26-72c3-4852-8b69-5f1b7fdd3822` |
| GitHub repo | https://github.com/FedericoMartinez-Vault/auto-validator-riskappetite (public, branch `main`) |

**Network:** SSH and the app work on the **private IP** when VPN is connected. Public IP often blocks port 22/8502 from the corporate network.

---

## Prerequisites (your PC)

1. [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) installed.
2. Logged in: `az login`
3. Correct subscription: `az account set --subscription "VRMS Azure DEV Subscription"`
4. For code deploys: changes pushed to `main` on GitHub before running `azure-deploy.ps1`.

---

## Day-to-day commands

| Goal | Command | Time |
|------|---------|------|
| **Refresh Foundry token** (current auth workaround) | `.\deploy\refresh-vm-token.ps1` | ~50s |
| **Deploy code** after `git push` | `.\deploy\azure-deploy.ps1 -SkipEnvSync` | ~50s |
| **Deploy code + reset `.env`** (e.g. switch auth mode) | `.\deploy\azure-deploy.ps1 -AuthMode ManagedIdentity` | ~1 min |
| **Local dev** | `.\deploy\sync-env-from-azure.ps1` then `streamlit run app.py` | — |
| **Test ports from PC** | `.\deploy\test-connectivity.ps1` | — |

Typical release flow:

```powershell
git add .
git commit -m "your message"
git push origin main
cd streamlit-risk-appetite-json
.\deploy\azure-deploy.ps1 -SkipEnvSync
```

If Foundry returns auth errors (~1 hour after last refresh):

```powershell
cd streamlit-risk-appetite-json
.\deploy\refresh-vm-token.ps1
```

---

## How deploy works (architecture)

```
Your PC (PowerShell + az cli)
    │
    │  az vm run-command invoke  (single remote shell, ~50s)
    ▼
Azure VM VPSTREAMLIT-RISKAPP-01
    │
    ├─ vm-deploy.sh (from azure-deploy.ps1)
    │     ├─ git clone / git pull  →  ~/apps/auto-validator-riskappetite
    │     ├─ pip install (cached if requirements.txt unchanged)
    │     ├─ write .env (optional)
    │     └─ systemctl restart risk-appetite-streamlit
    │
    └─ refresh-vm-token.ps1 uploads only .env + restart (no git pull)
```

The VM does **not** build from a tar upload anymore. It pulls from GitHub. The deploy script (`vm-deploy.sh`) is sent base64-encoded in one `az vm run-command` call.

---

## Foundry authentication

The app reads `/home/azureuser/apps/.../streamlit-risk-appetite-json/.env`. No browser login at runtime.

### Current setup: user token from your PC (workaround)

Infra has not granted the VM managed identity on Foundry. Conditional Access blocks `az login` on the VM/VDI.

**`refresh-vm-token.ps1`** (run on your PC while `az login` is valid):

1. Calls `sync-env-from-azure.ps1 -ForVm -AuthMode Token` → runs `az account get-access-token --resource https://ai.azure.com` and builds a local `.env` with `AZURE_ACCESS_TOKEN` + expiry.
2. Uploads that `.env` to the VM via `az vm run-command`.
3. Restarts `risk-appetite-streamlit`.

Token lifetime is ~**1 hour**. Re-run the script when the sidebar shows Foundry errors.

```powershell
.\deploy\refresh-vm-token.ps1
```

### Permanent option: managed identity (needs infra once)

The VM already obtains tokens from Azure IMDS automatically. It only needs role **Azure AI Developer** on `azr-dev-foundry-af-1617` for identity `119a6e26-72c3-4852-8b69-5f1b7fdd3822`.

Ask platform team to run:

```bash
bash deploy/grant-vm-foundry-role.sh
```

Then deploy with:

```powershell
.\deploy\azure-deploy.ps1 -AuthMode ManagedIdentity
```

No more `refresh-vm-token.ps1`.

### Other auth modes (`azure-deploy.ps1 -AuthMode`)

| Mode | `.env` on VM | When to use |
|------|----------------|-------------|
| `ManagedIdentity` (default) | `USE_MANAGED_IDENTITY=true` | After infra grants Foundry role |
| `AzureCli` | `USE_AZURE_CLI_AUTH=true` | Only if `az login` works on VM as `azureuser` (blocked by CA today) |
| `KeyVault` | MI + reads SP secrets from KV | Infra stores `foundry-sp-client-id` / `foundry-sp-client-secret` in `AZR-DEV-AI-AF-RDOH-KV` and runs `grant-vm-keyvault-role.sh` |

Manual SP in `.env` (`AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET`) also works; set locally and use `refresh-vm-token.ps1` pattern or edit VM `.env` via run-command.

---

## Scripts reference

### `azure-deploy.ps1` (main deploy)

**Runs on:** your PC (PowerShell).

**What it does:**

1. Reads `vm-deploy.sh`, normalizes line endings, base64-encodes it.
2. Sends one `az vm run-command` to the VM with env vars: `TENANT_ID`, `REPO_URL`, `GIT_BRANCH`, `SKIP_ENV`, `AUTH_MODE`.
3. VM decodes and runs `vm-deploy.sh`.
4. Prints service status and app URLs.

**Parameters:**

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `-AuthMode` | `ManagedIdentity` | How `vm-deploy.sh` writes `.env` (`ManagedIdentity`, `KeyVault`, `AzureCli`) |
| `-SkipEnvSync` | off | Skip rewriting `.env` on VM (code-only deploy) |
| `-Branch` | `main` | Git branch to pull |
| `-RepoUrl` | GitHub URL | Override repo if needed |

**Examples:**

```powershell
# Code only (keep current .env / token)
.\deploy\azure-deploy.ps1 -SkipEnvSync

# Full deploy + managed identity .env
.\deploy\azure-deploy.ps1 -AuthMode ManagedIdentity
```

---

### `refresh-vm-token.ps1` (Foundry token only)

**Runs on:** your PC. **Requires:** `az login` on this machine (not the VDI).

**What it does:**

1. `sync-env-from-azure.ps1 -ForVm -AuthMode Token` → local `.env` with access token.
2. Base64-upload `.env` to the VM app directory.
3. `systemctl restart risk-appetite-streamlit`.
4. Prints token expiry time.

**Does not** pull git or reinstall pip. Use this for auth only; use `azure-deploy.ps1 -SkipEnvSync` for code.

---

### `vm-deploy.sh` (runs on the VM)

Invoked by `azure-deploy.ps1`. Re-executes as `azureuser` if started as root.

| Step | First run | Later runs |
|------|-----------|------------|
| Bootstrap | `apt` install python, git, azure-cli | Skipped (marker file) |
| Git | `git clone` shallow | `git fetch` + `reset --hard origin/main` |
| Python | `python3 -m venv`, `pip install -r requirements.txt` | Skipped if `requirements.txt` hash unchanged |
| `.env` | Written per `AUTH_MODE` | Skipped if `SKIP_ENV=1` |
| Service | Copy `risk-appetite-streamlit.service`, `systemctl restart` | Always restart |

---

### `sync-env-from-azure.ps1` (build `.env` locally)

**Runs on:** your PC.

Reads tenant ID from `az account show`, Foundry endpoint from Key Vault or defaults, and writes `streamlit-risk-appetite-json/.env`.

```powershell
# Local Streamlit (az login on PC)
.\deploy\sync-env-from-azure.ps1

# Generate VM token .env (used internally by refresh-vm-token.ps1)
.\deploy\sync-env-from-azure.ps1 -ForVm -AuthMode Token
```

---

### `azure-provision.sh` (one-time VM creation)

**Runs on:** machine with bash + Azure CLI (WSL or Linux). **Only needed once** to create the VM.

Creates NSG rules (TCP 22, 8502), Ubuntu 22.04 VM, generates SSH key at `~/.ssh/id_rsa` on the machine that runs the script.

```bash
az login
az account set --subscription "VRMS Azure DEV Subscription"
bash deploy/azure-provision.sh
```

---

### `grant-vm-foundry-role.sh` (infra)

Assigns **Azure AI Developer** on Foundry account `azr-dev-foundry-af-1617` to VM identity `119a6e26-72c3-4852-8b69-5f1b7fdd3822`. Requires Owner / User Access Administrator.

---

### `grant-vm-keyvault-role.sh` (infra)

Assigns **Key Vault Secrets User** on `AZR-DEV-AI-AF-RDOH-KV` to the VM identity. Needed only for `-AuthMode KeyVault`.

---

### `configure-firewall.sh` (optional, on VM)

Enables `ufw` allowing SSH and 8502. Run manually on the VM if needed.

---

### `risk-appetite-streamlit.service` (systemd unit)

Defines the Streamlit process: user `azureuser`, port `8502`, `EnvironmentFile` pointing at app `.env`. Installed/updated by `vm-deploy.sh` on each deploy.

---

### `test-connectivity.ps1` (diagnostics)

From your PC: ping private/public IP, test TCP 8502 on public IP, HTTP probe. Useful to confirm VPN vs firewall issues.

---

## SSH (optional)

Only needed for debugging or `az login` on VM (AzureCli mode). **Use private IP with VPN:**

```powershell
ssh azureuser@10.72.128.197 -i C:\path\to\your\private_key
```

Register a new public key without SSH:

```powershell
az vm user update -g AZR-DEV-DATA-VM-RG -n VPSTREAMLIT-RISKAPP-01 `
  --username azureuser `
  --ssh-key-value (Get-Content "$env:USERPROFILE\.ssh\your_key.pub" -Raw)
```

---

## Operations / troubleshooting

**Service status (no SSH):**

```bash
az vm run-command invoke -g AZR-DEV-DATA-VM-RG -n VPSTREAMLIT-RISKAPP-01 \
  --command-id RunShellScript \
  --scripts "systemctl status risk-appetite-streamlit; ss -tlnp | grep 8502"
```

**Test Foundry from VM:**

```bash
az vm run-command invoke -g AZR-DEV-DATA-VM-RG -n VPSTREAMLIT-RISKAPP-01 \
  --command-id RunShellScript \
  --scripts "cd /home/azureuser/apps/auto-validator-riskappetite/streamlit-risk-appetite-json && sudo -u azureuser env PYTHONPATH=. .venv/bin/python -c \"from src.foundry_agent_client import FoundryAgentClient; c=FoundryAgentClient(); print(c.find_agent()); c.close()\""
```

**Common issues:**

| Symptom | Fix |
|---------|-----|
| Foundry `agents/read` / 401 | Run `.\deploy\refresh-vm-token.ps1` or get MI role from infra |
| HTTP 429 rate limit | Wait 1–2 min, retry in app |
| App old code | `git push` then `.\deploy\azure-deploy.ps1 -SkipEnvSync` |
| Cannot SSH public IP | Use `10.72.128.197` on VPN |
| Token expired | `refresh-vm-token.ps1` |

---

## UAT VM (reference)

| | |
|--|--|
| Host | `VPUATDATAAI01` |
| Private IP | `10.72.64.196` |
| Public IP | `20.228.231.195` |

Same deploy scripts apply with different `-Rg` / `-Vm` if you parameterize them. Store SSH keys outside the repo.

---

## Infra access request

To stop using hourly token refresh, ask platform team for **Azure AI Developer** on `azr-dev-foundry-af-1617` for managed identity `119a6e26-72c3-4852-8b69-5f1b7fdd3822`. Portal path: resource → **Access control (IAM)** → **Add role assignment** → **Azure AI Developer** → member **Managed identity** → `VPSTREAMLIT-RISKAPP-01`.
