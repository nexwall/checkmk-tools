# Script Repair Corrupted Scripts
# Repair corrupt scripts in install/checkmk-installer/ using the correct versions

param(
    [switch]$DryRun,        # Simula senza modificare
    [switch]$AutoConfirm    # Salta conferma (usa con cautela)
)

$ErrorActionPreference = "Continue"

$REPO_PATH = (Split-Path $PSScriptRoot -Parent)

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "      RIPARAZIONE SCRIPT CORROTTI" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# STEP 1: SEARCH FOR CORRUPT SCRIPTS
# ═══════════════════════════════════════════════════════════════

Write-Host "[STEP 1] Scan for corrupt scripts..." -ForegroundColor Cyan
Write-Host ""

# Run integrity check only on install/checkmk-installer/
$corruptedScripts = @()
$wslAvailable = $false

# Check WSL
try {
    $null = wsl --version 2>&1
    $wslAvailable = $LASTEXITCODE -eq 0
} catch {
    $wslAvailable = $false
}

if (-not $wslAvailable) {
    Write-Host "[WARNING] WSL not available - limited repair" -ForegroundColor Yellow
    Write-Host ""
}

# Scansiona install/checkmk-installer/
$installerScripts = Get-ChildItem -Path "$REPO_PATH\install\checkmk-installer" -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { 
        $_.Extension -in @('.sh', '.bash') -and
        $_.FullName -notmatch '\\iso-output\\|\\\.git\\'
    }

Write-Host "Found $($installerScripts.Count) bash script in install/checkmk-installer/" -ForegroundColor Gray
Write-Host "Checking integrity..." -ForegroundColor Gray
Write-Host ""

