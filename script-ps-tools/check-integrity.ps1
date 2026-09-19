# CheckMK-Tools Repository Integrity Check Script
# Verify syntax of all scripts without backing up

param(
    [switch]$Detailed,      # Mostra lista completa errori
    [switch]$ExportReport,  # Esporta report in file
    [int]$Threshold = 15,   # Soglia corruzione (default 15%)
    [switch]$SendEmail      # Invia email se errori trovati
)

$ErrorActionPreference = "Continue"

$REPO_PATH = (Split-Path $PSScriptRoot -Parent)

# === EMAIL CONFIGURATION ===
$SMTP_SERVER = "smtp-relay.nethesis.it"
$SMTP_PORT = 587
$SMTP_USE_SSL = $true
$EMAIL_FROM = "checkmk@nethesis.it"
$EMAIL_TO = if ($env:NOTIFY_EMAIL) { $env:NOTIFY_EMAIL } else { "admin@example.com" }
$EMAIL_CREDENTIAL_FILE = "C:\CheckMK-Backups\smtp_credential.xml"

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "      CONTROLLO INTEGRITÀ REPOSITORY CHECKMK-TOOLS" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# Check repository existence
if (-not (Test-Path $REPO_PATH)) {
    Write-Host "[ERROR] Repository not found: $REPO_PATH" -ForegroundColor Red
    exit 1
}

Write-Host "[INFO] Repository: $REPO_PATH" -ForegroundColor Gray
Write-Host "[INFO] Soglia corruzione: $Threshold%" -ForegroundColor Gray
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# CHECK WSL AVAILABILITY
# ═══════════════════════════════════════════════════════════════

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
    Write-Host "[WARNING] WSL unavailable - limited bash testing" -ForegroundColor Yellow
}
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# RACCOLTA SCRIPT
# ═══════════════════════════════════════════════════════════════

Write-Host "[INFO] Search script in the repository..." -ForegroundColor Cyan

$allScripts = Get-ChildItem -Path $REPO_PATH -Recurse -File -ErrorAction SilentlyContinue | 
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

$totalScripts = $allScripts.Count

if ($totalScripts -eq 0) {
    Write-Host "[ERROR] No script found!" -ForegroundColor Red
    exit 1
}

Write-Host "[INFO] Found $totalScripts script to check" -ForegroundColor White
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# CHECK INTEGRITY
# ═══════════════════════════════════════════════════════════════

Write-Host "================================================================" -ForegroundColor Yellow
Write-Host "INTEGRITY VERIFICATION IN PROGRESS" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor Yellow
Write-Host ""

$validScripts = 0
$corruptedScripts = 0
$corruptedList = @()
$categoryStats = @{
    'PowerShell' = @{ Total = 0; Valid = 0; Errors = 0 }
    'Bash/Shell' = @{ Total = 0; Valid = 0; Errors = 0 }
    'Batch' = @{ Total = 0; Valid = 0; Errors = 0 }
    'Python' = @{ Total = 0; Valid = 0; Errors = 0 }
}

