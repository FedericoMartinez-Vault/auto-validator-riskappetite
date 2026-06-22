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

## Foundry auth on the VM (required)

The app loads credentials from `.env` only — no browser login at runtime.

**Option A — Service principal (recommended for servers)**

```env
USE_AZURE_CLI_AUTH=false
AZURE_TENANT_ID=<tenant-id>
AZURE_CLIENT_ID=<app-id>
AZURE_CLIENT_SECRET=<secret>
FOUNDRY_PROJECT_ENDPOINT=https://azr-dev-foundry-af-1617.services.ai.azure.com/api/projects/azr-dev-proj-af-1617
FOUNDRY_AGENT_NAME=AF-UW-RiskApetite
```

Redeploy: `.\deploy\azure-deploy.ps1` then `sudo systemctl restart risk-appetite-streamlit`

**Option B — Managed identity**

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

**Option C — One-time `az login` on the VM (dev/testing)**

Inside VPN, as `azureuser`:

```bash
az login --use-device-code
sudo systemctl restart risk-appetite-streamlit
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
# Ensure .env has service principal vars for the VM
.\deploy\azure-deploy.ps1
```

Uses `az vm run-command` (no SSH required). Restarts `risk-appetite-streamlit` systemd unit.

---

## UAT VM (`VPUATDATAAI01`)

| | |
|--|--|
| Private IP | `10.72.64.196` |
| Public IP | `20.228.231.195` |
| App path | `~/apps/auto-validator-riskappetite/streamlit-risk-appetite-json` |

SSH key: copy `deploy/AI_UAT.pem.txt` locally to `~/.ssh/vault-keys/AI_UAT.pem` (do not commit).

Pending: NSG inbound rule **TCP 8502** in Azure Portal.

---

## Useful commands

```bash
az vm run-command invoke -g AZR-DEV-DATA-VM-RG -n VPSTREAMLIT-RISKAPP-01 \
  --command-id RunShellScript \
  --scripts "systemctl status risk-appetite-streamlit; ss -tlnp | grep 8502"

az vm show -g AZR-DEV-DATA-VM-RG -n VPSTREAMLIT-RISKAPP-01 -d --query publicIps -o tsv
```

---

## `deploy/` files

| File | Purpose |
|------|---------|
| `azure-provision.sh` | Create VM + NSG |
| `azure-deploy.ps1` | Upload app + restart service |
| `grant-vm-foundry-role.sh` | Grant Foundry role to VM identity |
| `configure-firewall.sh` | Enable ufw on VM |
| `risk-appetite-streamlit.service` | systemd unit |
| `test-connectivity.ps1` | Test ports from Windows |
