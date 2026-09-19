# Automatic Backup Script Repository CheckMK-Tools
# Simplified version for Scheduled Task (ASCII characters only)

param(
    [switch]$Unattended
)

$ErrorActionPreference = "Stop"

# === CONFIGURATION ===
$REPO_PATH = (Split-Path $PSScriptRoot -Parent)
$LOCAL_BACKUP_BASE = "C:\CheckMK-Backups"
$NETWORK_BACKUP_BASE = if ($env:BACKUP_NETWORK_PATH) { "$($env:BACKUP_NETWORK_PATH)\CheckMK-Backups" } else { "" }
$TIMESTAMP = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$LOCAL_BACKUP_PATH = Join-Path $LOCAL_BACKUP_BASE $TIMESTAMP
$NETWORK_BACKUP_PATH = if ($NETWORK_BACKUP_BASE) { Join-Path $NETWORK_BACKUP_BASE $TIMESTAMP } else { "" }
$RETENTION_COUNT = 20

# === EMAIL CONFIGURATION ===
$SMTP_SERVER = "smtp-relay.nethesis.it"
$SMTP_PORT = 587
$SMTP_USE_SSL = $true
$EMAIL_FROM = "checkmk@nethesis.it"
$EMAIL_TO = if ($env:NOTIFY_EMAIL) { $env:NOTIFY_EMAIL } else { "admin@example.com" }
$EMAIL_CREDENTIAL_FILE = Join-Path $LOCAL_BACKUP_BASE "smtp_credential.xml"  # File credenziali crittografato
$SEND_EMAIL = $true  # Email attivata

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
    
    # Determina tipo tramite estensione o shebang
    $scriptType = $script.Extension
    
    if ($script.Extension -eq '') {
        # Files without extension: check shebang
        try {
            $firstLine = Get-Content $script.FullName -First 1 -ErrorAction Stop
            if ($firstLine -match '^#!/.*bash') {
                $scriptType = '.sh'
            } elseif ($firstLine -match '^#!/.*python') {
                $scriptType = '.py'
            } else {
                # Shebang not recognized, jump
                $validScripts++
                continue
            }
        } catch {
            # Cannot read file, skips
            $validScripts++
            continue
        }
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

Write-Host "Error rate: $corruptionPercentage%" -ForegroundColor $(if ($corruptionPercentage -gt $CORRUPTION_THRESHOLD) { "Red" } else { "Yellow" })
Write-Host ""

if ($corruptionPercentage -gt $CORRUPTION_THRESHOLD) {
    Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "║ MASSIVE CORRUPTION DETECTED ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝" -ForegroundColor Red
    Write-Host ""
    Write-Host "[CRITICAL ERROR] Massive repository corruption detected!" -ForegroundColor Red
    Write-Host "  • Script corrotti: $corruptedScripts / $totalScripts ($($corruptionPercentage)%)" -ForegroundColor Red
    Write-Host "  • Soglia sicurezza: $($CORRUPTION_THRESHOLD)%" -ForegroundColor Yellow
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

# === NETWORK BACKUP ===
Write-Host ""
Write-Host "================================================================"
Write-Host "NETWORK BACKUP"
Write-Host "================================================================"
Write-Host ""

$networkCopied = 0
$networkSuccess = $false

# Check network connection
if (Test-Path $NETWORK_BACKUP_BASE) {
    Write-Host "[INFO] Reachable network share" -ForegroundColor Green
    Write-Host "[INFO] Destinazione: $NETWORK_BACKUP_PATH" -ForegroundColor Gray
    Write-Host ""
    
    try {
        # Create network backup folder
        New-Item -ItemType Directory -Path $NETWORK_BACKUP_PATH -Force -ErrorAction Stop | Out-Null
        Write-Host "[OK] Network backup folder created" -ForegroundColor Green
        Write-Host ""
        Write-Host "[INFO] Copying files to network..." -ForegroundColor Cyan
        
        # Copia ricorsiva
        foreach ($file in $allFiles) {
            $relativePath = $file.FullName.Replace($REPO_PATH, "").TrimStart('\')
            $destinationPath = Join-Path $NETWORK_BACKUP_PATH $relativePath
            $destinationDir = Split-Path $destinationPath -Parent
            
            try {
                if (-not (Test-Path $destinationDir)) {
                    New-Item -ItemType Directory -Path $destinationDir -Force -ErrorAction Stop | Out-Null
                }
                
                Copy-Item -Path $file.FullName -Destination $destinationPath -Force -ErrorAction Stop
                $networkCopied++
                
                if ($networkCopied % 50 -eq 0) {
                    Write-Host "Copied $networkCopied / $totalFiles files..." -ForegroundColor Gray
                }
            } catch {
                Write-Host "[WARN] Error copying $relativePath file over network" -ForegroundColor Yellow
            }
        }
        
        Write-Host "[OK] Network backup complete: $networkCopied files copied" -ForegroundColor Green
        $networkSuccess = $true
        
    } catch {
        Write-Host "[ERROR] Network backup failed: $_" -ForegroundColor Red
        Write-Host "[INFO] Local backup is still available" -ForegroundColor Yellow
    }
} else {
    Write-Host "[WARN] Network share unreachable: $NETWORK_BACKUP_BASE" -ForegroundColor Yellow
    Write-Host "[INFO] I continue only with local backup" -ForegroundColor Yellow
}

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
if ($networkSuccess) {
    Write-Host "NET:" -ForegroundColor Cyan
    Write-Host "Files copied: $networkCopied" -ForegroundColor Gray
    Write-Host "Path: $NETWORK_BACKUP_PATH" -ForegroundColor Gray
} else {
    Write-Host "NETWORK: Not available" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "  Timestamp:        $TIMESTAMP" -ForegroundColor Gray
Write-Host ""

# === RETENTION POLICY ===
Write-Host "================================================================"
Write-Host "CLEANING OLD BACKUPS (Retention)"
Write-Host "================================================================"
Write-Host ""

$existingBackups = Get-ChildItem -Path $LOCAL_BACKUP_BASE -Directory | 
    Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$' } |
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
        
        $emailBody = @"
===============================================================
       REPORT BACKUP REPOSITORY CHECKMK-TOOLS
===============================================================

Data e ora: $TIMESTAMP
Host: $env:COMPUTERNAME

---------------------------------------------------------------
  CONTROLLO INTEGRITA SCRIPT
---------------------------------------------------------------
Script verificati:     $totalScripts
Script validi:         $validScripts
Script corrotti:       $corruptedScripts
Stato:                 $(if ($corruptedScripts -eq 0) { "OK" } else { "WARNING" })

"@
        
        # Add error list if present
        if ($corruptedScripts -gt 0 -and $corruptedList.Count -gt 0) {
            $emailBody += "`nScript con errori sintassi bash:`n"
            $emailBody += "---------------------------------------------------------------`n"
            foreach ($errorItem in $corruptedList) {
                $emailBody += "  - $errorItem`n"
            }
        }
        
        $emailBody += @"

---------------------------------------------------------------
  BACKUP LOCALE
---------------------------------------------------------------
File copiati:          $copiedFiles
Dimensione:            $([math]::Round($backupSize, 2)) MB
Percorso:              $LOCAL_BACKUP_PATH

---------------------------------------------------------------
  BACKUP RETE
---------------------------------------------------------------
"@
        
        if ($networkSuccess) {
            $emailBody += @"
Stato:                 COMPLETATO
File copiati:          $networkCopied
Percorso:              $NETWORK_BACKUP_PATH

"@
        } else {
            $emailBody += @"
Stato:                 NON DISPONIBILE
Motivo:                Share di rete non raggiungibile

"@
        }
        
        $emailBody += @"
---------------------------------------------------------------
  RETENTION POLICY
---------------------------------------------------------------
Backup totali:         $backupCount
Retention:             $RETENTION_COUNT
"@
        
        if ($backupCount -gt $RETENTION_COUNT) {
            $deleted = $backupCount - $RETENTION_COUNT
            $emailBody += "Backup eliminati:      $deleted`n"
        } else {
            $emailBody += "Backup eliminati:      0`n"
        }
        
        $emailBody += @"

===============================================================
  BACKUP COMPLETATO CON SUCCESSO
===============================================================

Questo e un messaggio automatico generato dal sistema di backup.
"@
        
        # Prepare credentials if necessary
        $smtpParams = @{
            SmtpServer = $SMTP_SERVER
            Port = $SMTP_PORT
            From = $EMAIL_FROM
            To = $EMAIL_TO
            Subject = $emailSubject
            Body = $emailBody
            Encoding = [System.Text.Encoding]::UTF8
        }
        
        if ($SMTP_USE_SSL) {
            $smtpParams.UseSsl = $true
        }
        
        # Upload encrypted credentials if they exist
        if (Test-Path $EMAIL_CREDENTIAL_FILE) {
            $credential = Import-Clixml -Path $EMAIL_CREDENTIAL_FILE
            $smtpParams.Credential = $credential
        } else {
            Write-Host "[WARN] Credential file not found: $EMAIL_CREDENTIAL_FILE" -ForegroundColor Yellow
            Write-Host "[INFO] Run: .\setup-smtp-credentials.ps1 to configure" -ForegroundColor Cyan
            throw "Credenziali SMTP mancanti"
        }
        
        Send-MailMessage @smtpParams -WarningAction SilentlyContinue
        
        Write-Host "[OK] Email inviata a: $EMAIL_TO" -ForegroundColor Green
        
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
            
            $emailBody = @"
===============================================================
       BACKUP FALLITO - ERRORE CRITICO
===============================================================

Data e ora: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Host: $env:COMPUTERNAME
Repository: $REPO_PATH

---------------------------------------------------------------
  DETTAGLIO ERRORE
---------------------------------------------------------------
$GLOBAL_ERROR_MESSAGE

---------------------------------------------------------------
  STACK TRACE
---------------------------------------------------------------
$errorDetails

---------------------------------------------------------------
  AZIONE RICHIESTA
---------------------------------------------------------------
Verificare manualmente il sistema di backup.
Log disponibile in: C:\CheckMK-Backups\logs\

===============================================================
  NOTIFICA AUTOMATICA DI ERRORE
===============================================================

Questo e un messaggio automatico generato dal sistema di backup.
"@
            
            $smtpParams = @{
                SmtpServer = $SMTP_SERVER
                Port = $SMTP_PORT
                From = $EMAIL_FROM
                To = $EMAIL_TO
                Subject = $emailSubject
                Body = $emailBody
                Encoding = [System.Text.Encoding]::UTF8
            }
            
            if ($SMTP_USE_SSL) {
                $smtpParams.UseSsl = $true
            }
            
            if (Test-Path $EMAIL_CREDENTIAL_FILE) {
                $credential = Import-Clixml -Path $EMAIL_CREDENTIAL_FILE
                $smtpParams.Credential = $credential
                
                Send-MailMessage @smtpParams -WarningAction SilentlyContinue
                Write-Host "[OK] Error email sent to: $EMAIL_TO" -ForegroundColor Green
            } else {
                Write-Host "[WARN] Unable to send email: missing credentials" -ForegroundColor Yellow
            }
            
        } catch {
            Write-Host "[WARN] Failed to send error email: $_" -ForegroundColor Yellow
        }
    }
    
    Write-Host ""
    exit 1
}
