# Quick Backup Script Repository CheckMK-Tools
# QUICK version without integrity check (to be used after check-integrity.ps1)
# Optimized for Python conversion workflow

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
$EMAIL_CREDENTIAL_FILE = Join-Path $LOCAL_BACKUP_BASE "smtp_credential.xml"
$SEND_EMAIL = $true

# === GLOBAL VARIABLES FOR EMAIL ERROR ===
$GLOBAL_ERROR_MESSAGE = ""

Write-Host ""
Write-Host "================================================================"
Write-Host "FAST BACKUP REPOSITORY CHECKMK-TOOLS"
Write-Host "================================================================"
Write-Host ""
Write-Host "[INFO] QUICK mode - integrity check DISABLED" -ForegroundColor Cyan
Write-Host "[INFO] Run check-integrity.ps1 separately if necessary" -ForegroundColor Gray
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
        $emailSubject = "[CheckMK Backup] Quick Backup Completato - $TIMESTAMP"
        
        $emailBody = @"
===============================================================
       REPORT BACKUP VELOCE REPOSITORY CHECKMK-TOOLS
===============================================================

Data e ora: $TIMESTAMP
Host: $env:COMPUTERNAME
Modalita: QUICK (senza controllo integrita)

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

Nota: Questo backup e stato eseguito in modalita QUICK 
      (senza controllo integrita script).
      Eseguire check-integrity.ps1 separatamente se necessario.

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
            $emailSubject = "[CheckMK Backup] ERRORE Quick Backup - $TIMESTAMP"
            
            $emailBody = @"
===============================================================
       BACKUP FALLITO - ERRORE CRITICO
===============================================================

Data e ora: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Host: $env:COMPUTERNAME
Repository: $REPO_PATH
Modalita: QUICK (senza controllo integrita)

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