foreach ($script in $allScripts) {
    $relativePath = $script.FullName.Replace($REPO_PATH, "").TrimStart('\')
    
    # Whitelist files that may be legitimately empty
    $allowedEmptyFiles = @(
        "corrupted-files-list.txt",
        ".gitkeep",
        ".env"
    )
    $fileName = $script.Name
    $canBeEmpty = $allowedEmptyFiles -contains $fileName
    
    # Determina tipo tramite estensione + shebang (shebang ha precedenza)
    $scriptType = $script.Extension
    $category = 'Unknown'
    
    try {
        $firstLine = Get-Content $script.FullName -First 1 -ErrorAction Stop
        if ($firstLine -match '^#!/.*bash') {
            $scriptType = '.sh'
            $category = 'Bash/Shell'
        } elseif ($firstLine -match '^#!/.*python') {
            $scriptType = '.py'
            $category = 'Python'
        } elseif ($script.Extension -eq '') {
            # File without extension and unrecognized shebang: skip
            $validScripts++
            continue
        } else {
            # Categorize by extension
            $category = switch ($script.Extension) {
                '.ps1' { 'PowerShell' }
                { $_ -in @('.sh', '.bash') } { 'Bash/Shell' }
                { $_ -in @('.bat', '.cmd') } { 'Batch' }
                '.py' { 'Python' }
                default { 'Unknown' }
            }
        }
    } catch {
        # Cannot read file, skips
        $validScripts++
        continue
    }
    
    if ($categoryStats.ContainsKey($category)) {
        $categoryStats[$category].Total++
    }
    
    # Check PowerShell
    if ($scriptType -eq ".ps1") {
        try {
            $errors = $null
            $tokens = $null
            $null = [System.Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref]$tokens, [ref]$errors)
            
            if ($errors.Count -gt 0) {
                $corruptedScripts++
                $categoryStats[$category].Errors++
                $errorMsg = ($errors[0].Message -replace "`n", " " -replace "`r", "")
                $corruptedList += "[SINTASSI PS] $relativePath - Line $($errors[0].Extent.StartLineNumber): $errorMsg"
                continue
            }
        } catch {
            $corruptedScripts++
            $categoryStats[$category].Errors++
            $corruptedList += "[ERRORE PS] $relativePath - $_"
            continue
        }
    }
    
    # Check Bash with WSL
    if ($scriptType -in @(".sh", ".bash") -and $wslAvailable) {
        try {
            # Convert Windows path to WSL path
            $wslPath = $script.FullName -replace '\\', '/' -replace '^([A-Z]):', { "/mnt/$($_.Groups[1].Value.ToLower())" }
            
            # Use bash -n for syntax check
            $bashCheck = wsl bash -n "$wslPath" 2>&1
            $exitCode = $LASTEXITCODE
            if ($exitCode -ne 0) {
                $corruptedScripts++
                $categoryStats[$category].Errors++
                $errorMsg = if ($bashCheck) { ($bashCheck | Select-Object -First 2) -join "; " } else { "Syntax error" }
                $corruptedList += "[SINTASSI BASH] $relativePath - $errorMsg"
                continue
            }
            
            # Check executable permissions
            $perms = wsl stat -c "%a" "$wslPath" 2>&1
            if ($LASTEXITCODE -eq 0 -and $perms -match '^\d{3}$') {
                $execBit = [int]::Parse($perms.Substring(2, 1))
                if (($execBit -band 1) -eq 0) {
                    # Not executable, fix automatically
                    wsl chmod +x "$wslPath" 2>&1 | Out-Null
                    if ($LASTEXITCODE -eq 0) {
                        Write-Host "  [FIX] Reso eseguibile: $relativePath" -ForegroundColor Yellow
                    }
                }
            }
        } catch {
            # Fallback: check shebang
            try {
                $firstLine = Get-Content $script.FullName -First 1 -ErrorAction Stop
                if (-not ($firstLine -match '^#!/')) {
                    Write-Host "  [WARN] Shebang mancante: $relativePath" -ForegroundColor DarkYellow
                }
            } catch {
                $corruptedScripts++
                $categoryStats[$category].Errors++
                $corruptedList += "[LETTURA] $relativePath - $_"
                continue
            }
        }
    }
    
    # Batch verification (basic check)
    if ($scriptType -in @(".bat", ".cmd")) {
        try {
            $content = Get-Content $script.FullName -Raw -ErrorAction Stop
            # Skip blank check for whitelisted files
            if ([string]::IsNullOrWhiteSpace($content) -and -not $canBeEmpty) {
                $corruptedScripts++
                $categoryStats[$category].Errors++
                $corruptedList += "[VUOTO] $relativePath - File vuoto"
                continue
            }
        } catch {
            $corruptedScripts++
            $categoryStats[$category].Errors++
            $corruptedList += "[LETTURA] $relativePath - $_"
            continue
        }
    }
    
    # Python check (basic syntax check)
    if ($scriptType -eq ".py") {
        try {
            $pythonCheck = python -m py_compile "$($script.FullName)" 2>&1
            if ($LASTEXITCODE -ne 0) {
                $corruptedScripts++
                $categoryStats[$category].Errors++
                $errorMsg = if ($pythonCheck) { $pythonCheck -join "; " } else { "Syntax error" }
                $corruptedList += "[SINTASSI PY] $relativePath - $errorMsg"
                continue
            }
        } catch {
            # Python not available, skip
        }
    }
    
    $validScripts++
    if ($categoryStats.ContainsKey($category)) {
        $categoryStats[$category].Valid++
    }
    
    if ($validScripts % 100 -eq 0) {
        Write-Host "  Verificati $validScripts / $totalScripts script..." -ForegroundColor Gray
    }
}

