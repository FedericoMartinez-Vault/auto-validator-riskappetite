#!/bin/bash
# Runs on the Azure VM (invoked by azure-deploy.ps1). Fast path: git pull + cached pip.
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

if [[ ! -f "$MARKER" ]]; then
  log "First-time bootstrap: installing system packages..."
  export DEBIAN_FRONTEND=noninteractive
  sudo apt-get update -y
  sudo apt-get install -y python3 python3-venv python3-pip git
  sudo -u azureuser mkdir -p /home/azureuser/apps
  touch "$MARKER"
else
  log "Bootstrap skipped (cached)."
fi

if [[ -d "$REPO_DIR/.git" ]]; then
  log "Updating repo ($GIT_BRANCH)..."
  sudo -u azureuser git config --global --add safe.directory "$REPO_DIR"
  sudo -u azureuser git -C "$REPO_DIR" fetch origin "$GIT_BRANCH" --depth=1
  sudo -u azureuser git -C "$REPO_DIR" checkout "$GIT_BRANCH"
  sudo -u azureuser git -C "$REPO_DIR" reset --hard "origin/$GIT_BRANCH"
else
  log "Cloning repo..."
  sudo -u azureuser rm -rf "$REPO_DIR"
  sudo -u azureuser git clone --branch "$GIT_BRANCH" --depth=1 "$REPO_URL" "$REPO_DIR"
  sudo -u azureuser git config --global --add safe.directory "$REPO_DIR"
fi

cd "$APP_DIR"

if [[ ! -d .venv ]]; then
  log "Creating virtualenv..."
  sudo -u azureuser python3 -m venv .venv
fi

REQ_HASH="$(sha256sum requirements.txt | awk '{print $1}')"
CACHE_FILE=".venv/.requirements.sha256"
if [[ -f "$CACHE_FILE" ]] && [[ "$(cat "$CACHE_FILE")" == "$REQ_HASH" ]]; then
  log "Python deps unchanged — skipping pip install."
else
  log "Installing Python dependencies..."
  sudo -u azureuser .venv/bin/pip install -q --upgrade pip
  sudo -u azureuser .venv/bin/pip install -q -r requirements.txt
  echo "$REQ_HASH" | sudo -u azureuser tee "$CACHE_FILE" > /dev/null
fi

if [[ "$SKIP_ENV" != "1" ]]; then
  log "Writing .env (auth: $AUTH_MODE)..."
  case "$AUTH_MODE" in
    Token)
      log "ERROR: Token auth must be set on the VM manually; use ManagedIdentity for automated deploy."
      exit 1
      ;;
    KeyVault)
      sudo -u azureuser tee .env > /dev/null <<EOF
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
      sudo -u azureuser tee .env > /dev/null <<EOF
FOUNDRY_PROJECT_ENDPOINT=$FOUNDRY_ENDPOINT
FOUNDRY_AGENT_NAME=$AGENT_NAME
AZURE_TENANT_ID=$TENANT_ID
USE_AZURE_CLI_AUTH=false
USE_MANAGED_IDENTITY=true
EOF
      ;;
  esac
  chmod 600 .env
  chown azureuser:azureuser .env
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
log "Done. App at $APP_DIR"
