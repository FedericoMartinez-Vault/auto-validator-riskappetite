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
$VmScript = Join-Path $PSScriptRoot "vm-deploy.sh"

if (-not (Test-Path $VmScript)) {
    throw "Missing $VmScript"
}

az account set --subscription $Subscription | Out-Null
$tenantId = az account show --query tenantId -o tsv

$skipEnvFlag = if ($SkipEnvSync) { "1" } else { "0" }
$scriptContent = ([IO.File]::ReadAllText($VmScript)) -replace "`r`n", "`n" -replace "`r", "`n"
$scriptB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($scriptContent))

$remoteLines = @(
    "rm -f /tmp/vm-deploy.b64"
)
$chunkSize = 4000
for ($i = 0; $i -lt $scriptB64.Length; $i += $chunkSize) {
    $chunk = $scriptB64.Substring($i, [Math]::Min($chunkSize, $scriptB64.Length - $i))
    $remoteLines += "echo '$chunk' >> /tmp/vm-deploy.b64"
}
$remoteLines += @(
    "base64 -d /tmp/vm-deploy.b64 > /tmp/vm-deploy.sh",
    "chmod +x /tmp/vm-deploy.sh",
    "export TENANT_ID='$tenantId'",
    "export REPO_URL='$RepoUrl'",
    "export GIT_BRANCH='$Branch'",
    "export SKIP_ENV='$skipEnvFlag'",
    "export AUTH_MODE='$AuthMode'",
    "bash /tmp/vm-deploy.sh"
)
$remoteScript = (($remoteLines -join "; ") -replace "`r", "")

Write-Host "Deploying branch '$Branch' to $Vm (~1 min, git pull + cached pip)..."

$result = az vm run-command invoke -g $Rg -n $Vm --command-id RunShellScript --scripts $remoteScript -o json | ConvertFrom-Json

$message = $result.value[0].message
if ($message -match '\[stdout\]([\s\S]*?)\[stderr\]') {
    $stdout = $Matches[1].Trim()
    if ($stdout) { Write-Host $stdout }
    if ($message -match '\[stderr\]([\s\S]*)$') {
        $stderr = $Matches[1].Trim()
        if ($stderr) { Write-Host $stderr -ForegroundColor DarkYellow }
    }
} else {
    Write-Host $message
}

if ($message -notmatch '\bactive\b') {
    throw "Deploy finished but service is not active. Check output above."
}

$ip = az vm show -g $Rg -n $Vm -d --query publicIps -o tsv
Write-Host ""
Write-Host "URL (VPN): http://10.72.128.197:8502"
Write-Host "URL (public): http://${ip}:8502"
Write-Host "Auth: managed identity (no access token)."