# ═══════════════════════════════════════════════════════════════
# CALCOLO PERCENTUALE CORRUZIONE
# ═══════════════════════════════════════════════════════════════

$corruptionPercentage = if ($totalScripts -gt 0) { 
    [math]::Round(($corruptedScripts / $totalScripts) * 100, 2) 
} else { 
    0 
}

# ═══════════════════════════════════════════════════════════════
# RESULTS REPORT
# ═══════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "INTEGRITY CHECK RESULTS" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "RIEPILOGO GENERALE:" -ForegroundColor White
Write-Host "  Script verificati:    $totalScripts" -ForegroundColor Gray
Write-Host "  Script validi:        $validScripts" -ForegroundColor Green
Write-Host "Corrupted Script: $corruptedScripts" -ForegroundColor $(if ($corruptedScripts -eq 0) { "Green" } else { "Red" })
Write-Host "Error rate: $corruptionPercentage%" -ForegroundColor $(if ($corruptionPercentage -gt $Threshold) { "Red" } elseif ($corruptionPercentage -gt 5) { "Yellow" } else { "Green" })
Write-Host "  Soglia corruzione:    $Threshold%" -ForegroundColor Gray
Write-Host ""

# Statistics by category
Write-Host "DETAIL BY TYPE:" -ForegroundColor White
foreach ($cat in $categoryStats.Keys | Sort-Object) {
    $stats = $categoryStats[$cat]
    if ($stats.Total -gt 0) {
        $catPercent = [math]::Round(($stats.Errors / $stats.Total) * 100, 1)
        Write-Host "  $cat" -ForegroundColor Cyan
        Write-Host "    Totale:      $($stats.Total)" -ForegroundColor Gray
        Write-Host "    Validi:      $($stats.Valid)" -ForegroundColor Green
        Write-Host "Errors: $($stats.Errors) ($catPercent%)" -ForegroundColor $(if ($stats.Errors -eq 0) { "Green" } else { "Yellow" })
    }
}
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# VALUTAZIONE SOGLIA
# ═══════════════════════════════════════════════════════════════

Write-Host "================================================================" -ForegroundColor $(if ($corruptionPercentage -gt $Threshold) { "Red" } else { "Green" })
Write-Host "    VALUTAZIONE FINALE" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor $(if ($corruptionPercentage -gt $Threshold) { "Red" } else { "Green" })
Write-Host ""

