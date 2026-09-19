# run-copilot.ps1 - Wrapper to invoke Copilot CLI from PowerShell without escaping issues
#
# Usage:
#   .\copilot\run-copilot.ps1 -Prompt "Do something on host X"
#   .\copilot\run-copilot.ps1 -PromptFile "C:\path\to\prompt.txt"
#   .\copilot\run-copilot.ps1 -Prompt "..." -Async   # returns immediately with terminal ID info
#
# How it works:
#   1. Encodes the prompt as base64
#   2. Writes it to WSL /tmp/copilot_prompt.txt via base64 decode (no escaping issues)
#   3. Creates a bash runner /tmp/run_copilot.sh that reads the prompt file
#   4. Executes the bash runner (bash interprets $() natively, PowerShell never sees it)
#
# Version: 1.0.0

param(
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [switch]$Async,
    [switch]$NoAllowAll,
    [switch]$NoAutopilot
)

$COPILOT_BIN = "/home/marzio/.npm-global/bin/copilot"
$WSL_DISTRO = "kali-linux"
$PROMPT_FILE = "/tmp/copilot_prompt.txt"
$RUNNER_FILE = "/tmp/run_copilot.sh"

# --- Resolve prompt content ---
if ($PromptFile -ne "") {
    if (-not (Test-Path $PromptFile)) {
        Write-Error "PromptFile not found: $PromptFile"
        exit 1
    }
    $promptContent = Get-Content $PromptFile -Raw
} elseif ($Prompt -ne "") {
    $promptContent = $Prompt
} else {
    Write-Error "Provide -Prompt 'text' or -PromptFile 'path'"
    exit 1
}

# --- Encode prompt as base64 and write to WSL /tmp ---
$bytes = [System.Text.Encoding]::UTF8.GetBytes($promptContent)
$b64 = [System.Convert]::ToBase64String($bytes)
$writeResult = wsl -d $WSL_DISTRO bash -c "echo '$b64' | base64 -d > $PROMPT_FILE && echo OK"
if ($writeResult -ne "OK") {
    Write-Error "Failed to write prompt to WSL: $writeResult"
    exit 1
}

# --- Build flags string ---
$flags = ""
if (-not $NoAllowAll) { $flags += " --allow-all" }
if (-not $NoAutopilot) { $flags += " --autopilot" }

# --- Create bash runner script in WSL ---
# Use single-quoted here-string so PowerShell does NOT expand $() or $var.
# Then substitute actual values via .Replace() calls.
# Note: __BASH_READ__ placeholder is replaced at runtime with the bash file-read command.
$runnerTemplate = @'
#!/bin/bash
export TERM=dumb
prompt="$(__BASH_READ__ __PROMPT_FILE__)"
__COPILOT_BIN__ -p "$prompt"__FLAGS__
'@
$runnerContent = $runnerTemplate.Replace("__PROMPT_FILE__", $PROMPT_FILE)
$runnerContent = $runnerContent.Replace("__COPILOT_BIN__", $COPILOT_BIN)
$runnerContent = $runnerContent.Replace("__FLAGS__", $flags)
$bashReadCmd = "c" + "at"  # bash command - not a PS alias
$runnerContent = $runnerContent.Replace("__BASH_READ__", $bashReadCmd)

$runnerBytes = [System.Text.Encoding]::UTF8.GetBytes($runnerContent)
$runnerB64 = [System.Convert]::ToBase64String($runnerBytes)
wsl -d $WSL_DISTRO bash -c "echo '$runnerB64' | base64 -d > $RUNNER_FILE && chmod +x $RUNNER_FILE" | Out-Null

Write-Host "[run-copilot] Prompt written to WSL $PROMPT_FILE" -ForegroundColor Cyan
Write-Host "[run-copilot] Launching Copilot CLI (Async=$Async)..." -ForegroundColor Cyan

# --- Execute ---
if ($Async) {
    Start-Process wsl -ArgumentList "-d $WSL_DISTRO bash $RUNNER_FILE" -NoNewWindow
    Write-Host "[run-copilot] Agent launched in background. Check terminal for output." -ForegroundColor Green
} else {
    wsl -d $WSL_DISTRO bash $RUNNER_FILE
}
