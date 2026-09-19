# Automatic Backup Script Repository CheckMK-Tools
# Simplified version for Scheduled Task (ASCII characters only)

param(
    [switch]$Unattended
)

$ErrorActionPreference = "Continue"

# === CONFIGURATION ===
$REPO_PATH = (Split-Path $PSScriptRoot -Parent)
$LOCAL_BACKUP_BASE = "C:\CheckMK-Backups"
$LOG_PATH = Join-Path $LOCAL_BACKUP_BASE "logs"
$LOG_FILE = Join-Path $LOG_PATH "backup_$(Get-Date -Format 'yyyy-MM-dd').log"
$TIMESTAMP = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$LOCAL_BACKUP_PATH = Join-Path $LOCAL_BACKUP_BASE $TIMESTAMP
$RETENTION_COUNT = 20

# === EMAIL CONFIGURATION ===
$SMTP_SERVER = "smtp-relay.nethesis.it"
$SMTP_PORT = 587
$SMTP_USE_SSL = $true
$EMAIL_FROM = "checkmk@nethesis.it"
$EMAIL_TO = if ($env:NOTIFY_EMAIL) { $env:NOTIFY_EMAIL } else { "" }
$EMAIL_CREDENTIAL_FILE = Join-Path $LOCAL_BACKUP_BASE "smtp_credential.xml"
$SEND_EMAIL = $true

# === GLOBAL VARIABLES FOR EMAIL ERROR ===
$GLOBAL_ERROR_MESSAGE = ""

Write-Host ""
Write-Host "================================================================"
Write-Host "FULL BACKUP CHECKMK-TOOLS REPOSITORY"
Write-Host "================================================================"
Write-Host ""