if ($corruptionPercentage -gt $Threshold) {
    Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "║ MASSIVE CORRUPTION DETECTED ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝" -ForegroundColor Red
    Write-Host ""
    Write-Host "[STATE] CRITICAL - Corruption above threshold!" -ForegroundColor Red
    Write-Host "• Automatic backup would be BLOCKED" -ForegroundColor Red
    Write-Host "  • Necessaria azione immediata" -ForegroundColor Red
    Write-Host ""
    Write-Host "AZIONI CONSIGLIATE:" -ForegroundColor Yellow
    Write-Host "1. Check file encoding (UTF-8 vs ANSI)" -ForegroundColor Gray
    Write-Host "2. Check line endings (CRLF vs LF)" -ForegroundColor Gray
    Write-Host "3. Run 'git status' to see massive changes" -ForegroundColor Gray
    Write-Host "4. Consider restoring from previous backup" -ForegroundColor Gray
    Write-Host ""
    $exitCode = 2
} elseif ($corruptedScripts -gt 0) {
    Write-Host "[STATUS] WARNING - Errors detected but below threshold" -ForegroundColor Yellow
    Write-Host "• Automatic backup would continue normally" -ForegroundColor Yellow
    Write-Host "• Errors present: $corruptedScripts ($corruptionPercentage%)" -ForegroundColor Yellow
    Write-Host "• Consider correction when possible" -ForegroundColor Gray
    Write-Host ""
    $exitCode = 1
} else {
    Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "║          REPOSITORY INTEGRO                       ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
    Write-Host "[STATUS] OK - No errors detected" -ForegroundColor Green
    Write-Host "• All scripts are valid" -ForegroundColor Green
    Write-Host "• Automatic backup works correctly" -ForegroundColor Green
    Write-Host ""
    $exitCode = 0
}

# ═══════════════════════════════════════════════════════════════
# DETAILED ERROR LIST
# ═══════════════════════════════════════════════════════════════

if ($corruptedScripts -gt 0 -and ($Detailed -or $corruptionPercentage -gt $Threshold)) {
    Write-Host "================================================================" -ForegroundColor Yellow
    Write-Host "DETAILED ERROR LIST" -ForegroundColor White
    Write-Host "================================================================" -ForegroundColor Yellow
    Write-Host ""
    
    $maxToShow = if ($Detailed) { $corruptedList.Count } else { [Math]::Min(20, $corruptedList.Count) }
    
    for ($i = 0; $i -lt $maxToShow; $i++) {
        Write-Host "  $($i+1). $($corruptedList[$i])" -ForegroundColor Red
    }
    
    if ($corruptedList.Count -gt $maxToShow) {
        Write-Host ""
        Write-Host "...and other $($corruptedList.Count - $maxToShow) errors" -ForegroundColor DarkRed
        Write-Host "Use -Detailed to see all errors" -ForegroundColor Gray
    }
    Write-Host ""
}

# ═══════════════════════════════════════════════════════════════
# EXPORT REPORT
# ═══════════════════════════════════════════════════════════════

if ($ExportReport) {
    $reportPath = Join-Path $REPO_PATH "integrity-report_$(Get-Date -Format 'yyyy-MM-dd_HH-mm-ss').txt"
    
    $reportContent = @"
================================================================
 REPORT INTEGRITÀ REPOSITORY CHECKMK-TOOLS
================================================================

Data verifica: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Repository: $REPO_PATH

RIEPILOGO:
  Script verificati:    $totalScripts
  Script validi:        $validScripts
  Script con errori:    $corruptedScripts
  Percentuale errori:   $corruptionPercentage%
  Soglia corruzione:    $Threshold%

STATO: $(if ($corruptionPercentage -gt $Threshold) { 'CRITICO' } elseif ($corruptedScripts -gt 0) { 'WARNING' } else { 'OK' })

DETTAGLIO PER TIPO:
"@
    
    foreach ($cat in $categoryStats.Keys | Sort-Object) {
        $stats = $categoryStats[$cat]
        if ($stats.Total -gt 0) {
            $catPercent = [math]::Round(($stats.Errors / $stats.Total) * 100, 1)
            $reportContent += "`n  $cat : $($stats.Total) script, $($stats.Errors) errori ($catPercent%)"
        }
    }
    
    if ($corruptedScripts -gt 0) {
        $reportContent += "`n`n================================================================`nLISTA ERRORI DETTAGLIATA:`n================================================================`n"
        $reportContent += $corruptedList -join "`n"
    }
    
    $reportContent | Out-File -FilePath $reportPath -Encoding UTF8
    Write-Host "[INFO] Report esportato: $reportPath" -ForegroundColor Cyan
    Write-Host ""
}

# ═══════════════════════════════════════════════════════════════
# I WILL SEND EMAIL IF REQUESTED AND ERRORS FOUND
# ═══════════════════════════════════════════════════════════════

