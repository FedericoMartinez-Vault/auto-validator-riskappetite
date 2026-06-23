# Push your az login token to the VM .env and restart Streamlit (~30s).
# Prerequisite: az login on THIS machine (not the VDI/VM).
# Usage: .\refresh-vm-token.ps1

param(
    [string]$Subscription = "VRMS Azure DEV Subscription",
    [string]$Rg = "AZR-DEV-DATA-VM-RG",
    [string]$Vm = "VPSTREAMLIT-RISKAPP-01",
    [string]$AppDir = "/home/azureuser/apps/auto-validator-riskappetite/streamlit-risk-appetite-json"
)

$ErrorActionPreference = "Stop"
$AppRoot = Split-Path $PSScriptRoot -Parent

& "$PSScriptRoot\sync-env-from-azure.ps1" -ForVm -AuthMode Token -OutputPath "$AppRoot\.env" | Out-Null

az account set --subscription $Subscription | Out-Null

$envBytes = [IO.File]::ReadAllBytes("$AppRoot\.env")
$envB64 = [Convert]::ToBase64String($envBytes)

$remoteLines = @("rm -f /tmp/vm-env.b64")
$chunkSize = 4000
for ($i = 0; $i -lt $envB64.Length; $i += $chunkSize) {
    $chunk = $envB64.Substring($i, [Math]::Min($chunkSize, $envB64.Length - $i))
    $remoteLines += "echo '$chunk' >> /tmp/vm-env.b64"
}
$remoteLines += @(
    "base64 -d /tmp/vm-env.b64 > $AppDir/.env",
    "chown azureuser:azureuser $AppDir/.env",
    "chmod 600 $AppDir/.env",
    "systemctl restart risk-appetite-streamlit",
    "sleep 2",
    "systemctl is-active risk-appetite-streamlit",
    "wc -l $AppDir/.env"
)
$remoteScript = (($remoteLines -join "; ") -replace "`r", "")

Write-Host "Refreshing Foundry token on $Vm..."

$result = az vm run-command invoke -g $Rg -n $Vm --command-id RunShellScript --scripts $remoteScript -o json | ConvertFrom-Json
$message = $result.value[0].message
if ($message -match '\[stdout\]([\s\S]*?)\[stderr\]') { Write-Host $Matches[1].Trim() }

if ($message -notmatch '\bactive\b') {
    throw "Token upload failed or service not active."
}

$exp = (Get-Content "$AppRoot\.env" | Where-Object { $_ -match '^AZURE_TOKEN_EXPIRES_ON=' }) -replace 'AZURE_TOKEN_EXPIRES_ON=', ''
if ($exp) {
    $expDt = [DateTimeOffset]::FromUnixTimeSeconds([int64]$exp).LocalDateTime
    Write-Host "Token OK. Expires ~$expDt. Re-run this script before then."
}
Write-Host "App: http://10.72.128.197:8502 (VPN)"
