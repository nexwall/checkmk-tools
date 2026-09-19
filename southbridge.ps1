#!/usr/bin/env pwsh
# southbridge.ps1 - Double tunnel to srv-monitoring-us via checkmk-vps-02
# srv-monitoring-us side (from tmate):
#   ssh -R 1443:127.0.0.1:443 -N root@<your-checkmk-server> &
#   ssh -R 2222:127.0.0.1:22  -N root@<your-checkmk-server> &
# This script does the PC side:
#   local forward localhost:1443 -> checkmk-vps-02:1443  (HTTPS)
#   local forward localhost:2222 -> checkmk-vps-02:2222  (SSH)

Write-Host "=== SOUTHBRIDGE ===" -ForegroundColor Cyan
Write-Host "HTTPS tunnel: localhost:1443 -> checkmk-vps-02:1443 -> srv-monitoring-us:443" -ForegroundColor Gray
Write-Host "SSH tunnel: localhost:2222 -> checkmk-vps-02:2222 -> srv-monitoring-us:22" -ForegroundColor Gray

# 1. Verify reverse tunnel on checkmk-vps-02 (1443 + 2222)
Write-Host "`n[1/3] Checking reverse tunnel on checkmk-vps-02..." -ForegroundColor Yellow
$check1443 = wsl -d kali-linux bash -c "ssh checkmk-vps-02 'ss -tlnp | grep :1443'" 2>&1
$check2222 = wsl -d kali-linux bash -c "ssh checkmk-vps-02 'ss -tlnp | grep :2222'" 2>&1
if (-not $check1443 -or -not $check2222) {
    if (-not $check1443) {
        Write-Host "WARNING: port 1443 NOT active on checkmk-vps-02!" -ForegroundColor Red
        Write-Host "on srv-monitoring-us: ssh -R 1443:127.0.0.1:443 -N root@<your-checkmk-server> &" -ForegroundColor White
    }
    if (-not $check2222) {
        Write-Host "WARNING: port 2222 NOT active on checkmk-vps-02!" -ForegroundColor Red
        Write-Host "on srv-monitoring-us: ssh -R 2222:127.0.0.1:22 -N root@<your-checkmk-server> &" -ForegroundColor White
    }
    Write-Host "Waiting (Ctrl+C to exit)..." -ForegroundColor Gray
    $timeout = 120
    $elapsed = 0
    while ($elapsed -lt $timeout) {
        Start-Sleep -Seconds 5
        $elapsed += 5
        $check1443 = wsl -d kali-linux bash -c "ssh checkmk-vps-02 'ss -tlnp | grep :1443'" 2>&1
        $check2222 = wsl -d kali-linux bash -c "ssh checkmk-vps-02 'ss -tlnp | grep :2222'" 2>&1
        if ($check1443 -and $check2222) { break }
        Write-Host "     ...attendo ($elapsed/$timeout sec)" -ForegroundColor DarkGray
    }
    if (-not $check1443 -or -not $check2222) {
        Write-Host "Timeout ($timeout sec). Reverse tunnels not ready. I go out." -ForegroundColor Red
        exit 1
    }
}
Write-Host "OK - port 1443 active on checkmk-vps-02" -ForegroundColor Green
Write-Host "OK - port 2222 active on checkmk-vps-02" -ForegroundColor Green

# 2. Free up local ports 1443 and 2222 if busy
Write-Host "`n[2/3] Free local ports if occupied..." -ForegroundColor Yellow
$existing1443 = netstat -an | findstr "127.0.0.1:1443"
$existing2222 = netstat -an | findstr "127.0.0.1:2222"
if ($existing1443 -or $existing2222) {
    wsl -d kali-linux bash -c "pkill -f 'ssh -L 1443' 2>/dev/null; pkill -f 'ssh -L 2222' 2>/dev/null; true" | Out-Null
    Start-Sleep -Seconds 1
    Get-Job | ForEach-Object {
        try { $_.StopJob() } catch {}
        try { Remove-Job -Job $_ -Force } catch {}
    }
    Write-Host "     Job precedenti rimossi" -ForegroundColor Gray
} else {
    Write-Host "Free doors" -ForegroundColor Gray
}

# 3. Start both local forwards in the background via WSL (ControlMaster - no passphrase)
Write-Host "`n[3/3] Starting local forward..." -ForegroundColor Yellow
$jobHttps = Start-Job -ScriptBlock { wsl -d kali-linux bash -c "ssh -L 1443:127.0.0.1:1443 -N checkmk-vps-02" }
$jobSsh   = Start-Job -ScriptBlock { wsl -d kali-linux bash -c "ssh -L 2222:127.0.0.1:2222 -N checkmk-vps-02" }
Start-Sleep -Seconds 2

$listen1443 = netstat -an | findstr "127.0.0.1:1443"
$listen2222 = netstat -an | findstr "127.0.0.1:2222"

if ($listen1443) {
    Write-Host "OK - localhost:1443 listening (Job ID: $($jobHttps.Id))" -ForegroundColor Green
} else {
    Write-Host "ERROR: localhost:1443 not listening!" -ForegroundColor Red
}
if ($listen2222) {
    Write-Host "OK - localhost:2222 listening (Job ID: $($jobSsh.Id))" -ForegroundColor Green
} else {
    Write-Host "ERROR: localhost:2222 not listening!" -ForegroundColor Red
}

if (-not $listen1443 -or -not $listen2222) {
    Write-Host "Check the ControlMaster WSL: wsl -d kali-linux ssh checkmk-vps-02" -ForegroundColor Yellow
    exit 1
}

Write-Host "`n>>> HTTPS: https://localhost:1443 <<<" -ForegroundColor Cyan
Write-Host ">>> SSH:   ssh -p 2222 root@localhost <<<" -ForegroundColor Cyan
Write-Host "`n To close: Stop-Job $($jobHttps.Id),$($jobSsh.Id); Remove-Job $($jobHttps.Id),$($jobSsh.Id)" -ForegroundColor Gray