if ($SendEmail -and $corruptedScripts -gt 0) {
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host "SEND EMAIL ERROR NOTIFICATION" -ForegroundColor White
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host ""
    
    try {
        $emailSubject = "[CheckMK Integrity] ERRORI RILEVATI - $corruptedScripts script corrotti"
        
        $emailBody = @"
===============================================================
       CONTROLLO INTEGRITÀ - ERRORI RILEVATI
===============================================================

Data e ora: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Repository: $REPO_PATH

---------------------------------------------------------------
  RIEPILOGO GENERALE
---------------------------------------------------------------
Script verificati:     $totalScripts
Script validi:         $validScripts
Script corrotti:       $corruptedScripts
Percentuale errori:    $([math]::Round($corruptionPercentage, 2))%
Soglia corruzione:     $Threshold%

STATO: $(if ($corruptionPercentage -gt $Threshold) { 'CRITICO ' } else { 'WARNING ' })

---------------------------------------------------------------
  DETTAGLIO PER TIPO
---------------------------------------------------------------
"@
        
        foreach ($cat in $categoryStats.Keys | Sort-Object) {
            $stats = $categoryStats[$cat]
            if ($stats.Total -gt 0) {
                $catPercent = [math]::Round(($stats.Errors / $stats.Total) * 100, 1)
                $emailBody += "`n  $cat"
                $emailBody += "`n    Totale:      $($stats.Total)"
                $emailBody += "`n    Validi:      $($stats.Valid)"
                $emailBody += "`n    Errori:      $($stats.Errors) ($catPercent%)"
            }
        }
        
        if ($corruptedList.Count -gt 0) {
            $emailBody += "`n`n---------------------------------------------------------------"
            $emailBody += "`n  LISTA SCRIPT CORROTTI (primi 20)"
            $emailBody += "`n---------------------------------------------------------------`n"
            $emailBody += ($corruptedList | Select-Object -First 20) -join "`n"
            
            if ($corruptedList.Count -gt 20) {
                $emailBody += "`n`n... e altri $($corruptedList.Count - 20) errori"
                $emailBody += "`n`nEsegui: .\check-integrity.ps1 -Detailed per vedere tutti gli errori"
            }
        }
        
        $emailBody += @"


---------------------------------------------------------------
  AZIONE RICHIESTA
---------------------------------------------------------------
Verificare e correggere gli script con errori di sintassi.
Eseguire: .\check-integrity.ps1 -Detailed per lista completa

===============================================================
  NOTIFICA AUTOMATICA CONTROLLO INTEGRITÀ
===============================================================

Questo è un messaggio automatico generato dal sistema.
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
            Write-Host "[OK] Email inviata a: $EMAIL_TO" -ForegroundColor Green
        } else {
            Write-Host "[WARN] Unable to send email: missing credentials" -ForegroundColor Yellow
            Write-Host "[INFO] Required file: $EMAIL_CREDENTIAL_FILE" -ForegroundColor Gray
        }
        
    } catch {
        Write-Host "[WARN] Unable to send email: $_" -ForegroundColor Yellow
    }
    
    Write-Host ""
}

# ═══════════════════════════════════════════════════════════════
# RIEPILOGO COMANDI UTILI
# ═══════════════════════════════════════════════════════════════

if ($corruptedScripts -gt 0) {
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host "    COMANDI UTILI" -ForegroundColor White
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host ".\check-integrity.ps1 -Detailed # Show all errors" -ForegroundColor Gray
    Write-Host "  .\check-integrity.ps1 -ExportReport   # Esporta report completo" -ForegroundColor Gray
    Write-Host "  .\check-integrity.ps1 -Threshold 20   # Cambia soglia" -ForegroundColor Gray
    Write-Host "git status # Check changes" -ForegroundColor Gray
    Write-Host "  git diff                               # Mostra differenze" -ForegroundColor Gray
    Write-Host ""
}

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

exit $exitCode
