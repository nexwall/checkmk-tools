# Full Backup Script CheckMK-Tools Repository
# Local + optional backup to network share (configure BACKUP_NETWORK_PATH env var)

param(
    [switch]$Unattended  # Modalità automatica senza prompt
)

$ErrorActionPreference = "Stop"

$REPO_PATH = (Split-Path $PSScriptRoot -Parent)
$LOCAL_BACKUP_BASE = "C:\CheckMK-Backups"
$TIMESTAMP = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$LOCAL_BACKUP_PATH = Join-Path $LOCAL_BACKUP_BASE $TIMESTAMP

Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║ FULL BACKUP CHECKMK-TOOLS REPOSITORY ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan

# ═══════════════════════════════════════════════════════════════════
# CONTROLLO INTEGRITÀ SCRIPT
# ═══════════════════════════════════════════════════════════════════

Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Yellow
Write-Host "║ CHECK SCRIPT INTEGRITY ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Yellow

function Test-ScriptIntegrity {
    param(
        [string]$ScriptPath
    )
    
    $relativePath = $ScriptPath.Replace($REPO_PATH, "").TrimStart('\')
    
    # Check file existence
    if (-not (Test-Path $ScriptPath)) {
        Write-Host "File not found: $relativePath" -ForegroundColor Red
        return $false
    }
    
    # Skip check empty for files that may legitimately be empty
    $allowedEmptyFiles = @(
        "corrupted-files-list.txt",
        ".gitkeep",
        ".env"
    )
    
    $fileName = Split-Path $ScriptPath -Leaf
    $canBeEmpty = $allowedEmptyFiles -contains $fileName
    
    # Check that the file is not empty (unless it is whitelisted)
    $fileInfo = Get-Item $ScriptPath
    if ($fileInfo.Length -eq 0 -and -not $canBeEmpty) {
        Write-Host "Empty file: $relativePath" -ForegroundColor Red
        return $false
    }
    
    # For PowerShell files, check the syntax
    if ($ScriptPath -like "*.ps1") {
        try {
            $errors = $null
            $tokens = $null
            $null = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$tokens, [ref]$errors)
            
            if ($errors.Count -gt 0) {
                Write-Host "Syntax errors in: $relativePath" -ForegroundColor Red
                foreach ($parseError in $errors) {
                    Write-Host "  └─ Linea $($parseError.Extent.StartLineNumber): $($parseError.Message)" -ForegroundColor Red
                }
                return $false
            }
        } catch {
            Write-Host "Failed to parse: $relativePath" -ForegroundColor Red
            Write-Host "  └─ $($_.Exception.Message)" -ForegroundColor Red
            return $false
        }
    }
    
    # For batch/cmd files, check basic
    elseif ($ScriptPath -like "*.bat" -or $ScriptPath -like "*.cmd") {
        try {
            $content = Get-Content $ScriptPath -Raw -ErrorAction Stop
            if ([string]::IsNullOrWhiteSpace($content)) {
                Write-Host "Corrupt or empty file: $relativePath" -ForegroundColor Red
                return $false
            }
        } catch {
            Write-Host "Could not read: $relativePath" -ForegroundColor Red
            Write-Host "  └─ $($_.Exception.Message)" -ForegroundColor Red
            return $false
        }
    }
    
    # For configuration files (.service, .timer, .socket, .conf, .env, .template)
    elseif ($ScriptPath -match '\.(service|timer|socket|conf|env|template)$') {
        try {
            $content = Get-Content $ScriptPath -Raw -ErrorAction Stop
            if ([string]::IsNullOrWhiteSpace($content)) {
                Write-Host "Corrupt or empty file: $relativePath" -ForegroundColor Red
                return $false
            }
        } catch {
            Write-Host "Could not read: $relativePath" -ForegroundColor Red
            Write-Host "  └─ $($_.Exception.Message)" -ForegroundColor Red
            return $false
        }
    }
    
    # For bash/shell/python/other files, check contents and shebang
    else {
        try {
            $content = Get-Content $ScriptPath -Raw -ErrorAction Stop
            # Skip checks for empty content for whitelisted files
            if ([string]::IsNullOrWhiteSpace($content) -and -not $canBeEmpty) {
                Write-Host "Corrupt or unreadable file: $relativePath" -ForegroundColor Red
                return $false
            }
            # For scripts without extension, warn if shebang is missing but don't block
            if ($ScriptPath -notlike "*.*") {
                $firstLine = ($content -split "`n")[0].Trim()
                if ($firstLine -notmatch '^#!') {
                    Write-Host "Missing shebang (may not be script): $relativePath" -ForegroundColor Yellow
                    # Don't block, continue checking
                }
            }
        } catch {
            Write-Host "Could not read: $relativePath" -ForegroundColor Red
            Write-Host "  └─ $($_.Exception.Message)" -ForegroundColor Red
            return $false
        }
    }
    
    Write-Host " $relativePath" -ForegroundColor Green
    return $true
}

Write-Host "Checking critical scripts...`n" -ForegroundColor Cyan