foreach ($script in $installerScripts) {
    $relativePath = $script.FullName.Replace("$REPO_PATH\", "")
    
    # Check with WSL bash -n
    if ($wslAvailable) {
        $wslPath = $script.FullName -replace '\\', '/' -replace '^([A-Z]):', { "/mnt/$($_.Groups[1].Value.ToLower())" }
        $bashCheck = wsl bash -n "$wslPath" 2>&1
        
        if ($LASTEXITCODE -ne 0) {
            $errorMsg = if ($bashCheck) { ($bashCheck | Select-Object -First 1) -join "" } else { "Syntax error" }
            $corruptedScripts += [PSCustomObject]@{
                CorruptedPath = $relativePath
                FullPath = $script.FullName
                FileName = $script.Name
                Error = $errorMsg
                SourcePath = $null
                SourceExists = $false
            }
        }
    }
}

Write-Host "Script corrotti trovati: $($corruptedScripts.Count)" -ForegroundColor $(if ($corruptedScripts.Count -eq 0) { "Green" } else { "Yellow" })
Write-Host ""

if ($corruptedScripts.Count -eq 0) {
    Write-Host "No corrupt scripts found!" -ForegroundColor Green
    Write-Host ""
    exit 0
}

# ═══════════════════════════════════════════════════════════════
# PHASE 2: SEARCH FOR CORRECT VERSIONS
# ═══════════════════════════════════════════════════════════════

Write-Host "[PHASE 2] Search for correct versions..." -ForegroundColor Cyan
Write-Host ""

$repairable = @()
$notFound = @()

foreach ($corrupt in $corruptedScripts) {
    $fileName = $corrupt.FileName
    
    # Search Pattern:
    # 1. script-check-ns7/full/
    # 2. script-check-ns8/full/
    # 3. script-check-proxmox/full/
    # 4. script-tools/full/
    # 5. Ydea-Toolkit/full/
    
    $searchPaths = @(
        "script-check-ns7\full\$fileName",
        "script-check-ns8\full\$fileName",
        "script-check-nsec8\full\$fileName",
        "script-check-proxmox\full\$fileName",
        "script-check-ubuntu\full\$fileName",
        "script-tools\full\$fileName",
        "Ydea-Toolkit\full\$fileName"
    )
    
    $found = $false
    foreach ($searchPath in $searchPaths) {
        $fullSearchPath = Join-Path $REPO_PATH $searchPath
        if (Test-Path $fullSearchPath) {
            $corrupt.SourcePath = $searchPath
            $corrupt.SourceExists = $true
            $repairable += $corrupt
            $found = $true
            break
        }
    }
    
    if (-not $found) {
        $notFound += $corrupt
    }
}

Write-Host "Script riparabili: $($repairable.Count)" -ForegroundColor Green
Write-Host "Scripts not found: $($notFound.Count)" -ForegroundColor $(if ($notFound.Count -eq 0) { "Green" } else { "Yellow" })
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# FASE 3: RIEPILOGO DETTAGLIATO
# ═══════════════════════════════════════════════════════════════

Write-Host "================================================================" -ForegroundColor Yellow
Write-Host "      RIEPILOGO AZIONI" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor Yellow
Write-Host ""

if ($repairable.Count -gt 0) {
    Write-Host "SCRIPTS THAT WILL BE REPAIRED ($($repairable.Count)):" -ForegroundColor Green
    Write-Host ""
    
    $counter = 1
    foreach ($item in $repairable) {
        Write-Host "  $counter. $($item.FileName)" -ForegroundColor White
        Write-Host "     CORROTTO: $($item.CorruptedPath)" -ForegroundColor Red
        Write-Host "     SORGENTE:  $($item.SourcePath)" -ForegroundColor Green
        Write-Host "ERROR: $($item.Error.Substring(0, [Math]::Min(80, $item.Error.Length)))..." -ForegroundColor DarkYellow
        Write-Host ""
        $counter++
    }
}

if ($notFound.Count -gt 0) {
    Write-Host "NOT REPAIRABLE SCRIPTS (source not found):" -ForegroundColor Yellow
    Write-Host ""
    
    foreach ($item in $notFound) {
        Write-Host "    $($item.FileName)" -ForegroundColor Yellow
        Write-Host "     Path: $($item.CorruptedPath)" -ForegroundColor Gray
        Write-Host ""
    }
}

Write-Host "================================================================" -ForegroundColor Yellow
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# FASE 4: CONFERMA
# ═══════════════════════════════════════════════════════════════

if ($repairable.Count -eq 0) {
    Write-Host "No repairable scripts found!" -ForegroundColor Red
    Write-Host ""
    exit 1
}

Write-Host "ACTIONS THAT WILL BE CARRIED OUT:" -ForegroundColor Cyan
Write-Host "• $($repairable.Count) files will be overwritten" -ForegroundColor White
Write-Host "• Corrupted versions will be replaced" -ForegroundColor White
Write-Host "• A backup will be created before editing" -ForegroundColor White
Write-Host ""

if ($DryRun) {
    Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Magenta
    Write-Host "║               MODALITÀ DRY-RUN                   ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝" -ForegroundColor Magenta
    Write-Host ""
    Write-Host "[INFO] Nessuna modifica verrà effettuata" -ForegroundColor Yellow
    Write-Host ""
    exit 0
}

if (-not $AutoConfirm) {
    Write-Host "════════════════════════════════════════════════════════" -ForegroundColor Yellow
    $confirmation = Read-Host "Procedere con la riparazione? (si/no)"
    Write-Host ""
    
    if ($confirmation -ne "si" -and $confirmation -ne "s" -and $confirmation -ne "yes" -and $confirmation -ne "y") {
        Write-Host "Operation canceled by user" -ForegroundColor Red
        Write-Host ""
        exit 0
    }
}

# ═══════════════════════════════════════════════════════════════
# STEP 5: BACKUP
# ═══════════════════════════════════════════════════════════════

Write-Host "[STEP 5] Creating backups..." -ForegroundColor Cyan
Write-Host ""

$backupDir = Join-Path $REPO_PATH "install\checkmk-installer.BACKUP_$(Get-Date -Format 'yyyy-MM-dd_HH-mm-ss')"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

Write-Host "Backup directory: $backupDir" -ForegroundColor Gray
Write-Host ""

foreach ($item in $repairable) {
    $backupPath = Join-Path $backupDir ($item.CorruptedPath -replace '^install\\checkmk-installer\\', '')
    $backupDir = Split-Path $backupPath -Parent
    
    if (-not (Test-Path $backupDir)) {
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    }
    
    Copy-Item $item.FullPath -Destination $backupPath -Force
}

Write-Host "Backup completed: $($repairable.Count) files saved" -ForegroundColor Green
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# FASE 6: RIPARAZIONE
# ═══════════════════════════════════════════════════════════════

Write-Host "[STEP 6] Repair in progress..." -ForegroundColor Cyan
Write-Host ""

$repaired = 0
$failed = 0

foreach ($item in $repairable) {
    $sourcePath = Join-Path $REPO_PATH $item.SourcePath
    
    try {
        Copy-Item $sourcePath -Destination $item.FullPath -Force
        Write-Host "   $($item.FileName)" -ForegroundColor Green
        $repaired++
    } catch {
        Write-Host "$($item.FileName) - Error: $_" -ForegroundColor Red
        $failed++
    }
}

Write-Host ""

# ═══════════════════════════════════════════════════════════════
# STEP 7: VERIFICATION
# ═══════════════════════════════════════════════════════════════

Write-Host "[STEP 7] Check post-repair integrity..." -ForegroundColor Cyan
Write-Host ""

$stillCorrupted = 0

if ($wslAvailable) {
    foreach ($item in $repairable) {
        $wslPath = $item.FullPath -replace '\\', '/' -replace '^([A-Z]):', { "/mnt/$($_.Groups[1].Value.ToLower())" }
        $bashCheck = wsl bash -n "$wslPath" 2>&1
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host "$($item.FileName) - Still corrupt!" -ForegroundColor Yellow
            $stillCorrupted++
        }
    }
}

