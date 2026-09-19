# Wrapper for performing backups in unattended mode with logging
$ErrorActionPreference = "Continue"

$SCRIPT_PATH = Join-Path $PSScriptRoot "backup-simple.ps1"
$LOG_PATH = "C:\CheckMK-Backups\logs"
$LOG_FILE = Join-Path $LOG_PATH "backup_$(Get-Date -Format 'yyyy-MM-dd').log"

# Create log folder if it does not exist
if (-not (Test-Path $LOG_PATH)) {
    New-Item -ItemType Directory -Path $LOG_PATH -Force | Out-Null
}

# Record start of execution
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Inizio backup automatico..." | Out-File -FilePath $LOG_FILE -Append -Encoding UTF8

# Network share check removed — local-only mode
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Backup locale (rete non configurata)" | Out-File -FilePath $LOG_FILE -Append -Encoding UTF8

# Run backups
try {
    & $SCRIPT_PATH -Unattended 2>&1 | Out-File -FilePath $LOG_FILE -Append -Encoding UTF8
    $exitCode = $LASTEXITCODE
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Backup completato (exit code: $exitCode)" | Out-File -FilePath $LOG_FILE -Append -Encoding UTF8
    exit $exitCode
} catch {
    "ERRORE: $_" | Out-File -FilePath $LOG_FILE -Append -Encoding UTF8
    exit 1
}
