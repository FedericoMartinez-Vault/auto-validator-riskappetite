# Infra request — Foundry access for Streamlit VM (one-time)

Copy this to your Azure / platform team. After they run it, the VM gets tokens **automatically** with no PC, no `az login`, no hourly redeploy.

## What we need

Grant **Azure AI Developer** on the Foundry account to the VM **system-assigned managed identity**.

| Field | Value |
|-------|--------|
| VM | `VPSTREAMLIT-RISKAPP-01` |
| Resource group | `AZR-DEV-DATA-VM-RG` |
| Managed identity object ID | `119a6e26-72c3-4852-8b69-5f1b7fdd3822` |
| Foundry account | `azr-dev-foundry-af-1617` |
| Foundry RG | `AZR-DEV-AI-AF-RG` |
| Role | `Azure AI Developer` |

## Command for infra (Owner / User Access Admin)

```bash
az login
az account set --subscription "VRMS Azure DEV Subscription"
bash deploy/grant-vm-foundry-role.sh
```

Or explicitly:

```bash
az role assignment create \
  --assignee-object-id 119a6e26-72c3-4852-8b69-5f1b7fdd3822 \
  --assignee-principal-type ServicePrincipal \
  --role "Azure AI Developer" \
  --scope "/subscriptions/6c8f1314-e2b0-43e5-87b0-0538a6a6ca04/resourceGroups/AZR-DEV-AI-AF-RG/providers/Microsoft.CognitiveServices/accounts/azr-dev-foundry-af-1617"
```

## After grant

Redeploy once (or restart service):

```powershell
.\deploy\azure-deploy.ps1 -AuthMode ManagedIdentity
```

VM `.env` (already set by deploy):

```env
USE_MANAGED_IDENTITY=true
USE_AZURE_CLI_AUTH=false
AZURE_TENANT_ID=348d7f3f-9dec-4a47-a2a1-d314cc2e5774
```

The app calls Azure IMDS (`169.254.169.254`) on the VM to refresh tokens — **no user login, no developer PC**.

## Why tenant ID alone is not enough

Azure AD requires an **identity** to issue tokens:

| Method | Automatic on VM? | Needs infra once? |
|--------|------------------|-------------------|
| Tenant ID only | No (impossible) | — |
| **Managed identity** | **Yes** | Role grant (above) |
| Service principal in Key Vault | Yes | SP + secrets + KV role |
| `az login` on VM | No | Blocked by Conditional Access |
| Token from developer PC | No | Depends on your PC |

## Alternative: service principal in Key Vault

If infra prefers an app registration instead of MI on Foundry:

1. Create SP with **Azure AI Developer** on Foundry.
2. Store in `AZR-DEV-AI-AF-RDOH-KV`: `foundry-sp-client-id`, `foundry-sp-client-secret`.
3. Run `bash deploy/grant-vm-keyvault-role.sh` for the VM identity.
4. Deploy: `.\deploy\azure-deploy.ps1 -AuthMode KeyVault`
