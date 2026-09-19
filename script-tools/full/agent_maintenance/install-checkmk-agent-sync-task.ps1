<#
.SYNOPSIS
Installs checkmk-agent-autoupdate-windows.ps1 as a daily Windows Scheduled Task.

.DESCRIPTION
Registers a Scheduled Task ("CheckmkAgentSync") that runs
checkmk-agent-autoupdate-windows.ps1 daily as SYSTEM, mirroring the systemd
checkmk-agent-sync.timer used on Linux clients. Verify-only by default -
pass -Install to also enable real upgrades (adds -Install to the task's
arguments), matching the Linux deployment convention where verify-only
is the safe default and -Install is an explicit opt-in per host.

.PARAMETER ServerUrl
Base Checkmk server URL (default: https://monitor.nethlab.it)

.PARAMETER Site
Checkmk site name (default: monitoring)

.PARAMETER Install
Also enable real agent upgrades (adds -Install to the scheduled command).

.PARAMETER TimeOfDay
Daily run time, HH:mm, local time (default: 03:00).

.EXAMPLE
powershell -File install-checkmk-agent-sync-task.ps1 -ServerUrl https://monitor.nethlab.it -Site monitoring

.EXAMPLE
powershell -File install-checkmk-agent-sync-task.ps1 -Install
#>

[CmdletBinding()]
param(
    [string]$ServerUrl = "https://monitor.nethlab.it",
    [string]$Site = "monitoring",
    [switch]$Install,
    [string]$TimeOfDay = "03:00"
)

$ErrorActionPreference = "Stop"

$TaskName = "CheckmkAgentSync"
$ScriptPath = Join-Path $PSScriptRoot "checkmk-agent-autoupdate-windows.ps1"
$LogPath = "C:\ProgramData\checkmk-agent-sync\checkmk-agent-sync.log"

$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "This script must be run from an elevated (Run as Administrator) PowerShell session - Register-ScheduledTask requires admin rights."
}

if (-not (Test-Path $ScriptPath)) {
    throw "checkmk-agent-autoupdate-windows.ps1 not found next to this installer: $ScriptPath"
}

New-Item -ItemType Directory -Path (Split-Path $LogPath) -Force | Out-Null

$installFlag = if ($Install) { " -Install" } else { "" }
$argumentList = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" -ServerUrl `"$ServerUrl`" -Site `"$Site`"$installFlag *>> `"$LogPath`""

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argumentList
$trigger = New-ScheduledTaskTrigger -Daily -At $TimeOfDay
$trigger.RandomDelay = "PT5M"
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "[OK] Scheduled task '$TaskName' installed (daily at $TimeOfDay, mode: $(if ($Install) { 'INSTALL' } else { 'VERIFY_ONLY' }))"
Write-Host "     Log: $LogPath"
Write-Host "     Run now to test:  Start-ScheduledTask -TaskName $TaskName"
Write-Host "     Check status:     Get-ScheduledTaskInfo -TaskName $TaskName"
