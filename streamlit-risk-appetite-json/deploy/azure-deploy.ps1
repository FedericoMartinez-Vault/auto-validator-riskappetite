# Deploy Streamlit app to Azure VM via Run Command
# Usage: .\azure-deploy.ps1

$ErrorActionPreference = "Stop"
$Subscription = "VRMS Azure DEV Subscription"
$Rg = "AZR-DEV-DATA-VM-RG"
$Vm = "VPSTREAMLIT-RISKAPP-01"
$AppRoot = Split-Path $PSScriptRoot -Parent

& "$PSScriptRoot\sync-env-from-azure.ps1" -ForVm -OutputPath "$AppRoot\.env"

az account set --subscription $Subscription

az vm run-command invoke -g $Rg -n $Vm --command-id RunShellScript --scripts `
  "sudo apt-get update -y && sudo apt-get install -y python3 python3-venv python3-pip git && sudo -u azureuser mkdir -p /home/azureuser/apps" `
  -o none

Push-Location $AppRoot
$files = @("app.py", "requirements.txt", "src", "scripts", ".env.example", "deploy/configure-firewall.sh", "deploy/grant-vm-foundry-role.sh")
if (Test-Path .env) { $files += ".env" }
tar -czf deploy/app-bundle.tar.gz @files
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("deploy/app-bundle.tar.gz"))
Pop-Location

az vm run-command invoke -g $Rg -n $Vm --command-id RunShellScript --scripts "rm -f /tmp/app.b64" -o none
$chunkSize = 4000
for ($i = 0; $i -lt $b64.Length; $i += $chunkSize) {
    $chunk = $b64.Substring($i, [Math]::Min($chunkSize, $b64.Length - $i))
    az vm run-command invoke -g $Rg -n $Vm --command-id RunShellScript --scripts "echo '$chunk' >> /tmp/app.b64" -o none
}

az vm run-command invoke -g $Rg -n $Vm --command-id RunShellScript --scripts @"
sudo -u azureuser mkdir -p /home/azureuser/apps/streamlit-risk-appetite-json
base64 -d /tmp/app.b64 | sudo -u azureuser tar -xzf - -C /home/azureuser/apps/streamlit-risk-appetite-json
cd /home/azureuser/apps/streamlit-risk-appetite-json
sudo -u azureuser python3 -m venv .venv
sudo -u azureuser .venv/bin/pip install -q --upgrade pip
sudo -u azureuser .venv/bin/pip install -q -r requirements.txt
"@ -o none

if (Test-Path "$AppRoot\.env") {
    $envB64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("$AppRoot\.env"))
    az vm run-command invoke -g $Rg -n $Vm --command-id RunShellScript --scripts "rm -f /tmp/env.b64" -o none
    for ($i = 0; $i -lt $envB64.Length; $i += $chunkSize) {
        $chunk = $envB64.Substring($i, [Math]::Min($chunkSize, $envB64.Length - $i))
        az vm run-command invoke -g $Rg -n $Vm --command-id RunShellScript --scripts "echo '$chunk' >> /tmp/env.b64" -o none
    }
    az vm run-command invoke -g $Rg -n $Vm --command-id RunShellScript --scripts @"
base64 -d /tmp/env.b64 > /home/azureuser/apps/streamlit-risk-appetite-json/.env
chown azureuser:azureuser /home/azureuser/apps/streamlit-risk-appetite-json/.env
chmod 600 /home/azureuser/apps/streamlit-risk-appetite-json/.env
"@ -o none
}

$svcB64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("$PSScriptRoot\risk-appetite-streamlit.service"))
az vm run-command invoke -g $Rg -n $Vm --command-id RunShellScript --scripts @"
echo $svcB64 | base64 -d | sudo tee /etc/systemd/system/risk-appetite-streamlit.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable risk-appetite-streamlit
sudo systemctl restart risk-appetite-streamlit
systemctl is-active risk-appetite-streamlit
ss -tlnp | grep 8502
"@ -o table

$ip = az vm show -g $Rg -n $Vm -d --query publicIps -o tsv
Write-Host "URL (VPN): http://10.72.128.197:8502"
Write-Host "URL (public): http://${ip}:8502"
