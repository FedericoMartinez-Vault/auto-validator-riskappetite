# Fast deploy: single az vm run-command + git pull on VM (no file upload chunks).
# Usage:
#   .\azure-deploy.ps1                    # git pull + managed identity .env
#   .\azure-deploy.ps1 -SkipEnvSync       # keep VM .env, update code only
#   .\azure-deploy.ps1 -Branch main       # override branch

param(
    [string]$Subscription = "VRMS Azure DEV Subscription",
    [string]$Rg = "AZR-DEV-DATA-VM-RG",
    [string]$Vm = "VPSTREAMLIT-RISKAPP-01",
    [string]$RepoUrl = "https://github.com/FedericoMartinez-Vault/auto-validator-riskappetite.git",
    [string]$Branch = "main",
    [ValidateSet("ManagedIdentity", "KeyVault")]
    [string]$AuthMode = "ManagedIdentity",
    [switch]$SkipEnvSync
)

$ErrorActionPreference = "Stop"
$AppRoot = Split-Path $PSScriptRoot -Parent
$VmScript = Join-Path $PSScriptRoot "vm-deploy.sh"

if (-not (Test-Path $VmScript)) {
    throw "Missing $VmScript"
}

az account set --subscription $Subscription | Out-Null
$tenantId = az account show --query tenantId -o tsv

$skipEnvFlag = if ($SkipEnvSync) { "1" } else { "0" }
$scriptContent = ([IO.File]::ReadAllText($VmScript)) -replace "`r`n", "`n" -replace "`r", "`n"
$scriptB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($scriptContent))

Write-Host "Deploying branch '$Branch' to $Vm (auth: $AuthMode, single VM command)..."

$result = az vm run-command invoke -g $Rg -n $Vm --command-id RunShellScript --scripts @"
export TENANT_ID='$tenantId'
export REPO_URL='$RepoUrl'
export GIT_BRANCH='$Branch'
export SKIP_ENV='$skipEnvFlag'
export AUTH_MODE='$AuthMode'
echo '$scriptB64' | base64 -d > /tmp/vm-deploy.sh
chmod +x /tmp/vm-deploy.sh
bash /tmp/vm-deploy.sh
"@ -o json | ConvertFrom-Json

$message = $result.value[0].message
if ($message -match '\[stdout\](.*)\[stderr\]' -or $message -match '\[stdout\](.*)') {
    $stdout = $Matches[1].Trim()
    if ($stdout) { Write-Host $stdout }
}
if ($message -notmatch 'active') {
    Write-Warning "Service may not be active. Full output:"
    Write-Host $message
}

$ip = az vm show -g $Rg -n $Vm -d --query publicIps -o tsv
Write-Host ""
Write-Host "URL (VPN): http://10.72.128.197:8502"
Write-Host "URL (public): http://${ip}:8502"
Write-Host "Auth: managed identity (no access token). Infra must run grant-vm-foundry-role.sh once if not done yet."