# === START GLOBAL TRY FOR ERROR MANAGEMENT ===
try {

# Create backup folder if it does not exist
if (-not (Test-Path $LOCAL_BACKUP_BASE)) {
    New-Item -ItemType Directory -Path $LOCAL_BACKUP_BASE -Force | Out-Null
}

# Verify that the repository exists
if (-not (Test-Path $REPO_PATH)) {
    Write-Host "[ERROR] Repository not found: $REPO_PATH" -ForegroundColor Red
    throw "Repository non trovato: $REPO_PATH"
}

# === CONTROLLO INTEGRITA SCRIPT ===
Write-Host "================================================================"
Write-Host "    CONTROLLO INTEGRITA SCRIPT"
Write-Host "================================================================"
Write-Host ""

# Check WSL availability for bash syntax checking
$wslAvailable = $false
try {
    $null = wsl --version 2>&1
    $wslAvailable = $LASTEXITCODE -eq 0
} catch {
    $wslAvailable = $false
}

if ($wslAvailable) {
    Write-Host "[INFO] WSL available - bash syntax checking enabled" -ForegroundColor Green
} else {
    Write-Host "[WARN] WSL unavailable - limited bash testing" -ForegroundColor Yellow
}

$scriptFiles = Get-ChildItem -Path $REPO_PATH -Recurse -File -ErrorAction SilentlyContinue | 
    Where-Object { 
        $_.FullName -notmatch '\\\.git\\' -and
        $_.FullName -notmatch '\\BACKUP' -and
        $_.FullName -notmatch '\.BACKUP' -and
        $_.FullName -notmatch 'BACKUP-CORRUPTED-' -and
        $_.Name -notmatch '^(LICENSE|README|CHANGELOG|AUTHORS|Dockerfile)$' -and
        $_.Name -notmatch '^\.' -and
        ($_.Extension -in @('.ps1', '.sh', '.bash', '.bat', '.cmd', '.py') -or $_.Extension -eq '') -and
        $_.Name -notmatch '^(test-|debug-|backup-)' # Escludi script di test
    }
$totalScripts = $scriptFiles.Count
$validScripts = 0
$corruptedScripts = 0
$corruptedList = @()

Write-Host "[INFO] Checking $totalScripts script..." -ForegroundColor Cyan

# Whitelist files that may be legitimately empty
$allowedEmptyFiles = @(
    "corrupted-files-list.txt",
    ".gitkeep",
    ".env"
)

foreach ($script in $scriptFiles) {
    $relativePath = $script.FullName.Replace($REPO_PATH, "").TrimStart('\')
    $fileName = $script.Name
    $canBeEmpty = $allowedEmptyFiles -contains $fileName
    
    # Check for non-empty file (unless whitelisted)
    if ($script.Length -eq 0 -and -not $canBeEmpty) {
        $corruptedScripts++
        $corruptedList += "[VUOTO] $relativePath"
        continue
    }
    
    # Determina tipo tramite estensione + shebang (shebang ha precedenza)
    $scriptType = $script.Extension
    
    try {
        $firstLine = Get-Content $script.FullName -First 1 -ErrorAction Stop
        if ($firstLine -match '^#!/.*bash') {
            $scriptType = '.sh'
        } elseif ($firstLine -match '^#!/.*python') {
            $scriptType = '.py'
        } elseif ($script.Extension -eq '') {
            # File without extension and unrecognized shebang: skip
            $validScripts++
            continue
        }
    } catch {
        # Cannot read file, skips
        $validScripts++
        continue
    }
    
    # Check PowerShell syntax with ParseFile
    if ($scriptType -eq ".ps1") {
        try {
            $errors = $null
            $tokens = $null
            $null = [System.Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref]$tokens, [ref]$errors)
            
            if ($errors -and $errors.Count -gt 0) {
                $corruptedScripts++
                $corruptedList += "[SINTASSI PS] $relativePath - $($errors[0].Message)"
                continue
            }
        } catch {
            $corruptedScripts++
            $corruptedList += "[ERRORE PS] $relativePath - $_"
            continue
        }
    }
    
    # Check bash/sh syntax with WSL (bash -n)
    if ($scriptType -in @(".sh", ".bash") -and $wslAvailable) {
        try {
            # Convert Windows path to WSL path
            $wslPath = $script.FullName -replace '\\', '/' -replace '^([A-Z]):', { "/mnt/$($_.Groups[1].Value.ToLower())" }
            
            # Use bash -n for syntax check (does not run the script)
            $bashCheck = wsl bash -n "$wslPath" 2>&1
            $exitCode = $LASTEXITCODE
            if ($exitCode -ne 0) {
                $corruptedScripts++
                $errorMsg = if ($bashCheck) { ($bashCheck | Select-Object -First 2) -join "; " } else { "Syntax error" }
                $corruptedList += "[SINTASSI BASH] $relativePath - $errorMsg"
                continue
            }
        } catch {
            # If bash -n fails, at least try to verify the shebang
            try {
                $firstLine = Get-Content $script.FullName -First 1 -ErrorAction Stop
                if (-not ($firstLine -match '^#!/')) {
                    Write-Host "  [WARN] Shebang mancante: $relativePath" -ForegroundColor DarkYellow
                }
            } catch {
                $corruptedScripts++
                $corruptedList += "[LETTURA] $relativePath - $_"
                continue
            }
        }
    }

    # Python check (basic syntax check)
    if ($scriptType -eq ".py") {
        try {
            $pythonCheck = python -m py_compile "$($script.FullName)" 2>&1
            if ($LASTEXITCODE -ne 0) {
                $corruptedScripts++
                $errorMsg = if ($pythonCheck) { $pythonCheck -join "; " } else { "Syntax error" }
                $corruptedList += "[SINTASSI PY] $relativePath - $errorMsg"
                continue
            }
        } catch {
            # Python not available, skip
        }
    }
    
    # Check Batch/CMD syntax
    if ($scriptType -in @(".bat", ".cmd")) {
        try {
            # cmd /c checks the syntax without running
            $cmdCheck = cmd /c "echo off & call `"$($script.FullName)`" /?" 2>&1
            if ($LASTEXITCODE -ne 0 -and $cmdCheck -match "syntax error|unexpected|invalid") {
                $corruptedScripts++
                $errorMsg = ($cmdCheck | Select-Object -First 2) -join "; "
                $corruptedList += "[SINTASSI BAT] $relativePath - $errorMsg"
                continue
            }
        } catch {
            # Error during verification, but we don't block
            Write-Host "[WARN] Failed to verify: $relativePath" -ForegroundColor DarkYellow
        }
    }
    
    $validScripts++
    if ($validScripts % 100 -eq 0) {
        Write-Host "  Verificati $validScripts / $totalScripts script..." -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "================================================================"
Write-Host "  Script verificati: $totalScripts" -ForegroundColor Gray
Write-Host "  Script validi:     $validScripts" -ForegroundColor Green
Write-Host "  Script corrotti:   $corruptedScripts" -ForegroundColor $(if ($corruptedScripts -eq 0) { "Green" } else { "Red" })
Write-Host "================================================================"
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# CONTROLLO SOGLIA CORRUZIONE MASSIVA
# ═══════════════════════════════════════════════════════════════
$corruptionPercentage = if ($totalScripts -gt 0) { 
    [math]::Round(($corruptedScripts / $totalScripts) * 100, 2) 
} else { 
    0 
}

# 15% Threshold: If more than 15% of the scripts are corrupt, block the backup
$CORRUPTION_THRESHOLD = 15

$pctStr = "$corruptionPercentage%"; Write-Host "Error rate: $pctStr" -ForegroundColor $(if ($corruptionPercentage -gt $CORRUPTION_THRESHOLD) { "Red" } else { "Yellow" })
Write-Host ""

if ($corruptionPercentage -gt $CORRUPTION_THRESHOLD) {
    Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "║ MASSIVE CORRUPTION DETECTED ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝" -ForegroundColor Red
    Write-Host ""
    Write-Host "[CRITICAL ERROR] Massive repository corruption detected!" -ForegroundColor Red
    $pct1 = "$($corruptionPercentage)%"; Write-Host "  • Script corrotti: $corruptedScripts / $totalScripts ($pct1)" -ForegroundColor Red
    $pct2 = "$($CORRUPTION_THRESHOLD)%"; Write-Host "  • Soglia sicurezza: $pct2" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "[BACKUP CANCELED] To avoid propagating corruption to existing backups!" -ForegroundColor Red
    Write-Host ""
    Write-Host "AZIONI CONSIGLIATE:" -ForegroundColor Yellow
    Write-Host "1. Check file encoding (UTF-8 vs ANSI)" -ForegroundColor Gray
    Write-Host "2. Check line endings (CRLF vs LF)" -ForegroundColor Gray
    Write-Host "3. Restore from a previous backup if necessary" -ForegroundColor Gray
    Write-Host "4. Run 'git status' to check for massive changes" -ForegroundColor Gray
    Write-Host "5. Check if there has been an unintentional mass conversion" -ForegroundColor Gray
    Write-Host ""
    
    # Show top 10 errors for diagnostics
    Write-Host "First errors detected (for diagnostics):" -ForegroundColor Yellow
    $corruptedList | Select-Object -First 10 | ForEach-Object {
        Write-Host "  - $_" -ForegroundColor Red
    }
    if ($corruptedList.Count -gt 10) {
        Write-Host "...and other $($corruptedList.Count - 10) errors" -ForegroundColor DarkRed
    }
    Write-Host ""
    
    exit 1
}

# If below threshold, continue with warning
if ($corruptedScripts -gt 0) {
    Write-Host "[WARNING] $corruptedScripts errors found (below $CORRUPTION_THRESHOLD% threshold, backup continues)" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Scripts reported (non-critical errors):" -ForegroundColor Gray
    foreach ($item in $corruptedList) {
        Write-Host "  - $item" -ForegroundColor DarkYellow
    }
    Write-Host ""
    Write-Host "[INFO] Backup proceeds anyway..." -ForegroundColor Cyan
}

Write-Host "[OK] I continue with the backup..." -ForegroundColor Green
Write-Host ""

# Count all files for backup (with exclusion filters)
$allFiles = Get-ChildItem -Path $REPO_PATH -Recurse -File -ErrorAction SilentlyContinue | 
    Where-Object { 
        $_.FullName -notmatch '\\\.git\\' -and
        $_.FullName -notmatch '\\BACKUP' -and
        $_.FullName -notmatch '\.BACKUP' -and
        $_.FullName -notmatch 'BACKUP-CORRUPTED-' -and
        $_.Name -notmatch '^\.' # Escludi file nascosti
    }
$totalFiles = $allFiles.Count

if ($totalFiles -eq 0) {
    Write-Host "[ERROR] No files found in the repository!" -ForegroundColor Red
    exit 1
}

Write-Host "[INFO] $totalFiles files to backup found" -ForegroundColor Cyan
Write-Host ""

if (-not $Unattended) {
    Write-Host "Press any key to continue with the backup..." -ForegroundColor Yellow
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    Write-Host ""
}

# === LOCAL BACKUP ===
Write-Host "================================================================"
Write-Host "LOCAL BACKUP"
Write-Host "================================================================"
Write-Host ""
Write-Host "[INFO] Destinazione: $LOCAL_BACKUP_PATH" -ForegroundColor Gray
Write-Host ""

# Create backup folder
try {
    New-Item -ItemType Directory -Path $LOCAL_BACKUP_PATH -Force | Out-Null
    Write-Host "[OK] Backup folder created" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Failed to create backup folder: $_" -ForegroundColor Red
    exit 1
}

# Copy files
Write-Host ""
Write-Host "[INFO] Copying files..." -ForegroundColor Cyan

$copiedFiles = 0
$errorCount = 0

foreach ($file in $allFiles) {
    $relativePath = $file.FullName.Replace($REPO_PATH, "").TrimStart('\')
    $destinationPath = Join-Path $LOCAL_BACKUP_PATH $relativePath
    $destinationDir = Split-Path $destinationPath -Parent
    
    try {
        if (-not (Test-Path $destinationDir)) {
            New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
        }
        
        Copy-Item -Path $file.FullName -Destination $destinationPath -Force
        $copiedFiles++
        
        if ($copiedFiles % 50 -eq 0) {
            Write-Host "Copied $copiedFiles / $totalFiles file..." -ForegroundColor Gray
        }
    } catch {
        $errorCount++
        Write-Host "[WARN] $relativePath file copy error" -ForegroundColor Yellow
    }
}

Write-Host "[OK] Completed: $copiedFiles copied files" -ForegroundColor Green

if ($errorCount -gt 0) {
    Write-Host "[WARN] $errorCount files not copied" -ForegroundColor Yellow
}

# Calculate local backup size
$backupSize = (Get-ChildItem -Path $LOCAL_BACKUP_PATH -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB

# Network backup is not configured (local-only mode)

# === STATISTICHE ===
Write-Host ""
Write-Host "================================================================"
Write-Host "BACKUP STATISTICS"
Write-Host "================================================================"
Write-Host ""
Write-Host "  LOCALE:" -ForegroundColor Cyan
Write-Host "Copied files: $copiedFiles" -ForegroundColor Gray
Write-Host "Size: $([math]::Round($backupSize, 2)) MB" -ForegroundColor Gray
Write-Host "Path: $LOCAL_BACKUP_PATH" -ForegroundColor Gray
Write-Host ""
Write-Host "  RIEPILOGO RAPIDO:" -ForegroundColor Cyan
Write-Host "    Script verificati: $totalScripts" -ForegroundColor Gray
Write-Host "Backed up files (local): $copiedFiles" -ForegroundColor Gray
Write-Host ""
Write-Host "  Timestamp:        $TIMESTAMP" -ForegroundColor Gray
Write-Host ""

# === RETENTION POLICY ===
Write-Host "================================================================"
Write-Host "CLEANING OLD BACKUPS (Retention)"
Write-Host "================================================================"
Write-Host ""

$existingBackups = Get-ChildItem -Path $LOCAL_BACKUP_BASE -Directory | 
    Where-Object { $_.Name -match [regex]::new("^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$") } |
    Sort-Object Name -Descending

$backupCount = $existingBackups.Count
Write-Host "[INFO] Total backups: $backupCount (retention: $RETENTION_COUNT)" -ForegroundColor Cyan

if ($backupCount -gt $RETENTION_COUNT) {
    $toDelete = $backupCount - $RETENTION_COUNT
    Write-Host "[INFO] $toDelete older backups will be deleted..." -ForegroundColor Yellow
    Write-Host ""
    
    $backupsToDelete = $existingBackups | Select-Object -Skip $RETENTION_COUNT
    
    foreach ($backup in $backupsToDelete) {
        try {
            Write-Host "[DELETE] $($backup.Name)" -ForegroundColor Gray
            Remove-Item -Path $backup.FullName -Recurse -Force -ErrorAction Stop
            Write-Host "[OK] Deleted" -ForegroundColor Green
        } catch {
            Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
        }
    }
    
    Write-Host ""
    Write-Host "[OK] Cleanup complete: Keep latest $RETENTION_COUNT backups" -ForegroundColor Green
} else {
    Write-Host "[INFO] No backups to delete" -ForegroundColor Green
}

Write-Host ""
Write-Host "================================================================"
Write-Host "BACKUP COMPLETED SUCCESSFULLY"
Write-Host "================================================================"
Write-Host ""

# === INVIO EMAIL REPORT ===
if ($SEND_EMAIL) {
    Write-Host "================================================================"
    Write-Host "    INVIO EMAIL REPORT"
    Write-Host "================================================================"
    Write-Host ""
    
    try {
        $emailSubject = "[CheckMK Backup] Completato - $TIMESTAMP"

        # Build email body line by line to avoid PowerShell parser issues with here-strings containing special characters
        $emailBody = ""
        $emailBody += "===============================================================" + "`n"
        $emailBody += "       REPORT BACKUP REPOSITORY CHECKMK-TOOLS" + "`n"
        $emailBody += "===============================================================" + "`n"
        $emailBody += "" + "`n"
        $emailBody += "Data e ora: $TIMESTAMP" + "`n"
        $emailBody += "Host: $env:COMPUTERNAME" + "`n"
        $emailBody += "" + "`n"
        $emailBody += "---------------------------------------------------------------" + "`n"
        $emailBody += "  CONTROLLO INTEGRITA SCRIPT" + "`n"
        $emailBody += "---------------------------------------------------------------" + "`n"
        $emailBody += "Script verificati:     $totalScripts" + "`n"
        $emailBody += "Script validi:         $validScripts" + "`n"
        $emailBody += "Script corrotti:       $corruptedScripts" + "`n"
        if ($corruptedScripts -eq 0) { $stato = "OK" } else { $stato = "WARNING" }
        $emailBody += "Stato:                 $stato" + "`n"
        $emailBody += "" + "`n"
        $emailBody += "---------------------------------------------------------------" + "`n"
        $emailBody += "    RIEPILOGO RAPIDO" + "`n"
        $emailBody += "---------------------------------------------------------------" + "`n"
        $emailBody += "Script verificati:     $totalScripts" + "`n"
        $emailBody += "File backuppati (loc): $copiedFiles" + "`n"
        $emailBody += "" + "`n"
        
        # Add error list if present
        if ($corruptedScripts -gt 0 -and $corruptedList.Count -gt 0) {
            $emailBody += "Script con errori sintassi bash:" + "`n"
            $emailBody += "---------------------------------------------------------------" + "`n"
            foreach ($errorItem in $corruptedList) {
                $emailBody += "  - $errorItem" + "`n"
            }
        }
        
        $emailBody += "" + "`n"
        $emailBody += "---------------------------------------------------------------" + "`n"
        $emailBody += "  BACKUP LOCALE" + "`n"
        $emailBody += "---------------------------------------------------------------" + "`n"
        $bs = [math]::Round($backupSize, 2)
        $emailBody += "File copiati:          $copiedFiles" + "`n"
        $emailBody += "Dimensione:            $bs MB" + "`n"
        $emailBody += "Percorso:              $LOCAL_BACKUP_PATH" + "`n"
        $emailBody += "" + "`n"
        $emailBody += "---------------------------------------------------------------" + "`n"
        $emailBody += "  RETENTION POLICY" + "`n"
        $emailBody += "---------------------------------------------------------------" + "`n"
        $emailBody += "Backup totali:         $backupCount" + "`n"
        $emailBody += "Retention:             $RETENTION_COUNT" + "`n"
        
        if ($backupCount -gt $RETENTION_COUNT) {
            $deleted = $backupCount - $RETENTION_COUNT
            $emailBody += "Backup eliminati:      $deleted" + "`n"
        } else {
            $emailBody += "Backup eliminati:      0" + "`n"
        }
        
        $emailBody += "" + "`n"
        $emailBody += "===============================================================" + "`n"
        $emailBody += "  BACKUP COMPLETATO CON SUCCESSO" + "`n"
        $emailBody += "===============================================================" + "`n"
        $emailBody += "" + "`n"
        $emailBody += "Questo e un messaggio automatico generato dal sistema di backup." + "`n"
        
        # Validate email configuration
        if ([string]::IsNullOrWhiteSpace($EMAIL_TO)) {
            Write-Host "[WARN] NOTIFY_EMAIL environment variable not set. Email skipped." -ForegroundColor Yellow
            Write-Host '[INFO] Set NOTIFY_EMAIL with: [Environment]::SetEnvironmentVariable("NOTIFY_EMAIL", "you@example.com", "User")' -ForegroundColor Cyan
        } elseif (-not (Test-Path $EMAIL_CREDENTIAL_FILE)) {
            Write-Host "[WARN] Credential file not found: $EMAIL_CREDENTIAL_FILE" -ForegroundColor Yellow
            Write-Host "[INFO] Run setup-smtp-credentials.ps1 to configure SMTP credentials" -ForegroundColor Cyan
        } else {
            # Force TLS 1.2 for modern SMTP relay compatibility
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            
            $credential = Import-Clixml -Path $EMAIL_CREDENTIAL_FILE
            
            $smtp = New-Object System.Net.Mail.SmtpClient($SMTP_SERVER, $SMTP_PORT)
            $smtp.EnableSsl = $SMTP_USE_SSL
            $smtp.Credentials = $credential
            $smtp.Timeout = 30000
            
            $mailMessage = New-Object System.Net.Mail.MailMessage($EMAIL_FROM, $EMAIL_TO, $emailSubject, $emailBody)
            $mailMessage.BodyEncoding = [System.Text.Encoding]::UTF8
            $mailMessage.SubjectEncoding = [System.Text.Encoding]::UTF8
            
            try {
                $smtp.Send($mailMessage)
                Write-Host "[OK] Email sent to: $EMAIL_TO" -ForegroundColor Green
                "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Email sent OK to $EMAIL_TO" | Out-File -FilePath $LOG_FILE -Append -Encoding UTF8
            } catch {
                Write-Host "[WARN] Failed to send email: $_" -ForegroundColor Yellow
                "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Email FAILED: $_" | Out-File -FilePath $LOG_FILE -Append -Encoding UTF8
            } finally {
                $mailMessage.Dispose()
                $smtp.Dispose()
            }
        }
        
    } catch {
        Write-Host "[WARN] Unable to send email: $_" -ForegroundColor Yellow
        Write-Host "[INFO] The backup completed correctly" -ForegroundColor Cyan
    }
    
    Write-Host ""
}

exit 0

} catch {
    # === GLOBAL ERROR MANAGEMENT WITH EMAIL SENDING ===
    $GLOBAL_ERROR_MESSAGE = $_.Exception.Message
    $errorDetails = $_.Exception | Out-String
    
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Red
    Write-Host "BACKUP FAILED - CRITICAL ERROR" -ForegroundColor Red
    Write-Host "================================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "[ERROR] $GLOBAL_ERROR_MESSAGE" -ForegroundColor Red
    Write-Host ""
    
    # Send error email
    if ($SEND_EMAIL) {
        try {
            $emailSubject = "[CheckMK Backup] ERRORE - $TIMESTAMP"
            
            $now = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
            $emailBody = ""
            $emailBody += "===============================================================" + "`n"
            $emailBody += "       BACKUP FALLITO - ERRORE CRITICO" + "`n"
            $emailBody += "===============================================================" + "`n"
            $emailBody += "" + "`n"
            $emailBody += "Data e ora: $now" + "`n"
            $emailBody += "Host: $env:COMPUTERNAME" + "`n"
            $emailBody += "Repository: $REPO_PATH" + "`n"
            $emailBody += "" + "`n"
            $emailBody += "---------------------------------------------------------------" + "`n"
            $emailBody += "  DETTAGLIO ERRORE" + "`n"
            $emailBody += "---------------------------------------------------------------" + "`n"
            $emailBody += "$GLOBAL_ERROR_MESSAGE" + "`n"
            $emailBody += "" + "`n"
            $emailBody += "---------------------------------------------------------------" + "`n"
            $emailBody += "  STACK TRACE" + "`n"
            $emailBody += "---------------------------------------------------------------" + "`n"
            $emailBody += "$errorDetails" + "`n"
            $emailBody += "" + "`n"
            $emailBody += "---------------------------------------------------------------" + "`n"
            $emailBody += "  AZIONE RICHIESTA" + "`n"
            $emailBody += "---------------------------------------------------------------" + "`n"
            $emailBody += "Verificare manualmente il sistema di backup." + "`n"
            $emailBody += "Log disponibile in: C:CheckMK-Backupslogs" + "`n"
            $emailBody += "" + "`n"
            $emailBody += "===============================================================" + "`n"
            $emailBody += "  NOTIFICA AUTOMATICA DI ERRORE" + "`n"
            $emailBody += "===============================================================" + "`n"
            $emailBody += "" + "`n"
            $emailBody += "Questo e un messaggio automatico generato dal sistema di backup." + "`n"
            
            if (-not [string]::IsNullOrWhiteSpace($EMAIL_TO) -and (Test-Path $EMAIL_CREDENTIAL_FILE)) {
                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                
                $credential = Import-Clixml -Path $EMAIL_CREDENTIAL_FILE
                
                $smtp = New-Object System.Net.Mail.SmtpClient($SMTP_SERVER, $SMTP_PORT)
                $smtp.EnableSsl = $SMTP_USE_SSL
                $smtp.Credentials = $credential
                $smtp.Timeout = 30000
                
                $mailMessage = New-Object System.Net.Mail.MailMessage($EMAIL_FROM, $EMAIL_TO, $emailSubject, $emailBody)
                $mailMessage.BodyEncoding = [System.Text.Encoding]::UTF8
                $mailMessage.SubjectEncoding = [System.Text.Encoding]::UTF8
                
                try {
                    $smtp.Send($mailMessage)
                    Write-Host "[OK] Error email sent to: $EMAIL_TO" -ForegroundColor Green
                    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Error email sent OK to $EMAIL_TO" | Out-File -FilePath $LOG_FILE -Append -Encoding UTF8
                } catch {
                    Write-Host "[WARN] Failed to send error email: $_" -ForegroundColor Yellow
                    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Error email FAILED: $_" | Out-File -FilePath $LOG_FILE -Append -Encoding UTF8
                } finally {
                    $mailMessage.Dispose()
                    $smtp.Dispose()
                }
            } else {
                Write-Host "[WARN] Unable to send error email: missing credentials or NOTIFY_EMAIL" -ForegroundColor Yellow
            }
            
        } catch {
            Write-Host "[WARN] Failed to send error email: $_" -ForegroundColor Yellow
        }
    }
    
    Write-Host ""
    exit 1
}
