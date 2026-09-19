# Check Automatic Backup Status
# Show last run results and log

$ErrorActionPreference = "Stop"

$TASK_NAME = "CheckMK-Backup-Auto"
$LOG_PATH = "C:\CheckMK-Backups\logs"

Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║ AUTOMATIC BACKUP STATUS ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan

# Verify that the task exists
$task = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "Task '$TASK_NAME' not found!" -ForegroundColor Red
    Write-Host "Run 'setup-backup-task.ps1' to set it up." -ForegroundColor Yellow
    exit 1
}

# Ottieni info task
$taskInfo = Get-ScheduledTaskInfo -TaskName $TASK_NAME

Write-Host "Task Status:" -ForegroundColor Yellow
Write-Host "Name: $TASK_NAME" -ForegroundColor Gray
Write-Host "State: $($task.State)" -ForegroundColor $(if ($task.State -eq "Ready") { "Green" } else { "Yellow" })

# Ultima esecuzione
if ($taskInfo.LastRunTime) {
    $tempoTrascorso = (Get-Date) - $taskInfo.LastRunTime
    $tempoTestoDa = if ($tempoTrascorso.Days -gt 0) {
        "$($tempoTrascorso.Days) giorni fa"
    } elseif ($tempoTrascorso.Hours -gt 0) {
        "$($tempoTrascorso.Hours) ore fa"
    } elseif ($tempoTrascorso.Minutes -gt 0) {
        "$($tempoTrascorso.Minutes) minuti fa"
    } else {
        "pochi secondi fa"
    }
    
    Write-Host "   Ultima esecuzione: $($taskInfo.LastRunTime.ToString('yyyy-MM-dd HH:mm:ss')) ($tempoTestoDa)" -ForegroundColor Gray
    
    # Last execution result
    if ($taskInfo.LastTaskResult -eq 0) {
        Write-Host "Result: Success (0x0)" -ForegroundColor Green
    } else {
        Write-Host "Result: Error (0x$($taskInfo.LastTaskResult.ToString('X')))" -ForegroundColor Red
    }
} else {
    Write-Host "Last run: Never run" -ForegroundColor Yellow
}

# Prossima esecuzione
if ($taskInfo.NextRunTime) {
    $tempoMancante = $taskInfo.NextRunTime - (Get-Date)
    $tempoTestoTra = if ($tempoMancante.Days -gt 0) {
        "$($tempoMancante.Days) giorni"
    } elseif ($tempoMancante.Hours -gt 0) {
        "$($tempoMancante.Hours) ore"
    } elseif ($tempoMancante.Minutes -gt 0) {
        "$($tempoMancante.Minutes) minuti"
    } else {
        "meno di 1 minuto"
    }
    
    Write-Host "   Prossima esecuzione: $($taskInfo.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss')) (tra $tempoTestoTra)" -ForegroundColor Gray
}

# Number of executions
Write-Host "   Totale esecuzioni: $($taskInfo.NumberOfMissedRuns)" -ForegroundColor Gray

Write-Host ""

# ═══════════════════════════════════════════════════════════════════
# LOG ULTIMA ESECUZIONE
# ═══════════════════════════════════════════════════════════════════

$logFile = Join-Path $LOG_PATH "backup_$(Get-Date -Format 'yyyy-MM-dd').log"

if (Test-Path $logFile) {
    Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Yellow
    Write-Host "║            LOG ULTIMA ESECUZIONE                    ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Yellow
    
    $logContent = Get-Content $logFile -Tail 50
    
    # Cerca messaggi importanti nel log
    $errori = $logContent | Select-String -Pattern "|ERROR|ERRORE|Failed" -SimpleMatch
    $successi = $logContent | Select-String -Pattern "|SUCCESS|COMPLETATO|Backup completato" -SimpleMatch
    
    if ($errori) {
        Write-Host "Found $($errori.Count) errors in the log:" -ForegroundColor Red
        foreach ($errore in $errori | Select-Object -First 5) {
            Write-Host "$error" -ForegroundColor Red
        }
        Write-Host ""
    }
    
    if ($successi) {
        Write-Host "$($successes.Count) success messages found" -ForegroundColor Green
        Write-Host ""
    }
    
    Write-Host "Last 20 lines of the log:" -ForegroundColor Cyan
    Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor Gray
    $logContent | Select-Object -Last 20 | ForEach-Object {
        $color = if ($_ -match "|ERROR|ERRORE") {
            "Red"
        } elseif ($_ -match "|SUCCESS") {
            "Green"
        } elseif ($_ -match "|WARNING") {
            "Yellow"
        } else {
            "White"
        }
        Write-Host $_ -ForegroundColor $color
    }
    Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor Gray
    Write-Host ""
    Write-Host " Log completo: $logFile" -ForegroundColor Gray
} else {
    Write-Host "No logs found for today." -ForegroundColor Yellow
    Write-Host "The task may not have run yet today." -ForegroundColor Gray
}

# ═══════════════════════════════════════════════════════════════════
# RECENT BACKUPS
# ═══════════════════════════════════════════════════════════════════

Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║ RECENT BACKUPS (Local) ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan

$backupPath = "C:\CheckMK-Backups"
if (Test-Path $backupPath) {
    $backups = Get-ChildItem -Path $backupPath -Directory | 
        Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$' } |
        Sort-Object CreationTime -Descending |
        Select-Object -First 10
    
    if ($backups) {
        Write-Host "Last 10 backups:" -ForegroundColor Yellow
        foreach ($backup in $backups) {
            $size = (Get-ChildItem -Path $backup.FullName -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
            $age = (Get-Date) - $backup.CreationTime
            $ageText = if ($age.Days -gt 0) { "$($age.Days)g" } 
                      elseif ($age.Hours -gt 0) { "$($age.Hours)h" }
                      else { "$($age.Minutes)m" }
            
            Write-Host "$($backup.Name) - $([math]::Round($size, 2)) MB - $ageText ago" -ForegroundColor Gray
        }
        
        $totalSize = ($backups | ForEach-Object { 
            (Get-ChildItem -Path $_.FullName -Recurse | Measure-Object -Property Length -Sum).Sum 
        } | Measure-Object -Sum).Sum / 1GB
        
        Write-Host "`n Total occupied space: $([math]::Round($totalSize, 2)) GB" -ForegroundColor Cyan
    } else {
        Write-Host "No backups found." -ForegroundColor Yellow
    }
} else {
    Write-Host "Backup folder not found: $backupPath" -ForegroundColor Red
}

Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║ REPORT COMPLETED ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Green

Write-Host " Comandi rapidi:" -ForegroundColor Yellow
Write-Host "Back up now: Start-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor White
Write-Host "Disable backup: Disable-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor White
Write-Host "Re-enable backup: Enable-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor White
Write-Host "Recheck status: .\check-backup-status.ps1" -ForegroundColor White
Write-Host ""
