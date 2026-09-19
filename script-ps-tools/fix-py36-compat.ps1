# Fix Python 3.6 compatibility - remove unsupported reconfigure()

$scriptDir = Join-Path (Split-Path $PSScriptRoot -Parent) "script-check-ns7emote"
$files = Get-ChildItem "$scriptDir\*.py" -File

foreach ($file in $files) {
    $content = Get-Content $file.FullName -Raw
    
    # Removes reconfigure() lines that don't work on Python 3.6
    $newContent = $content -replace "if sys\.stdout\.encoding != 'utf-8':\r?\n\s+sys\.stdout\.reconfigure\(encoding='utf-8', errors='replace'\)\r?\n", ""
    $newContent = $newContent -replace "if sys\.stderr\.encoding != 'utf-8':\r?\n\s+sys\.stderr\.reconfigure\(encoding='utf-8', errors='replace'\)\r?\n", ""
    
    if ($content -ne $newContent) {
        Set-Content -Path $file.FullName -Value $newContent -NoNewline
        Write-Host "Fixed: $($file.Name)" -ForegroundColor Yellow
    }
}

Write-Host "`n Completed: Fix Python 3.6 compatibility" -ForegroundColor Green
Write-Host "os.environ['PYTHONIOENCODING'] sufficient for Python 3.6" -ForegroundColor Cyan
