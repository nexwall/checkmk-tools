# Wrapper for logging backups
$LogFile = "C:\CheckMK-Backups\logs\backup_$(Get-Date -Format 'yyyy-MM-dd').log"
$ErrorFile = "C:\CheckMK-Backups\logs\backup-error.log"

# Ensure that the log folder exists
$LogDir = Split-Path $LogFile -Parent
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

try {
    # Run backups
    & "$PSScriptRoot\backup-sync-complete.ps1" -Unattended *>&1 | Tee-Object -FilePath $LogFile
    
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) {
        throw "Backup fallito con exit code: $LASTEXITCODE"
    }
    
    exit 0
} catch {
    $errorMsg = "ERRORE BACKUP: $($_.Exception.Message)`n$($_.ScriptStackTrace)"
    $errorMsg | Out-File -FilePath $ErrorFile -Append
    Write-Host $errorMsg
    exit 1
}
