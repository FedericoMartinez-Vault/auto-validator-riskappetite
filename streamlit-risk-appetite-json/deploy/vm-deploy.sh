#!/bin/bash
# Runs on the Azure VM as azureuser (invoked by azure-deploy.ps1).
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/FedericoMartinez-Vault/auto-validator-riskappetite.git}"
GIT_BRANCH="${GIT_BRANCH:-main}"
REPO_DIR="${REPO_DIR:-/home/azureuser/apps/auto-validator-riskappetite}"
APP_DIR="${APP_DIR:-$REPO_DIR/streamlit-risk-appetite-json}"
TENANT_ID="${TENANT_ID:-}"
SKIP_ENV="${SKIP_ENV:-0}"
AUTH_MODE="${AUTH_MODE:-ManagedIdentity}"
FOUNDRY_ENDPOINT="${FOUNDRY_ENDPOINT:-https://azr-dev-foundry-af-1617.services.ai.azure.com/api/projects/azr-dev-proj-af-1617}"
AGENT_NAME="${AGENT_NAME:-AF-UW-RiskApetite}"
MARKER="/home/azureuser/.streamlit-riskapp-bootstrap"

log() { echo "[vm-deploy] $*"; }

if [[ "$(id -un)" != "azureuser" ]]; then
  log "Re-running as azureuser..."
  exec sudo -u azureuser env \
    REPO_URL="$REPO_URL" GIT_BRANCH="$GIT_BRANCH" REPO_DIR="$REPO_DIR" APP_DIR="$APP_DIR" \
    TENANT_ID="$TENANT_ID" SKIP_ENV="$SKIP_ENV" AUTH_MODE="$AUTH_MODE" \
    FOUNDRY_ENDPOINT="$FOUNDRY_ENDPOINT" AGENT_NAME="$AGENT_NAME" \
    bash "$0"
fi

if [[ ! -f "$MARKER" ]]; then
  log "First-time bootstrap: installing system packages..."
  export DEBIAN_FRONTEND=noninteractive
  sudo apt-get update -y
  sudo apt-get install -y python3 python3-venv python3-pip git curl ca-certificates apt-transport-https lsb-release gnupg
  if ! command -v az >/dev/null 2>&1; then
    log "Installing Azure CLI..."
    curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
  fi
  mkdir -p /home/azureuser/apps
  touch "$MARKER"
else
  log "Bootstrap skipped (cached)."
fi

git config --global --add safe.directory "$REPO_DIR" 2>/dev/null || true

if [[ -d "$REPO_DIR/.git" ]]; then
  log "Updating repo ($GIT_BRANCH)..."
  git -C "$REPO_DIR" fetch origin "$GIT_BRANCH" --depth=1
  git -C "$REPO_DIR" checkout "$GIT_BRANCH"
  git -C "$REPO_DIR" reset --hard "origin/$GIT_BRANCH"
else
  log "Cloning repo..."
  rm -rf "$REPO_DIR"
  git clone --branch "$GIT_BRANCH" --depth=1 "$REPO_URL" "$REPO_DIR"
fi

cd "$APP_DIR"

if [[ ! -d .venv ]]; then
  log "Creating virtualenv..."
  python3 -m venv .venv
fi

REQ_HASH="$(sha256sum requirements.txt | awk '{print $1}')"
CACHE_FILE=".venv/.requirements.sha256"
if [[ -f "$CACHE_FILE" ]] && [[ "$(cat "$CACHE_FILE")" == "$REQ_HASH" ]]; then
  log "Python deps unchanged — skipping pip install."
else
  log "Installing Python dependencies..."
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
  echo "$REQ_HASH" > "$CACHE_FILE"
fi

if [[ "$SKIP_ENV" != "1" ]]; then
  log "Writing .env (auth: $AUTH_MODE)..."
  case "$AUTH_MODE" in
    AzureCli)
      cat > .env <<EOF
FOUNDRY_PROJECT_ENDPOINT=$FOUNDRY_ENDPOINT
FOUNDRY_AGENT_NAME=$AGENT_NAME
AZURE_TENANT_ID=$TENANT_ID
USE_AZURE_CLI_AUTH=true
USE_MANAGED_IDENTITY=false
EOF
      ;;
    KeyVault)
      cat > .env <<EOF
FOUNDRY_PROJECT_ENDPOINT=$FOUNDRY_ENDPOINT
FOUNDRY_AGENT_NAME=$AGENT_NAME
AZURE_TENANT_ID=$TENANT_ID
USE_AZURE_CLI_AUTH=false
USE_MANAGED_IDENTITY=true
KEY_VAULT_NAME=AZR-DEV-AI-AF-RDOH-KV
KEY_VAULT_SP_CLIENT_ID_SECRET=foundry-sp-client-id
KEY_VAULT_SP_CLIENT_SECRET_SECRET=foundry-sp-client-secret
EOF
      ;;
    *)
      cat > .env <<EOF
FOUNDRY_PROJECT_ENDPOINT=$FOUNDRY_ENDPOINT
FOUNDRY_AGENT_NAME=$AGENT_NAME
AZURE_TENANT_ID=$TENANT_ID
USE_AZURE_CLI_AUTH=false
USE_MANAGED_IDENTITY=true
EOF
      ;;
  esac
  chmod 600 .env
else
  log "Keeping existing .env (SKIP_ENV=1)."
fi

log "Installing systemd unit..."
sudo cp deploy/risk-appetite-streamlit.service /etc/systemd/system/risk-appetite-streamlit.service
sudo sed -i "s|WorkingDirectory=.*|WorkingDirectory=$APP_DIR|" /etc/systemd/system/risk-appetite-streamlit.service
sudo sed -i "s|EnvironmentFile=.*|EnvironmentFile=$APP_DIR/.env|" /etc/systemd/system/risk-appetite-streamlit.service
sudo sed -i "s|ExecStart=.*|ExecStart=$APP_DIR/.venv/bin/streamlit run app.py --server.port 8502 --server.address 0.0.0.0 --server.headless true|" /etc/systemd/system/risk-appetite-streamlit.service

sudo systemctl daemon-reload
sudo systemctl enable risk-appetite-streamlit
sudo systemctl restart risk-appetite-streamlit

sleep 2
systemctl is-active risk-appetite-streamlit
ss -tlnp | grep 8502 || true

if [[ "$AUTH_MODE" == "AzureCli" ]]; then
  if az account show >/dev/null 2>&1; then
    log "Azure CLI session OK ($(az account show --query user.name -o tsv))."
  else
    log "NEXT: SSH as azureuser and run: az login --use-device-code"
    log "     then: az account set --subscription 'VRMS Azure DEV Subscription'"
    log "     then: sudo systemctl restart risk-appetite-streamlit"
  fi
fi

log "Done. App at $APP_DIR"
