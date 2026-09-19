<#
.SYNOPSIS
CheckMK Agent Synchronization Tool for Windows.

.DESCRIPTION
Synchronizes the locally installed Checkmk Windows agent (check_mk_agent.msi)
with the version served by the configured Checkmk site, mirroring the
behavior of the Linux counterpart checkmk-agent-autoupdate-linux.py:
  - Default mode is verify-only (report status, do not touch the system)
  - -Install actually downloads and runs msiexec to upgrade the agent
  - -DryRun shows what would happen without downloading/installing
  - -Force re-installs even when the local and remote versions already match

Local version is read from the Windows "Programs and Features" uninstall
registry key (DisplayVersion), and remote version is read directly from the
Property table of the downloaded MSI (ProductVersion) via the Windows
Installer COM API - both are compared as MSI ProductVersion strings, so no
translation between the "2.5.0p9"-style Linux version string and the MSI's
numeric "2.5.0.9"-style version is needed.

.PARAMETER ServerUrl
Base Checkmk server URL (default: https://monitor.nethlab.it)

.PARAMETER Site
Checkmk site name (default: monitoring)

.PARAMETER Install
Actually install/upgrade the agent if a newer version is available.

.PARAMETER Force
Re-install even if the local and remote versions already match.

.PARAMETER DryRun
Show what would happen without downloading or installing anything.

.EXAMPLE
powershell -File checkmk-agent-autoupdate-windows.ps1 -ServerUrl https://monitor.nethlab.it -Site monitoring

.EXAMPLE
powershell -File checkmk-agent-autoupdate-windows.ps1 -Install -Verbose
#>

[CmdletBinding()]
param(
    [string]$ServerUrl = "https://monitor.nethlab.it",
    [string]$Site = "monitoring",
    [switch]$Install,
    [switch]$Force,
    [switch]$DryRun
)

$ScriptVersion = "1.0.0"
$ErrorActionPreference = "Stop"

function Get-LocalAgentVersion {
    $uninstallPaths = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    foreach ($path in $uninstallPaths) {
        $entry = Get-ItemProperty $path -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -like "*Checkmk Agent*" -or $_.DisplayName -like "*Check_MK Agent*" } |
            Select-Object -First 1
        if ($entry) { return $entry.DisplayVersion }
    }
    return $null
}

function Get-MsiProductVersion {
    param([Parameter(Mandatory)][string]$MsiPath)

    $installer = New-Object -ComObject WindowsInstaller.Installer
    $database = $installer.GetType().InvokeMember(
        "OpenDatabase", "InvokeMethod", $null, $installer, @($MsiPath, 0))
    $view = $database.GetType().InvokeMember(
        "OpenView", "InvokeMethod", $null, $database,
        @("SELECT Value FROM Property WHERE Property='ProductVersion'"))
    $view.GetType().InvokeMember("Execute", "InvokeMethod", $null, $view, $null)
    $record = $view.GetType().InvokeMember("Fetch", "InvokeMethod", $null, $view, $null)
    if ($null -eq $record) { return $null }
    $value = $record.GetType().InvokeMember("StringData", "GetProperty", $null, $record, @(1))
    if ($null -eq $value) { return $null }
    return $value.Trim()
}

