# Build .env from Azure CLI + Key Vault (run while logged in: az login)
# Usage:
#   .\sync-env-from-azure.ps1              # local dev (.env with az cli auth)
#   .\sync-env-from-azure.ps1 -ForVm       # VM deploy (injects short-lived user token)

param(
    [string]$Subscription = "VRMS Azure DEV Subscription",
    [string]$KeyVaultName = "AZR-DEV-AI-AF-RDOH-KV",
    [string]$ResourceGroup = "AZR-DEV-AI-AF-RG",
    [string]$FoundryAccount = "azr-dev-foundry-af-1617",
    [string]$FoundryProject = "azr-dev-proj-af-1617",
    [string]$AgentName = "AF-UW-RiskApetite",
    [string]$OutputPath = "",
    [switch]$ForVm
)

$ErrorActionPreference = "Stop"
$AppRoot = Split-Path $PSScriptRoot -Parent
if (-not $OutputPath) {
    $OutputPath = Join-Path $AppRoot ".env"
}

az account set --subscription $Subscription | Out-Null

$account = az account show -o json | ConvertFrom-Json
$tenantId = $account.tenantId

$projectEndpoint = "https://${FoundryAccount}.services.ai.azure.com/api/projects/${FoundryProject}"

try {
    $kvEndpoint = az keyvault secret show --vault-name $KeyVaultName --name foundry-endpoint --query value -o tsv 2>$null
    if ($kvEndpoint -and $kvEndpoint -match "/api/projects/") {
        $projectEndpoint = $kvEndpoint.TrimEnd("/")
    }
} catch {
    Write-Warning "Key Vault foundry-endpoint not used; using constructed project URL."
}

$lines = @(
    "FOUNDRY_PROJECT_ENDPOINT=$projectEndpoint",
    "FOUNDRY_AGENT_NAME=$AgentName",
    "AZURE_TENANT_ID=$tenantId"
)

if ($ForVm) {
    $tokenJson = az account get-access-token --resource "https://ai.azure.com" -o json | ConvertFrom-Json
    $expiresOn = [DateTimeOffset]::Parse($tokenJson.expiresOn).ToUnixTimeSeconds()
    $lines += @(
        "USE_AZURE_CLI_AUTH=false",
        "USE_MANAGED_IDENTITY=false",
        "AZURE_ACCESS_TOKEN=$($tokenJson.accessToken)",
        "AZURE_TOKEN_EXPIRES_ON=$expiresOn"
    )
    Write-Host "VM .env: injected access token (expires $($tokenJson.expiresOn)). Re-run this script or redeploy to refresh."
} else {
    $lines += @(
        "USE_AZURE_CLI_AUTH=true",
        "USE_MANAGED_IDENTITY=false"
    )
}

[System.IO.File]::WriteAllText($OutputPath, ($lines -join "`n") + "`n")
Write-Host "Wrote $OutputPath"