# ═══════════════════════════════════════════════════════════════
# REPORT FINALE
# ═══════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "      RIPARAZIONE COMPLETATA" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""

Write-Host "RIEPILOGO FINALE:" -ForegroundColor White
Write-Host "  Script analizzati:        $($installerScripts.Count)" -ForegroundColor Gray
Write-Host "  Script corrotti trovati:  $($corruptedScripts.Count)" -ForegroundColor Yellow
Write-Host "  Script riparati:          $repaired" -ForegroundColor Green
Write-Host "  Script falliti:           $failed" -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Red" })
Write-Host "Still Corrupted: $stillCorrupted" -ForegroundColor $(if ($stillCorrupted -eq 0) { "Green" } else { "Yellow" })
Write-Host ""

Write-Host "BACKUPS:" -ForegroundColor White
Write-Host "Path: $backupDir" -ForegroundColor Gray
Write-Host ""

if ($stillCorrupted -gt 0) {
    Write-Host "WARNING: $stillCorrupted scripts are still corrupt" -ForegroundColor Yellow
    Write-Host "   Potrebbero richiedere riparazione manuale" -ForegroundColor Gray
    Write-Host ""
}

if ($notFound.Count -gt 0) {
    Write-Host "ℹ INFO: $($notFound.Count) script does not have a correct version available" -ForegroundColor Cyan
    Write-Host "May require restoring from backup or rewriting" -ForegroundColor Gray
    Write-Host ""
}

Write-Host "PROSSIMI PASSI CONSIGLIATI:" -ForegroundColor Cyan
Write-Host "1. Check operation: .\check-integrity.ps1" -ForegroundColor Gray
Write-Host "  2. Se OK, commit: git add . && git commit -m 'Fix: Riparati script corrotti'" -ForegroundColor Gray
Write-Host "3. If problems, restore: Copy-Item '$backupDir\*' -Destination 'install\checkmk-installer\' -Recurse -Force" -ForegroundColor Gray
Write-Host ""

Write-Host "================================================================" -ForegroundColor Green
Write-Host ""

# Exit code
if ($failed -gt 0) {
    exit 2  # Alcune riparazioni fallite
} elseif ($stillCorrupted -gt 0) {
    exit 1  # Riparazioni completate ma alcuni file ancora corrotti
} else {
    exit 0  # Tutto OK
}
