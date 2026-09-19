# Setup Scheduled Task for Automatic Backup
# Runs backup-sync-complete.ps1 every hour

$ErrorActionPreference = "Stop"

Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║ AUTOMATIC REPOSITORY BACKUP SETUP ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan

$TASK_NAME = "CheckMK-Backup-Auto"
$SCRIPT_PATH = Join-Path $PSScriptRoot "backup-sync-complete.ps1"
$LOG_PATH = "C:\CheckMK-Backups\logs"

# Verify that the script exists
if (-not (Test-Path $SCRIPT_PATH)) {
    Write-Host "Script not found: $SCRIPT_PATH" -ForegroundColor Red
    exit 1
}

# ═══════════════════════════════════════════════════════════════════
# CHOICE OF BACKUP FREQUENCY
# ═══════════════════════════════════════════════════════════════════

Write-Host "Choose automatic backup frequency:" -ForegroundColor Yellow
Write-Host ""
Write-Host "1) Every 15 minutes (very frequent)" -ForegroundColor White
Write-Host "2) Every 30 minutes (frequent)" -ForegroundColor White
Write-Host "3) Every hour (recommended)" -ForegroundColor Green
Write-Host "4) Every 2 hours (moderate)" -ForegroundColor White
Write-Host "5) Every 4 hours (light)" -ForegroundColor White
Write-Host "6) Every 6 hours (minimum)" -ForegroundColor White
Write-Host ""

do {
    $scelta = Read-Host "Inserisci il numero della tua scelta (1-6)"
    $sceltaValida = $scelta -match '^[1-6]$'
    if (-not $sceltaValida) {
        Write-Host "Invalid choice. Enter a number from 1 to 6." -ForegroundColor Red
    }
} while (-not $sceltaValida)

# Set the frequency according to your choice
$frequenzaMinuti = switch ($scelta) {
    "1" { 15 }
    "2" { 30 }
    "3" { 60 }
    "4" { 120 }
    "5" { 240 }
    "6" { 360 }
}

$frequenzaOre = $frequenzaMinuti / 60
if ($frequenzaOre -ge 1) {
    if ($frequenzaOre -eq 1) {
        $frequenzaTesto = "ogni ora"
    } else {
        $frequenzaTesto = "ogni $frequenzaOre ore"
    }
} else {
    $frequenzaTesto = "ogni $frequenzaMinuti minuti"
}

Write-Host "`n Frequenza selezionata: $frequenzaTesto" -ForegroundColor Green
Write-Host ""

# Create log folder if it does not exist
if (-not (Test-Path $LOG_PATH)) {
    New-Item -ItemType Directory -Path $LOG_PATH -Force | Out-Null
    Write-Host "Created log folder: $LOG_PATH" -ForegroundColor Green
}

Write-Host "Configuring Scheduled Tasks..." -ForegroundColor Yellow

# Remove existing task if present
$existingTask = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "→ Removing existing task..." -ForegroundColor Gray
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false
}

# Configure action with improved logging and unattended mode
$logFile = "`"$LOG_PATH\backup_`$(Get-Date -Format 'yyyy-MM-dd').log`""
$pwshPath = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $pwshPath) { $pwshPath = "C:\Program Files\PowerShell\7\pwsh.exe" }
$action = New-ScheduledTaskAction `
    -Execute $pwshPath `
    -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"& '$SCRIPT_PATH' -Unattended *>&1 | Tee-Object -FilePath $logFile -Append`""

# Configure triggers with the chosen frequency
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes $frequenzaMinuti)

# Configure settings
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false `
    -DontStopOnIdleEnd `
    -MultipleInstances IgnoreNew `
    -WakeToRun:$false

# Configure principal with S4U (works even without interactive login)
# IMPORTANT: S4U allows execution even with the user disconnected/lock screen
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest

# Registra task
try {
    Register-ScheduledTask `
        -TaskName $TASK_NAME `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Backup automatico $frequenzaTesto del repository checkmk-tools (funziona anche con utente disconnesso)" `
        -Force | Out-Null
    
    Write-Host "Scheduled Task created successfully!" -ForegroundColor Green
} catch {
    Write-Host "Error creating task: $_" -ForegroundColor Red
    exit 1
}

Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║ CONFIGURATION COMPLETE ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Green

Write-Host "Configuration Details:" -ForegroundColor Cyan
Write-Host "   Task Name: $TASK_NAME" -ForegroundColor Gray
Write-Host "   Script: $SCRIPT_PATH" -ForegroundColor Gray
Write-Host "   Frequenza: $frequenzaTesto" -ForegroundColor Yellow
Write-Host "   Log: $LOG_PATH" -ForegroundColor Gray
Write-Host "   User: $env:USERDOMAIN\$env:USERNAME" -ForegroundColor Gray

Write-Host "`n Comandi utili:" -ForegroundColor Yellow
Write-Host "Check tasks:" -ForegroundColor Gray
Write-Host "     Get-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor White
Write-Host "`n Start manually:" -ForegroundColor Gray
Write-Host "Start-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor White
Write-Host "`n   Disabilita temporaneamente:" -ForegroundColor Gray
Write-Host "     Disable-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor White
Write-Host "`n   Riabilita:" -ForegroundColor Gray
Write-Host "     Enable-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor White
Write-Host "`n   Rimuovi task:" -ForegroundColor Gray
Write-Host "     Unregister-ScheduledTask -TaskName '$TASK_NAME' -Confirm:`$false" -ForegroundColor White
Write-Host "`n   Visualizza log ultima esecuzione:" -ForegroundColor Gray
Write-Host "     Get-Content '$LOG_PATH\backup_$(Get-Date -Format 'yyyy-MM-dd').log'" -ForegroundColor White

Write-Host "`n Automatic backup will start in 2 minutes and then $frequencyText!" -ForegroundColor Green
Write-Host ""
