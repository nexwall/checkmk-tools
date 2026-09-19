#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Riparazione script corrotti con conferma utente
.DESCRIPTION
    1. Crea backup temporaneo
    2. Ripara i file nella copia temporanea
    3. Mostra report dettagliato
    4. Attende conferma utente
    5. Sostituisce originali con riparati
#>

param(
    [switch]$SkipBackup
)

$ErrorActionPreference = "Stop"
$WORKSPACE = $PSScriptRoot
$TEMP_DIR = Join-Path $WORKSPACE "REPAIR_TEMP_$(Get-Date -Format 'yyyy-MM-dd_HH-mm-ss')"
$REPORT_FILE = Join-Path $TEMP_DIR "repair-report.txt"

# Check WSL
try {
    $null = wsl --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "WSL non disponibile"
    }
} catch {
    Write-Host "[ERROR] WSL not available - needed for bash validation" -ForegroundColor Red
    exit 1
}

Write-Host "`n================================================================" -ForegroundColor Cyan
Write-Host "REPAIR CORRUPT SCRIPTS WITH CONFIRMATION" -ForegroundColor Cyan
Write-Host "================================================================`n" -ForegroundColor Cyan

# STEP 1: Find corrupt files
Write-Host "[STEP 1] Scan for corrupt files..." -ForegroundColor Yellow

$corruptedFiles = @()
$scriptExtensions = @(".sh", ".bash", ".ps1")
$excludeDirs = @("node_modules", ".git", "REPAIR_TEMP_*", "*.BACKUP_*")

