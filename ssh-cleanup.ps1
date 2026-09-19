#!/usr/bin/env pwsh
# ssh-cleanup.ps1 - Pulisce socket ControlMaster WSL e job SSH attivi

Write-Host "=== SSH CLEANUP ===" -ForegroundColor Cyan
Write-Host "WARNING: This script closes ControlMaster WSL sockets." -ForegroundColor Red
Write-Host "After cleanup you will need to re-enter the passphrase for checkmk-vps-01/02." -ForegroundColor Yellow
Write-Host ""

# 1. Job PowerShell SSH attivi
Write-Host "`n[1/3] Job PowerShell SSH attivi..." -ForegroundColor Yellow
$jobs = Get-Job | Where-Object { $_.State -in 'Running','Stopped','Completed','Failed' }
if ($jobs) {
    $jobs | Format-Table Id, Name, State, HasMoreData -AutoSize
    $jobs | Stop-Job -ErrorAction SilentlyContinue
    $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
    Write-Host "     Rimossi $($jobs.Count) job" -ForegroundColor Green
} else {
    Write-Host "No active jobs" -ForegroundColor Gray
}

# 2. Socket ControlMaster WSL
Write-Host "`n[2/3] Socket ControlMaster in WSL (~/.ssh/sockets/)..." -ForegroundColor Yellow
$sockets = wsl -d kali-linux bash -c "ls ~/.ssh/sockets/ 2>/dev/null"
if ($sockets) {
    Write-Host "     Socket trovati:" -ForegroundColor Gray
    $sockets | ForEach-Object { Write-Host "       $_" -ForegroundColor Gray }
    wsl -d kali-linux bash -c "for s in ~/.ssh/sockets/*; do ssh -O exit -o ControlPath=\$s dummy 2>/dev/null; done; rm -f ~/.ssh/sockets/*; echo 'Rimossi'"
    Write-Host "     Socket chiusi e rimossi" -ForegroundColor Green
} else {
    Write-Host "No active sockets" -ForegroundColor Gray
}

# 3. Local ports listening (1443, 8080, common tunnels)
Write-Host "`n[3/3] Local tunnel ports listening..." -ForegroundColor Yellow
$ports = netstat -an | Select-String "127\.0\.0\.1:(1443|8080|8443|4430|2222|2333)\s"
if ($ports) {
    $ports | ForEach-Object { Write-Host "     $_" -ForegroundColor Yellow }
    Write-Host "(closed via job removal above)" -ForegroundColor Gray
} else {
    Write-Host "No active tunnel ports" -ForegroundColor Gray
}

Write-Host "`nDone." -ForegroundColor Cyan
