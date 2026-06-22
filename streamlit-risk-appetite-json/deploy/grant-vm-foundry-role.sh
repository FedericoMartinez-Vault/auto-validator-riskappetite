#!/bin/bash
# Run with Owner/User Access Admin on the Foundry resource.
# Grants the Streamlit VM system-assigned identity access to Foundry agents.

set -eu

PRINCIPAL_ID="${1:-119a6e26-72c3-4852-8b69-5f1b7fdd3822}"
SCOPE="${2:-/subscriptions/6c8f1314-e2b0-43e5-87b0-0538a6a6ca04/resourceGroups/AZR-DEV-AI-AF-RG/providers/Microsoft.CognitiveServices/accounts/azr-dev-foundry-af-1617}"

az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Azure AI Developer" \
  --scope "$SCOPE"

echo "Granted Azure AI Developer to $PRINCIPAL_ID"
