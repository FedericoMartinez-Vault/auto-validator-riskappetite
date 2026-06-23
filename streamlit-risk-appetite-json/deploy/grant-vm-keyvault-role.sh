#!/bin/bash
# Run with Owner/User Access Admin on the Key Vault.
# Lets the Streamlit VM read service principal secrets at runtime (optional).

set -eu

PRINCIPAL_ID="${1:-119a6e26-72c3-4852-8b69-5f1b7fdd3822}"
SCOPE="${2:-/subscriptions/6c8f1314-e2b0-43e5-87b0-0538a6a6ca04/resourceGroups/AZR-DEV-AI-AF-RG/providers/Microsoft.KeyVault/vaults/AZR-DEV-AI-AF-RDOH-KV}"

az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" \
  --scope "$SCOPE"

echo "Granted Key Vault Secrets User to $PRINCIPAL_ID"