Get-ChildItem -Path $WORKSPACE -Recurse -File | Where-Object {
    $_.Extension -in $scriptExtensions -and
    $excludeDirs | ForEach-Object { $file = $_.FullName; $file -notlike "*$_*" } | Where-Object { $_ }
} | ForEach-Object {
    $file = $_
    $isCorrupted = $false
    $errorMsg = ""
    
    # Check bash
    if ($file.Extension -in @(".sh", ".bash")) {
        $wslPath = $file.FullName -replace '\\', '/' -replace '^([A-Z]):', { "/mnt/$($_.Groups[1].Value.ToLower())" }
        $bashCheck = wsl bash -n "$wslPath" 2>&1
        if ($LASTEXITCODE -ne 0) {
            $isCorrupted = $true
            $errorMsg = ($bashCheck -join " ").Substring(0, [Math]::Min(200, ($bashCheck -join " ").Length))
        }
    }
    
    # Check PowerShell
    if ($file.Extension -eq ".ps1" -and -not $isCorrupted) {
        $tokens = $null
        $errors = $null
        $null = [System.Management.Automation.Language.Parser]::ParseFile(
            $file.FullName, [ref]$tokens, [ref]$errors
        )
        if ($errors.Count -gt 0) {
            $isCorrupted = $true
            $errorMsg = ($errors[0].Message).Substring(0, [Math]::Min(200, $errors[0].Message.Length))
        }
    }
    
    if ($isCorrupted) {
        $relativePath = $file.FullName.Replace("$WORKSPACE\", "")
        $corruptedFiles += [PSCustomObject]@{
            FullPath = $file.FullName
            RelativePath = $relativePath
            Name = $file.Name
            Error = $errorMsg
        }
    }
}

Write-Host "Found $($corruptedFiles.Count) corrupt files`n" -ForegroundColor Yellow

if ($corruptedFiles.Count -eq 0) {
    Write-Host "[SUCCESS] No corrupt files found!" -ForegroundColor Green
    exit 0
}

# Filter only Ydea-Toolkit/full and script-tools/full
$targetFiles = $corruptedFiles | Where-Object { 
    $_.RelativePath -like "Ydea-Toolkit\full\*" -or 
    $_.RelativePath -like "script-tools\full\*" 
}

if ($targetFiles.Count -eq 0) {
    Write-Host "[INFO] No files to repair in Ydea-Toolkit/full or script-tools/full" -ForegroundColor Cyan
    Write-Host "[INFO] Remaining corrupted files: $($corruptedFiles.Count)" -ForegroundColor Cyan
    $corruptedFiles | Format-Table RelativePath, @{L='Error';E={$_.Error.Substring(0,[Math]::Min(80,$_.Error.Length))}}
    exit 0
}

Write-Host "[INFO] Files selected for repair: $($targetFiles.Count)" -ForegroundColor Cyan
$targetFiles | Format-Table RelativePath

# STEP 2: Create temporary backup
Write-Host "`n[STEP 2] Creating temporary backup..." -ForegroundColor Yellow

New-Item -ItemType Directory -Path $TEMP_DIR -Force | Out-Null
$backupDir = Join-Path $TEMP_DIR "backup"
$workingDir = Join-Path $TEMP_DIR "working"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
New-Item -ItemType Directory -Path $workingDir -Force | Out-Null

$targetFiles | ForEach-Object {
    $file = $_
    $destBackup = Join-Path $backupDir $file.RelativePath
    $destWorking = Join-Path $workingDir $file.RelativePath
    
    # Create directory
    $null = New-Item -ItemType Directory -Path (Split-Path $destBackup) -Force
    $null = New-Item -ItemType Directory -Path (Split-Path $destWorking) -Force
    
    # Copy files
    Copy-Item $file.FullPath -Destination $destBackup -Force
    Copy-Item $file.FullPath -Destination $destWorking -Force
}

Write-Host "Backup created in: $backupDir" -ForegroundColor Green
Write-Host "Work directory: $workingDir`n" -ForegroundColor Green

# FASE 3: Analizza e ripara
Write-Host "[PHASE 3] Analysis and repair in progress..." -ForegroundColor Yellow

$repairLog = @()
$repairedCount = 0
$failedCount = 0

foreach ($file in $targetFiles) {
    $workingFile = Join-Path $workingDir $file.RelativePath
    Write-Host "`nAnalysis: $($file.Name)" -ForegroundColor Cyan
    
    $content = Get-Content $workingFile -Raw
    $fixed = $false
    $changes = @()
    
    # Problema comune: righe concatenate senza newline
    if ($content -match '[a-z]\)[a-zA-Z]') {

        # Fix: add newline after closing brackets
        $content = $content -replace '(\))([\$a-zA-Z_])', "`$1`n`$2"
        $changes += "- Aggiunte newline dopo parentesi chiuse"
        $fixed = $true
    }
    
    # Problem: Lines concatenated with 'fi' or 'done'
    if ($content -match '([a-z]+)(fi|done|then|else)([a-zA-Z])') {
        $content = $content -replace '([a-z]+)(fi)([a-zA-Z])', "`$1`n`$2`n`$3"
        $content = $content -replace '([a-z]+)(done)([a-zA-Z])', "`$1`n`$2`n`$3"
        $content = $content -replace '([a-z]+)(then)([a-zA-Z])', "`$1`n`$2`n`$3"
        $content = $content -replace '([a-z]+)(else)([a-zA-Z])', "`$1`n`$2`n`$3"
        $changes += "- Separate keyword bash (fi, done, then, else)"
        $fixed = $true
    }
    
    # Problema: caratteri corrotti tipo ┬¡ãÆ
    if ($content -match '[┬¡ãÆ├┤│─└┘┌┐]') {
        $content = $content -replace '[┬¡ãÆ├┤│─└┘┌┐]+', ''
        $changes += "- Rimossi caratteri corrotti Unicode"
        $fixed = $true
    }
    
    if ($fixed) {
        Set-Content -Path $workingFile -Value $content -NoNewline -Encoding UTF8
        
        # Check if repaired
        $wslPath = $workingFile -replace '\\', '/' -replace '^([A-Z]):', { "/mnt/$($_.Groups[1].Value.ToLower())" }
        $bashCheck = wsl bash -n "$wslPath" 2>&1
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "SUCCESSFULLY REPAIRED" -ForegroundColor Green
            $repairedCount++
            $repairLog += [PSCustomObject]@{
                File = $file.RelativePath
                Status = " Riparato"
                Changes = ($changes -join "; ")
            }
        } else {
            Write-Host "Partial repair (still errors)" -ForegroundColor Yellow
            $failedCount++
            $repairLog += [PSCustomObject]@{
                File = $file.RelativePath
                Status = " Parziale"
                Changes = ($changes -join "; ")
            }
        }
    } else {
        Write-Host "   Nessuna riparazione automatica disponibile" -ForegroundColor Red
        $failedCount++
        $repairLog += [PSCustomObject]@{
            File = $file.RelativePath
            Status = " Fallito"
            Changes = "Nessuna riparazione trovata"
        }
    }
}