# Verify that the repository path exists
if (-not (Test-Path $REPO_PATH)) {
    Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "║ CONFIGURATION ERROR ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Red
    
    Write-Host "BACKUP INTERRUPTED: Repository path not found!" -ForegroundColor Red
    Write-Host "Configured path: $REPO_PATH" -ForegroundColor Yellow
    Write-Host "Check the `$REPO_PATH variable in the script.`n" -ForegroundColor Yellow
    
    exit 1
}

Write-Host " Repository: $REPO_PATH`n" -ForegroundColor Gray

$allValid = $true
$checkedScripts = 0
$corruptedScripts = 0

# Find ALL files in the repository by folder
Write-Host "Search for files in the repository by folder..." -ForegroundColor Cyan

# Get all root folders
$mainFolders = Get-ChildItem -Path $REPO_PATH -Directory -ErrorAction SilentlyContinue | 
    Where-Object { $_.Name -notmatch '^\.git$' } | 
    Sort-Object Name

# Files in the root
$rootFiles = Get-ChildItem -Path $REPO_PATH -File -ErrorAction SilentlyContinue | 
    Where-Object { 
        $_.Extension -notmatch '\.(log|tmp|cache|lock|swp|bak|zip|sha256|md5)$' -and
        $_.Name -notmatch '^\.gitignore$|^\.gitattributes$'
    }

$allScripts = @()
$folderStats = @()

# Add root file
if ($rootFiles.Count -gt 0) {
    $allScripts += $rootFiles
    $folderStats += [PSCustomObject]@{
        Folder = "(root)"
        Count = $rootFiles.Count
    }
}

# Process each root folder
foreach ($folder in $mainFolders) {
    $folderFiles = Get-ChildItem -Path $folder.FullName -Recurse -File -ErrorAction SilentlyContinue | 
        Where-Object { 
            $_.FullName -notmatch '\\\.git\\' -and
            $_.Extension -notmatch '\.(log|tmp|cache|lock|swp|bak|zip|sha256|md5)$' -and
            $_.Name -notmatch '^\.gitignore$|^\.gitattributes$'
        }
    
    if ($folderFiles.Count -gt 0) {
        $allScripts += $folderFiles
        $folderStats += [PSCustomObject]@{
            Folder = $folder.Name
            Count = $folderFiles.Count
        }
    }
}

$totalScripts = $allScripts.Count

if ($totalScripts -eq 0) {
    Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "║ NO FILES FOUND ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Red
    
    Write-Host "BACKUP INTERRUPTED: No files found!" -ForegroundColor Red
    Write-Host "Verify that the repository path is correct.`n" -ForegroundColor Yellow
    
    exit 1
}

Write-Host "Found $totalScripts files to check`n" -ForegroundColor White

# Show statistics per folder
Write-Host "File distribution by folder:" -ForegroundColor Cyan
foreach ($stat in $folderStats) {
    Write-Host "$($stat.Folder): $($stat.Count) file" -ForegroundColor Gray
}
Write-Host ""

# Check each file
foreach ($script in $allScripts) {
    $checkedScripts++
    
    # Show progress every 25 files
    if ($checkedScripts % 25 -eq 0) {
        Write-Host "Checked $checkedScripts / $totalScripts files..." -ForegroundColor Gray
    }
    
    if (-not (Test-ScriptIntegrity -ScriptPath $script.FullName)) {
        $allValid = $false
        $corruptedScripts++
    }
}

Write-Host "`n" -NoNewline

# Mostra riepilogo
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Gray
Write-Host "Riepilogo controllo:" -ForegroundColor White
Write-Host "• Checked files: $checkedScripts" -ForegroundColor Green
Write-Host "• Valid files: $($checkedScripts - $corruptedScripts)" -ForegroundColor $(if ($corruptedScripts -eq 0) { "Green" } else { "Yellow" })
Write-Host "• Corrupted files: $corruptedScripts" -ForegroundColor $(if ($corruptedScripts -eq 0) { "Green" } else { "Red" })
Write-Host "═══════════════════════════════════════════════════════`n" -ForegroundColor Gray

if (-not $allValid) {
    Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "║ CORRUPT FILES DETECTED ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Red
    
    Write-Host "BACKUP INTERRUPTED: $corruptedScripts files corrupted or with errors." -ForegroundColor Red
    Write-Host "Please fix the above errors before proceeding with the backup.`n" -ForegroundColor Yellow
    
    exit 1
}

Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║ INTEGRITY CHECKED ($checkedScripts file) ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Green

# Pause to allow the results to be seen
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "Integrity check completed:" -ForegroundColor White
Write-Host "• Total checked files: $checkedScripts" -ForegroundColor Green
Write-Host "• Valid files: $($checkedScripts - $corruptedScripts)" -ForegroundColor Green
Write-Host "• Corrupted files: $corruptedScripts" -ForegroundColor $(if ($corruptedScripts -eq 0) { "Green" } else { "Red" })
Write-Host "═══════════════════════════════════════════════════════`n" -ForegroundColor Cyan

if (-not $Unattended) {
    Write-Host "Press any key to continue with the backup..." -ForegroundColor Yellow
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    Write-Host ""
}

