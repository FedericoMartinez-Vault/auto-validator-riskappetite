#!/bin/bash
# Create VM + NSG for Streamlit Risk Appetite
# Usage: bash azure-provision.sh

set -eu

SUBSCRIPTION="VRMS Azure DEV Subscription"
RG="AZR-DEV-DATA-VM-RG"
LOCATION="eastus"
VM_NAME="VPSTREAMLIT-RISKAPP-01"
NSG="nsg-streamlit-riskappetite"
SUBNET="/subscriptions/6c8f1314-e2b0-43e5-87b0-0538a6a6ca04/resourceGroups/AZR-DEV-RG/providers/Microsoft.Network/virtualNetworks/AZR-DEV-VNet/subnets/AZR-DEV-DATA-VM-SNet01"

az account set --subscription "$SUBSCRIPTION"

az network nsg create -g "$RG" -n "$NSG" -l "$LOCATION" 2>/dev/null || true

az network nsg rule create -g "$RG" --nsg-name "$NSG" -n Allow-SSH \
  --priority 1000 --direction Inbound --access Allow --protocol Tcp \
  --destination-port-ranges 22 --source-address-prefixes "*" 2>/dev/null || true

az network nsg rule create -g "$RG" --nsg-name "$NSG" -n Allow-Streamlit-8502 \
  --priority 1010 --direction Inbound --access Allow --protocol Tcp \
  --destination-port-ranges 8502 --source-address-prefixes "*" 2>/dev/null || true

az vm create -g "$RG" -n "$VM_NAME" \
  --image Ubuntu2204 \
  --size Standard_B2s \
  --admin-username azureuser \
  --generate-ssh-keys \
  --public-ip-sku Standard \
  --nsg "$NSG" \
  --subnet "$SUBNET"

az vm show -g "$RG" -n "$VM_NAME" -d \
  --query "{name:name, privateIp:privateIps, publicIp:publicIps}" -o table