function Write-Report {
    param(
        [string]$Mode,
        [string]$TargetVariant,
        [string]$LocalBefore,
        [string]$RemoteVersion,
        [string]$LocalAfter,
        [string]$Action,
        [string]$FinalStatus,
        [string]$ErrorMessage
    )
    Write-Host ("=" * 70)
    Write-Host "CheckMK Agent Synchronization Report (Windows)"
    Write-Host ("=" * 70)
    Write-Host ("SCRIPT_VERSION.......................... {0}" -f $ScriptVersion)
    Write-Host ("TIMESTAMP............................... {0}" -f (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ"))
    Write-Host ("MODE.................................... {0}" -f $Mode)
    Write-Host ("DRY_RUN................................. {0}" -f $DryRun.IsPresent)
    Write-Host ("TARGET_VARIANT.......................... {0}" -f $TargetVariant)
    Write-Host ("CHECKMK_SERVER_URL...................... {0}" -f $ServerUrl)
    Write-Host ("CHECKMK_SITE............................ {0}" -f $Site)
    Write-Host ("INSTALLED_VERSION_BEFORE................ {0}" -f $LocalBefore)
    Write-Host ("REMOTE_PACKAGE_VERSION.................. {0}" -f $RemoteVersion)
    Write-Host ("INSTALLED_VERSION_AFTER................. {0}" -f $LocalAfter)
    Write-Host ("ACTION.................................. {0}" -f $Action)
    Write-Host ("FINAL_STATUS............................ {0}" -f $FinalStatus)
    Write-Host ("ERROR_MESSAGE........................... {0}" -f $ErrorMessage)
    Write-Host ("=" * 70)
}

$mode = if ($DryRun) { "DRY_RUN" } elseif ($Install) { "INSTALL" } else { "VERIFY_ONLY" }
$action = "NO_ACTION"
$finalStatus = $null
$errorMessage = $null
$localAfter = $null

try {
    $localBefore = Get-LocalAgentVersion
    Write-Verbose "Local agent version: $localBefore"

    $msiUrl = "$ServerUrl/$Site/check_mk/agents/windows/check_mk_agent.msi"
    $tempMsi = Join-Path $env:TEMP "check_mk_agent.msi"
    Write-Verbose "Downloading from: $msiUrl"
    Invoke-WebRequest -Uri $msiUrl -OutFile $tempMsi -UseBasicParsing

    $remoteVersion = Get-MsiProductVersion -MsiPath $tempMsi
    Write-Verbose "Remote agent version: $remoteVersion"

    $needsUpdate = ($null -eq $localBefore) -or ($localBefore -ne $remoteVersion) -or $Force.IsPresent

    if (-not $needsUpdate) {
        $finalStatus = "AGENT_ALREADY_ALIGNED"
        Remove-Item $tempMsi -ErrorAction SilentlyContinue
    }
    elseif (-not $Install) {
        $finalStatus = if ($null -eq $localBefore) { "AGENT_NOT_INSTALLED" } else { "AGENT_UPDATE_REQUIRED" }
        $action = "UPDATE_AVAILABLE"
        Remove-Item $tempMsi -ErrorAction SilentlyContinue
    }
    elseif ($DryRun) {
        Write-Host "[DRY-RUN] Would run: msiexec /i `"$tempMsi`" /quiet /norestart"
        $action = "WOULD_INSTALL"
        $finalStatus = "DRY_RUN_OK"
        Remove-Item $tempMsi -ErrorAction SilentlyContinue
    }
    else {
        Write-Verbose "Installing: $tempMsi"
        $proc = Start-Process msiexec.exe -ArgumentList "/i `"$tempMsi`" /quiet /norestart /l*v `"$env:TEMP\checkmk-agent-sync-msi.log`"" -Wait -PassThru
        Remove-Item $tempMsi -ErrorAction SilentlyContinue

        if ($proc.ExitCode -eq 0) {
            $localAfter = Get-LocalAgentVersion
            $action = "INSTALLED"
            $finalStatus = "AGENT_UPDATE_SUCCESS"
        }
        else {
            $action = "INSTALL_FAILED"
            $finalStatus = "AGENT_UPDATE_FAILED"
            $errorMessage = "msiexec exited with code $($proc.ExitCode) - see $env:TEMP\checkmk-agent-sync-msi.log"
        }
    }

    Write-Report -Mode $mode -TargetVariant "msi" -LocalBefore $localBefore -RemoteVersion $remoteVersion `
        -LocalAfter $localAfter -Action $action -FinalStatus $finalStatus -ErrorMessage $errorMessage

    if ($finalStatus -eq "AGENT_UPDATE_FAILED") { exit 1 }
    exit 0
}
catch {
    Write-Report -Mode $mode -TargetVariant "msi" -LocalBefore $localBefore -RemoteVersion $remoteVersion `
        -LocalAfter $localAfter -Action "ERROR" -FinalStatus "AGENT_SYNC_ERROR" -ErrorMessage $_.Exception.Message
    exit 1
}