# ═══════════════════════════════════════════════════════════════════
# START BACKUP
# ═══════════════════════════════════════════════════════════════════

Write-Host " Repository locale: $REPO_PATH" -ForegroundColor Gray
Write-Host "Local backup: $LOCAL_BACKUP_PATH" -ForegroundColor Gray

# Create local backup folder
Write-Host "Creating local backup folder..." -ForegroundColor Yellow
if (-not (Test-Path $LOCAL_BACKUP_BASE)) {
    New-Item -ItemType Directory -Path $LOCAL_BACKUP_BASE -Force | Out-Null
}
New-Item -ItemType Directory -Path $LOCAL_BACKUP_PATH -Force | Out-Null
Write-Host "Folder created: $LOCAL_BACKUP_PATH`n" -ForegroundColor Green

# Function to copy files
function Copy-BackupFiles {
    param(
        [string]$DestinationPath
    )
    
    Write-Host "Copy file to $DestinationPath..." -ForegroundColor Yellow
    
    $excludeDirs = @('.git', 'node_modules', '.vagrant', 'obj', 'bin')
    $excludeFiles = @('*.log', '*.tmp', '*.cache', 'Thumbs.db', '.DS_Store')

    $itemsToCopy = Get-ChildItem -Path $REPO_PATH -Recurse | Where-Object {
        $item = $_
        $exclude = $false
        
        # Exclude directories
        foreach ($dir in $excludeDirs) {
            if ($item.FullName -match [regex]::Escape("\$dir\")) {
                $exclude = $true
                break
            }
        }
        
        # Exclude temporary files
        if (-not $exclude -and $item -is [System.IO.FileInfo]) {
            foreach ($pattern in $excludeFiles) {
                if ($item.Name -like $pattern) {
                    $exclude = $true
                    break
                }
            }
        }
        
        return -not $exclude
    }

    $totalItems = $itemsToCopy.Count
    $copied = 0

    foreach ($item in $itemsToCopy) {
        $relativePath = $item.FullName.Substring($REPO_PATH.Length + 1)
        $destPath = Join-Path $DestinationPath $relativePath
        
        if ($item.PSIsContainer) {
            New-Item -ItemType Directory -Path $destPath -Force -ErrorAction SilentlyContinue | Out-Null
        } else {
            $destDir = Split-Path $destPath -Parent
            if (-not (Test-Path $destDir)) {
                New-Item -ItemType Directory -Path $destDir -Force | Out-Null
            }
            Copy-Item -Path $item.FullName -Destination $destPath -Force
            $copied++
            
            if ($copied % 50 -eq 0) {
                Write-Host "Copied $copied / $totalItems file..." -ForegroundColor Cyan
            }
        }
    }

    Write-Host "Completed: $copied copied files`n" -ForegroundColor Green
    return $copied
}

# Local backup
$localCopied = Copy-BackupFiles -DestinationPath $LOCAL_BACKUP_PATH

# Network backup removed — local-only mode

# Statistiche
Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║ BACKUP STATISTICS ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Green

$localSize = (Get-ChildItem -Path $LOCAL_BACKUP_PATH -Recurse -File | Measure-Object -Property Length -Sum).Sum
$localSizeMB = [math]::Round($localSize / 1MB, 2)

Write-Host "LOCAL BACKUP:" -ForegroundColor Cyan
Write-Host "Files copied: $localCopied" -ForegroundColor White
Write-Host "Size: $localSizeMB MB" -ForegroundColor White
Write-Host "Path: $LOCAL_BACKUP_PATH`n" -ForegroundColor White

Write-Host " Timestamp:        $TIMESTAMP`n" -ForegroundColor Cyan

# Count previous local backups
$previousBackups = Get-ChildItem -Path $LOCAL_BACKUP_BASE -Directory | 
    Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$' } |
    Sort-Object Name -Descending

Write-Host "Available local backups: $($previousBackups.Count)" -ForegroundColor Gray

# Automatic retention - keep only the last 10 backups
$RETENTION_COUNT = 10

if ($previousBackups.Count -gt $RETENTION_COUNT) {
    $backupsToDelete = $previousBackups | Select-Object -Skip $RETENTION_COUNT
    $deleteCount = $backupsToDelete.Count
    
    Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Yellow
    Write-Host "║ CLEANING OLD BACKUPS (Retention) ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Yellow
    
    Write-Host "Found $($previousBackups.Count) backup, retention set to $RETENTION_COUNT" -ForegroundColor Yellow
    Write-Host "$deleteCount older backups will be deleted...`n" -ForegroundColor Gray
    
    foreach ($backup in $backupsToDelete) {
        try {
            Write-Host "Deletion: $($backup.Name)" -ForegroundColor Gray
            Remove-Item -Path $backup.FullName -Recurse -Force -ErrorAction Stop
            Write-Host "Eliminated" -ForegroundColor Green
        } catch {
            Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
    
    Write-Host "`n Cleanup complete: Keep latest $RETENTION_COUNT backups`n" -ForegroundColor Green
}

Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║ BACKUP COMPLETED SUCCESSFULLY ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Green
