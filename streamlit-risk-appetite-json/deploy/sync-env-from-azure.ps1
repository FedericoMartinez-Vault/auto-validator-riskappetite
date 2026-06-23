# Build .env from Azure CLI + Key Vault (run while logged in: az login)
# Usage:
#   .\sync-env-from-azure.ps1                                    # local dev
#   .\sync-env-from-azure.ps1 -ForVm                             # VM: managed identity (permanent)
#   .\sync-env-from-azure.ps1 -ForVm -AuthMode Token             # VM: short-lived user token (legacy)
#   .\sync-env-from-azure.ps1 -ForVm -AuthMode KeyVault          # VM: MI + SP secrets from Key Vault

param(
    [string]$Subscription = "VRMS Azure DEV Subscription",
    [string]$KeyVaultName = "AZR-DEV-AI-AF-RDOH-KV",
    [string]$ResourceGroup = "AZR-DEV-AI-AF-RG",
    [string]$FoundryAccount = "azr-dev-foundry-af-1617",
    [string]$FoundryProject = "azr-dev-proj-af-1617",
    [string]$AgentName = "AF-UW-RiskApetite",
    [string]$OutputPath = "",
    [switch]$ForVm,
    [ValidateSet("ManagedIdentity", "Token", "KeyVault")]
    [string]$AuthMode = "ManagedIdentity"
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
    switch ($AuthMode) {
        "Token" {
            $tokenJson = az account get-access-token --resource "https://ai.azure.com" -o json | ConvertFrom-Json
            $expiresOn = [DateTimeOffset]::Parse($tokenJson.expiresOn).ToUnixTimeSeconds()
            $lines += @(
                "USE_AZURE_CLI_AUTH=false",
                "USE_MANAGED_IDENTITY=false",
                "AZURE_ACCESS_TOKEN=$($tokenJson.accessToken)",
                "AZURE_TOKEN_EXPIRES_ON=$expiresOn"
            )
            Write-Host "VM .env: short-lived token (expires $($tokenJson.expiresOn)). Use -AuthMode ManagedIdentity for permanent auth."
        }
        "KeyVault" {
            $lines += @(
                "USE_AZURE_CLI_AUTH=false",
                "USE_MANAGED_IDENTITY=true",
                "KEY_VAULT_NAME=$KeyVaultName",
                "KEY_VAULT_SP_CLIENT_ID_SECRET=foundry-sp-client-id",
                "KEY_VAULT_SP_CLIENT_SECRET_SECRET=foundry-sp-client-secret"
            )
            Write-Host "VM .env: managed identity + Key Vault SP secrets (no expiring token)."
            Write-Host "Infra must run grant-vm-foundry-role.sh and grant-vm-keyvault-role.sh, and store SP secrets in Key Vault."
        }
        default {
            $lines += @(
                "USE_AZURE_CLI_AUTH=false",
                "USE_MANAGED_IDENTITY=true"
            )
            Write-Host "VM .env: managed identity (permanent). Infra must run grant-vm-foundry-role.sh once."
        }
    }
} else {
    $lines += @(
        "USE_AZURE_CLI_AUTH=true",
        "USE_MANAGED_IDENTITY=false"
    )
}

[System.IO.File]::WriteAllText($OutputPath, ($lines -join "`n") + "`n")
Write-Host "Wrote $OutputPath"
