<#
.SYNOPSIS
  Installazione dell'agente CheckMK su Windows, con cmk-agent-ctl in plain
  pull nativo e IP allowlist (supporta piu' di un IP autorizzato).

.DESCRIPTION
  - Download dell'MSI agente CheckMK dal server configurato
  - Installazione/aggiornamento silenzioso (msiexec /quiet)
  - Abilita il plain pull nativo di cmk-agent-ctl.exe
    (delete-all --enable-insecure-connections), niente TLS/certificati custom
  - Chiede interattivamente quali IP autorizzare (uno o piu', separati da
    virgola) e li scrive in cmk-agent-ctl.toml (allowed_ip)

.PARAMETER ServerUrl
  Base Checkmk server URL (default: https://monitor.nethlab.it)

.PARAMETER Site
  Checkmk site name (default: monitoring)

.PARAMETER AllowedIp
  IP da autorizzare nell'allowlist di cmk-agent-ctl, separati da virgola per
  piu' di un IP. Se fornito, salta il prompt interattivo.

.PARAMETER Quick
  Modalita' non interattiva: usa 127.0.0.1 come unico IP autorizzato senza
  chiedere nulla (equivalente a -AllowedIp 127.0.0.1).

.PARAMETER Uninstall
  Disinstalla l'agente CheckMK e rimuove la configurazione cmk-agent-ctl.

.REQUIREMENTS
  PowerShell 5.1+, Windows 64-bit, privilegi amministratore

.USAGE
  powershell -ExecutionPolicy Bypass -File .\install-checkmk-agent-windows.ps1
  powershell -ExecutionPolicy Bypass -File .\install-checkmk-agent-windows.ps1 -AllowedIp 127.0.0.1
  powershell -ExecutionPolicy Bypass -File .\install-checkmk-agent-windows.ps1 -AllowedIp "127.0.0.1,10.0.0.5"
  powershell -ExecutionPolicy Bypass -File .\install-checkmk-agent-windows.ps1 -Quick
  powershell -ExecutionPolicy Bypass -File .\install-checkmk-agent-windows.ps1 -Uninstall
#>

[CmdletBinding()]
param(
    [string]$ServerUrl = "https://monitor.nethlab.it",
    [string]$Site = "monitoring",
    [string]$AllowedIp = "",
    [switch]$Quick,
    [switch]$Uninstall
)

$ScriptVersion = "2.1.0"
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

$CmkAgentDir        = "C:\ProgramData\checkmk\agent"
$CmkAgentCtlToml    = Join-Path $CmkAgentDir "cmk-agent-ctl.toml"
$CmkAgentCtlExe     = "C:\Program Files (x86)\checkmk\service\cmk-agent-ctl.exe"
$DefaultAllowedIp   = "127.0.0.1"

# ===============================
# Utility
# ===============================
function Write-Log {
    param(
        [string]$Message,
        [ValidateSet("INFO", "WARN", "ERROR", "OK")] [string]$Level = "INFO"
    )
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $color = switch ($Level) {
        "ERROR" { "Red" }
        "WARN"  { "Yellow" }
        "OK"    { "Green" }
        default { "White" }
    }
    Write-Host "[$ts] [$Level] $Message" -ForegroundColor $color
}

function Test-Administrator {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p  = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function ConvertTo-IpList {
    # Splits a comma/space-separated string into a de-duplicated array of IPs.
    # Throws on the first malformed entry.
    param([string]$Raw)
    $ips = @()
    foreach ($token in ($Raw -split '[,\s]+')) {
        if (-not $token) { continue }
        if ($token -notmatch '^\d{1,3}(\.\d{1,3}){3}$') {
            throw "IP non valido: '$token' (formato atteso: x.x.x.x)"
        }
        if ($ips -notcontains $token) { $ips += $token }
    }
    return $ips
}

function Read-AllowedIps {
    # Chiede quali IP autorizzare nell'allowlist di cmk-agent-ctl (plain pull).
    # Supporta piu' IP separati da virgola o spazio.
    Write-Host ""
    Write-Host "  Configurazione IP allowlist (cmk-agent-ctl, plain pull nativo):"
    Write-Host "  L'agente accettera' connessioni in chiaro sulla 6556 SOLO da questi IP."
    Write-Host "  Usare $DefaultAllowedIp se il traffico arriva tramite tunnel FRP locale (caso comune),"
    Write-Host "  altrimenti l'IP reale (o piu' IP separati da virgola/spazio) da cui si connette il server CheckMK."
    while ($true) {
        $raw = Read-Host "  IP autorizzati [$DefaultAllowedIp]"
        if (-not $raw) { return @($DefaultAllowedIp) }
        try {
            $ips = ConvertTo-IpList -Raw $raw
        } catch {
            Write-Log $_.Exception.Message "WARN"
            continue
        }
        if ($ips.Count -gt 0) { return $ips }
        Write-Log "Nessun IP valido inserito, riprova." "WARN"
    }
}

function Get-LocalAgentVersion {
    $uninstallPaths = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    foreach ($path in $uninstallPaths) {
        $entry = Get-ItemProperty $path -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -like "*Checkmk Agent*" -or $_.DisplayName -like "*Check_MK Agent*" } |
            Select-Object -First 1
        if ($entry) { return $entry }
    }
    return $null
}

# ===============================
# Agent install/uninstall
# ===============================
function Install-CheckmkAgent {
    $msiUrl = "$ServerUrl/$Site/check_mk/agents/windows/check_mk_agent.msi"
    $tempMsi = Join-Path $env:TEMP "check_mk_agent.msi"
    Write-Log "Download agente CheckMK: $msiUrl" "INFO"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $msiUrl -OutFile $tempMsi -UseBasicParsing

    Write-Log "Installazione MSI (msiexec /quiet)..." "INFO"
    $logPath = Join-Path $env:TEMP "checkmk-agent-install.log"
    $proc = Start-Process msiexec.exe -ArgumentList "/i `"$tempMsi`" /quiet /norestart /l*v `"$logPath`"" -Wait -PassThru
    Remove-Item $tempMsi -ErrorAction SilentlyContinue

    if ($proc.ExitCode -ne 0) {
        throw "msiexec fallito con codice $($proc.ExitCode) - vedi $logPath"
    }
    Write-Log "Agente CheckMK installato" "OK"
}

function Uninstall-CheckmkAgent {
    $entry = Get-LocalAgentVersion
    if (-not $entry) {
        Write-Log "Nessun agente CheckMK installato, nulla da rimuovere" "WARN"
    } else {
        Write-Log "Disinstallazione agente CheckMK ($($entry.DisplayVersion))..." "INFO"
        if ($entry.PSChildName -match '^\{.*\}$') {
            Start-Process msiexec.exe -ArgumentList "/x $($entry.PSChildName) /quiet /norestart" -Wait | Out-Null
        } else {
            Start-Process cmd.exe -ArgumentList "/c $($entry.UninstallString) /quiet" -Wait | Out-Null
        }
        Write-Log "Agente CheckMK disinstallato" "OK"
    }

    if (Test-Path $CmkAgentCtlExe) {
        & $CmkAgentCtlExe delete-all --enable-insecure-connections 2>&1 | Out-Null
    }
    if (Test-Path $CmkAgentDir) {
        Remove-Item -Path $CmkAgentDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Log "Rimossa configurazione: $CmkAgentDir" "OK"
    }
}

# ===============================
# cmk-agent-ctl plain pull (+ IP allowlist, uno o piu' IP)
# ===============================
function Find-CheckmkAgentService {
    $svc = Get-Service | Where-Object {
        $_.Name -eq "CheckmkService" -or
        $_.DisplayName -like "*Checkmk*" -or
        $_.Name -like "*check_mk_agent*"
    } | Select-Object -First 1
    return $svc
}

function Set-PlainPullConfig {
    param([string[]]$AllowedIps)

    if (-not (Test-Path $CmkAgentCtlExe)) {
        throw "cmk-agent-ctl.exe non trovato in: $CmkAgentCtlExe (l'agente e' installato correttamente?)"
    }

    Write-Log "Rimozione registrazione TLS esistente e abilitazione plain pull..." "INFO"
    & $CmkAgentCtlExe delete-all --enable-insecure-connections 2>&1 | ForEach-Object { Write-Log $_ "INFO" }

    if (-not (Test-Path $CmkAgentDir)) {
        New-Item -Path $CmkAgentDir -ItemType Directory -Force | Out-Null
    }
    $ipArray = ($AllowedIps | ForEach-Object { "`"$_`"" }) -join ", "
    Set-Content -Path $CmkAgentCtlToml -Value "allowed_ip = [$ipArray]`n" -Encoding UTF8
    Write-Log "Scritto $CmkAgentCtlToml (allowed_ip=$($AllowedIps -join ', '))" "OK"

    $svc = Find-CheckmkAgentService
    if ($svc) {
        Write-Log "Riavvio servizio '$($svc.DisplayName)' ($($svc.Name))..." "INFO"
        Restart-Service -Name $svc.Name -Force
        Write-Log "Servizio riavviato" "OK"
    } else {
        Write-Log "Servizio agente CheckMK non trovato tramite Get-Service - riavviarlo manualmente" "WARN"
    }
}

# ===============================
# MAIN
# ===============================
try {
    if (-not (Test-Administrator)) { throw "Esegui PowerShell come Amministratore" }
    if (-not [Environment]::Is64BitOperatingSystem) { throw "Richiesto Windows 64-bit" }

    Write-Log "=== install-checkmk-agent-windows.ps1 v$ScriptVersion ===" "OK"

    if ($Uninstall) {
        Uninstall-CheckmkAgent
        Write-Log "=== Disinstallazione completata ===" "OK"
        exit 0
    }

    if ($AllowedIp) {
        $resolvedIps = ConvertTo-IpList -Raw $AllowedIp
        if ($resolvedIps.Count -eq 0) { throw "-AllowedIp non contiene nessun IP valido" }
    } elseif ($Quick) {
        $resolvedIps = @($DefaultAllowedIp)
    } else {
        $resolvedIps = Read-AllowedIps
    }

    Install-CheckmkAgent
    Set-PlainPullConfig -AllowedIps $resolvedIps

    Write-Log "" "INFO"
    Write-Log "=== INSTALLAZIONE COMPLETATA ===" "OK"
    Write-Log "  Agente CheckMK   : porta 6556, plain pull, allowed_ip=$($resolvedIps -join ', ')" "INFO"
    Write-Log "" "INFO"
    Write-Log "Verifica:" "INFO"
    Write-Log "  & '$CmkAgentCtlExe' status" "INFO"
    Write-Log "" "INFO"
    Write-Log "Se questo host deve essere raggiunto tramite tunnel FRP, installare" "INFO"
    Write-Log "separatamente: install-frpc-pc.ps1 (stessa cartella)" "INFO"

    exit 0
}
catch {
    Write-Log "ERRORE: $($_.Exception.Message)" "ERROR"
    exit 1
}