# FASE 4: Report
Write-Host "`n================================================================" -ForegroundColor Cyan
Write-Host "    REPORT RIPARAZIONE" -ForegroundColor Cyan
Write-Host "================================================================`n" -ForegroundColor Cyan

$report = @"
RIEPILOGO:
  File analizzati:         $($targetFiles.Count)
  File riparati:           $repairedCount
  Riparazioni parziali:    $failedCount
  Data: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

DETTAGLIO RIPARAZIONI:

"@

$repairLog | ForEach-Object {
    $report += "`n$($_.Status) $($_.File)`n"
    $report += "   $($_.Changes)`n"
}

$report += "`n`nLOCAZIONI:`n"
$report += "  Backup originali: $backupDir`n"
$report += "  File riparati:    $workingDir`n"

Write-Host $report
$report | Out-File -FilePath $REPORT_FILE -Encoding UTF8

Write-Host "`nReport saved in: $REPORT_FILE`n" -ForegroundColor Green

# STEP 5: Confirm user
Write-Host "================================================================" -ForegroundColor Yellow
Write-Host "Do you want to replace the original files with the repaired ones?" -ForegroundColor Yellow
Write-Host "- Backup to: $backupDir" -ForegroundColor Gray
Write-Host "- Repaired files: $repairedCount to $($targetFiles.Count)" -ForegroundColor Gray
Write-Host "================================================================`n" -ForegroundColor Yellow

$response = Read-Host "Procedere con la sostituzione? (si/no)"

if ($response -ne "si") {
    Write-Host "`n[CANCELED] No files modified." -ForegroundColor Yellow
    Write-Host "The repaired files are available in: $workingDir" -ForegroundColor Cyan
    exit 0
}

# FASE 6: Sostituzione
Write-Host "`n[STEP 6] Replacing files..." -ForegroundColor Yellow

$successCount = 0
$errorCount = 0

foreach ($file in $targetFiles) {
    $workingFile = Join-Path $workingDir $file.RelativePath
    
    # Verifica se è stato riparato
    $logEntry = $repairLog | Where-Object { $_.File -eq $file.RelativePath -and $_.Status -eq " Riparato" }
    
    if ($logEntry) {
        try {
            Copy-Item $workingFile -Destination $file.FullPath -Force
            Write-Host "$($file.Name)" -ForegroundColor Green
            $successCount++
        } catch {
            Write-Host "$($file.Name): $($_.Exception.Message)" -ForegroundColor Red
            $errorCount++
        }
    }
}

Write-Host "`n================================================================" -ForegroundColor Cyan
Write-Host "COMPLETED" -ForegroundColor Cyan
Write-Host "================================================================`n" -ForegroundColor Cyan

Write-Host "Files successfully replaced: $successCount" -ForegroundColor Green
Write-Host "Errors during replacement: $errorCount" -ForegroundColor $(if($errorCount -gt 0){"Red"}else{"Green"})
Write-Host "`nPermanent backup to: $backupDir" -ForegroundColor Cyan
Write-Host "Complete report in: $REPORT_FILE`n" -ForegroundColor Cyan

if ($successCount -gt 0) {
    Write-Host "[TIP] Run '.\check-integrity.ps1' to check final status`n" -ForegroundColor Yellow
}
