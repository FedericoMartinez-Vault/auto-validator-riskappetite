# Prueba de conectividad desde tu PC (Windows)
# Uso: powershell -File deploy/test-connectivity.ps1

$PrivateIp = "10.72.64.196"
$PublicIp  = "20.228.231.195"
$Port      = 8502

$Key = "$env:USERPROFILE\.ssh\vault-keys\AI_UAT.pem"

Write-Host "=== Clave PEM ===" -ForegroundColor Cyan
if (Test-Path $Key) { Write-Host "OK: $Key" } else { Write-Host "MISSING: $Key - run deploy.md section 0" -ForegroundColor Red }

Write-Host "`n=== Ping IP privada (requiere VPN) ===" -ForegroundColor Cyan
ping -n 2 $PrivateIp

Write-Host "`n=== Ping IP publica ===" -ForegroundColor Cyan
ping -n 2 $PublicIp

Write-Host "`n=== TCP puerto $Port (publica) ===" -ForegroundColor Cyan
$t = Test-NetConnection -ComputerName $PublicIp -Port $Port -WarningAction SilentlyContinue
Write-Host "TcpTestSucceeded: $($t.TcpTestSucceeded)"

Write-Host "`n=== HTTP publica ===" -ForegroundColor Cyan
try {
    $r = Invoke-WebRequest -Uri "http://${PublicIp}:${Port}" -TimeoutSec 10 -UseBasicParsing
    Write-Host "OK HTTP $($r.StatusCode)"
} catch {
    Write-Host "FALLO: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`nURL app: http://${PublicIp}:${Port}" -ForegroundColor Green
