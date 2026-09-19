<#
.SYNOPSIS
  Installazione interattiva di frpc (FRP client) su Windows come Task Scheduler.

.DESCRIPTION
  - Download frpc v0.64.0 da GitHub
  - Installazione in C:\Program Files\frp
  - Config frpc.toml formato [common] con notazione dotted (auth.method, auth.token, tls.enable)
  - Registrazione Task Scheduler per avvio automatico
  - Avvio immediato del processo

.REQUIREMENTS
  PowerShell 5.1+, Windows 64-bit, privilegi amministratore

.USAGE
  Esegui con bypass ExecutionPolicy:
  
  powershell -ExecutionPolicy Bypass -File .\install-frpc-pc.ps1
  
  Oppure click destro → "Esegui con PowerShell"
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

# ===============================
# Config fissa
# ===============================
$FrpVersion  = "0.64.0"
$InstallPath = "C:\Program Files\frp"
$FrpcExePath = Join-Path $InstallPath "frpc.exe"
$ConfigPath  = Join-Path $InstallPath "frpc.toml"
$TaskName    = "frpc-client"

$DownloadUrl = "https://github.com/fatedier/frp/releases/download/v$FrpVersion/frp_${FrpVersion}_windows_amd64.zip"
$TempDir     = Join-Path $env:TEMP ("frp-install-" + (Get-Date -Format "yyyyMMdd-HHmmss"))

# ===============================
# Utility
# ===============================
function Write-Log {
  param(
    [string]$Message,
    [ValidateSet("INFO","WARN","ERROR","OK")] [string]$Level = "INFO"
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

function Set-ExecutionPolicyBypass {
  try {
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
    Write-Log "ExecutionPolicy Process=BYPASS (solo questa sessione)" "OK"
  } catch {
    Write-Log "Impossibile impostare ExecutionPolicy Process" "WARN"
  }

  try {
    $cu = Get-ExecutionPolicy -Scope CurrentUser
    if ($cu -eq "Undefined" -or $cu -eq "Restricted") {
      Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
      Write-Log "ExecutionPolicy CurrentUser=RemoteSigned" "OK"
    }
  } catch {
    Write-Log "ExecutionPolicy CurrentUser non modificabile (GPO?)" "WARN"
    Write-Log "In futuro usa: powershell -ExecutionPolicy Bypass -File <script>" "WARN"
  }
}

function Read-NonEmpty($Prompt) {
  do { $v = Read-Host $Prompt } while ([string]::IsNullOrWhiteSpace($v))
  return $v.Trim()
}

function Read-Int($Prompt) {
  while ($true) {
    $v = Read-Host $Prompt
    if ([int]::TryParse($v, [ref]$null) -and $v -ge 1 -and $v -le 65535) {
      return [int]$v
    }
    Write-Log "Porta non valida (1-65535)" "WARN"
  }
}

function Stop-And-Remove-Task {
  # Stop existing frpc process
  $frpcProcess = Get-Process -Name "frpc" -ErrorAction SilentlyContinue
  if ($frpcProcess) {
    Write-Log "Chiusura processo frpc esistente (PID: $($frpcProcess.Id))" "WARN"
    Stop-Process -Name "frpc" -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
  }
  
  # Rimuovi task esistente
  $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if ($existingTask) {
    Write-Log "Rimozione task esistente '$TaskName'" "WARN"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
  }
}

function Add-DefenderExclusion {
  Write-Log "Configurazione esclusioni Windows Defender..." "INFO"

  try {
    # Add exclusion for temp extraction dir (Defender can quarantine frpc.exe
    # here during Expand-Archive, before it's even copied to $InstallPath)
    Add-MpPreference -ExclusionPath $TempDir -ErrorAction Stop
    Write-Log "Esclusione temp aggiunta: $TempDir" "OK"

    # Add exclusion for directory
    Add-MpPreference -ExclusionPath $InstallPath -ErrorAction Stop
    Write-Log "Esclusione path aggiunta: $InstallPath" "OK"

    # Add exclusion for executable
    Add-MpPreference -ExclusionPath $FrpcExePath -ErrorAction Stop
    Write-Log "Esclusione exe aggiunta: $FrpcExePath" "OK"

    # Add exclusion for process
    Add-MpPreference -ExclusionProcess "frpc.exe" -ErrorAction Stop
    Write-Log "Esclusione processo aggiunta: frpc.exe" "OK"

    # CRITICAL: frpc-specific ThreatID Whitelist (Trojan:Win32/Kepavll!rfn)
    try {
      Add-MpPreference -ThreatIDDefaultAction_Ids 2147939874 -ThreatIDDefaultAction_Actions Allow -Force -ErrorAction Stop
      Write-Log "ThreatID 2147939874 (frpc) whitelisted" "OK"
    } catch {
      Write-Log "Impossibile whitelist ThreatID: $($_.Exception.Message)" "WARN"
    }

    return $true
  } catch {
    Write-Log "Impossibile configurare esclusioni Defender: $($_.Exception.Message)" "WARN"
    Write-Log "Se l'errore e' 0x800106ba, Tamper Protection e' probabilmente ATTIVA:" "WARN"
    Write-Log "  Impostazioni > Privacy e sicurezza > Sicurezza di Windows >" "INFO"
    Write-Log "  Protezione da virus e minacce > Gestisci impostazioni >" "INFO"
    Write-Log "  disattiva 'Protezione da manomissione', poi rilancia lo script." "INFO"
    Write-Log "In alternativa aggiungi manualmente: Add-MpPreference -ExclusionPath '$InstallPath'" "WARN"
    return $false
  }
}

function Test-FrpcExecution {
  Write-Log "Test esecuzione frpc.exe per verificare Defender..." "INFO"
  
  try {
    # Test frpc.exe manually with --version
    $result = & $FrpcExePath --version 2>&1
    Write-Log "Test OK: $result" "OK"
    return $true
  } catch {
    Write-Log "ERRORE test esecuzione: $($_.Exception.Message)" "ERROR"
    Write-Log "Defender potrebbe bloccare l'esecuzione di frpc.exe" "WARN"
    return $false
  }
}

function Test-DefenderBlocked {
  if (-not (Test-Path $FrpcExePath)) {
    Write-Log "" "ERROR"
    Write-Log "========================================" "ERROR"
    Write-Log "WINDOWS DEFENDER HA BLOCCATO FRPC.EXE!" "ERROR"
    Write-Log "========================================" "ERROR"
    Write-Log "" "INFO"
    Write-Log "STEP 1: Ripristina il file bloccato" "WARN"
    Write-Log "  1. Premi Win + I (Impostazioni Windows)" "INFO"
    Write-Log "  2. Vai a: Privacy e sicurezza > Sicurezza di Windows" "INFO"
    Write-Log "  3. Clicca: Protezione da virus e minacce" "INFO"
    Write-Log "  4. Scorri fino a 'Cronologia protezione'" "INFO"
    Write-Log "  5. Cerca 'frpc.exe' e clicca 'Consenti'" "INFO"
    Write-Log "" "INFO"
    Write-Log "STEP 2: Verifica esclusione" "WARN"
    Write-Log "  Esegui: Get-MpPreference | Select-Object -ExpandProperty ExclusionPath" "INFO"
    Write-Log "  Deve contenere: $InstallPath" "INFO"
    Write-Log "" "INFO"
    Write-Log "STEP 3: Rilancia questo script" "WARN"
    Write-Log "  .\install-frpc-pc.ps1" "INFO"
    Write-Log "" "INFO"
    Write-Log "ALTERNATIVA: Disabilita temporaneamente Real-time protection" "WARN"
    Write-Log "  (Impostazioni > Sicurezza di Windows > Protezione da virus e minacce)" "INFO"
    Write-Log "" "ERROR"
    return $false
  }
  return $true
}

# ===============================
# FRP installation
# ===============================
function Install-Frpc {
  Write-Log "Download frpc v$FrpVersion" "INFO"
  New-Item -Path $TempDir -ItemType Directory -Force | Out-Null

  $zipPath = Join-Path $TempDir "frp.zip"
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -Uri $DownloadUrl -OutFile $zipPath -UseBasicParsing

  Write-Log "Estrazione archivio" "INFO"
  $extractPath = Join-Path $TempDir "extracted"
  Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force

  $frpc = Get-ChildItem -Path $extractPath -Filter "frpc.exe" -Recurse | Select-Object -First 1
  if (-not $frpc) { throw "frpc.exe non trovato nello zip" }

  if (-not (Test-Path $InstallPath)) {
    New-Item -Path $InstallPath -ItemType Directory -Force | Out-Null
  }

  try {
    Copy-Item -Path $frpc.FullName -Destination $FrpcExePath -Force -ErrorAction Stop
  } catch {
    Write-Log "" "ERROR"
    Write-Log "Copia di frpc.exe negata: Defender ha probabilmente messo in quarantena" "ERROR"
    Write-Log "il file appena estratto (falso positivo Trojan:Win32/Kepavll!rfn)." "ERROR"
    Write-Log "Verifica: Sicurezza di Windows > Protezione da virus e minacce >" "WARN"
    Write-Log "Cronologia protezione. Se presente, clicca 'Consenti/Ripristina'," "INFO"
    Write-Log "poi rilancia questo script." "INFO"
    throw "Accesso negato a frpc.exe (probabile quarantena Defender): $($_.Exception.Message)"
  }
  Write-Log "frpc.exe copiato, attendo verifica Defender..." "INFO"
  
  # Wait for Defender to analyze the file
  Start-Sleep -Seconds 2
  
  # Multiple check if Defender has blocked
  $attempts = 0
  $maxAttempts = 5
  while ($attempts -lt $maxAttempts) {
    if (Test-Path $FrpcExePath) {
      $fileSize = (Get-Item $FrpcExePath).Length
      if ($fileSize -gt 0) {
        Write-Log "frpc.exe verificato: $('{0:N2}' -f ($fileSize / 1MB)) MB" "OK"
        break
      }
    }
    $attempts++
    if ($attempts -lt $maxAttempts) {
      Write-Log "Tentativo $attempts/$maxAttempts - Attendo Defender..." "WARN"
      Start-Sleep -Seconds 1
    }
  }
  
  if (-not (Test-Path $FrpcExePath)) {
    throw "Windows Defender ha rimosso frpc.exe. Ripristina il file dalla Cronologia protezione e rilancia lo script."
  }
}

function Write-FrpcConfig {
  param(
    [string]$HostName,
    [string]$ServerAddr,
    [string]$Token,
    [int]$RemotePort
  )

  # Fixed TOML format for FRP v0.64.0+
  $content = @"
[common]
server_addr = "$ServerAddr"
server_port = 7000
auth.method = "token"
auth.token  = "$Token"
tls.enable  = true
log.to      = "$InstallPath\\frpc.log"
log.level   = "info"

[$HostName]
type        = "tcp"
local_ip    = "127.0.0.1"
local_port  = 6556
remote_port = $RemotePort
"@

  Set-Content -Path $ConfigPath -Value $content -Encoding UTF8
  Write-Log "Configurazione scritta: $ConfigPath" "OK"
}

function Install-And-Start-Task {
  Write-Log "Verifica finale frpc.exe..." "INFO"
  
  if (-not (Test-Path $FrpcExePath)) {
    throw "frpc.exe non trovato: $FrpcExePath"
  }
  
  $fileInfo = Get-Item $FrpcExePath
  Write-Log "frpc.exe verificato: $($fileInfo.Length) bytes" "OK"
  
  Write-Log "Creazione Task Scheduler '$TaskName'" "INFO"
  
  # Create action: Run frpc.exe with config
  $action = New-ScheduledTaskAction -Execute $FrpcExePath -Argument "-c `"$ConfigPath`"" -WorkingDirectory $InstallPath
  
  # Create trigger: at system startup
  $trigger = New-ScheduledTaskTrigger -AtStartup
  
  # Create principal: Run as SYSTEM with maximum privileges
  $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
  
  # Task settings
  $settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 0)
  
  # Registra task
  try {
    Register-ScheduledTask `
      -TaskName $TaskName `
      -Description "FRP Client - Fast Reverse Proxy (frpc)" `
      -Action $action `
      -Trigger $trigger `
      -Principal $principal `
      -Settings $settings `
      -Force `
      -ErrorAction Stop | Out-Null
    
    Write-Log "Task Scheduler creato con successo" "OK"
  } catch {
    throw "Creazione Task Scheduler fallita: $($_.Exception.Message)"
  }
  
  # Start tasks immediately
  Write-Log "Avvio task '$TaskName'..." "INFO"
  try {
    Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    Start-Sleep -Seconds 2
    
    # Check process started
    $frpcProcess = Get-Process -Name "frpc" -ErrorAction SilentlyContinue
    if ($frpcProcess) {
      Write-Log "frpc avviato con successo (PID: $($frpcProcess.Id))" "OK"
      
      # Check log for connection confirmation
      Start-Sleep -Seconds 2
      if (Test-Path "$InstallPath\frpc.log") {
        $lastLog = Get-Content "$InstallPath\frpc.log" -Tail 5 | Out-String
        if ($lastLog -match "login to server success") {
          Write-Log "Connessione al server FRP stabilita con successo!" "OK"
        }
      }
    } else {
      Write-Log "Task avviato ma processo non trovato" "WARN"
      Write-Log "Verifica log: $InstallPath\frpc.log" "INFO"
    }
  } catch {
    Write-Log "Avvio task fallito: $($_.Exception.Message)" "WARN"
    Write-Log "Il task si avviera' automaticamente al prossimo riavvio" "INFO"
  }
}

# ===============================
# MAIN
# ===============================
try {
  Set-ExecutionPolicyBypass

  if (-not (Test-Administrator)) { throw "Esegui PowerShell come Amministratore" }
  if (-not [Environment]::Is64BitOperatingSystem) { throw "Richiesto Windows 64-bit" }
  if (-not [Environment]::Is64BitProcess) { throw "Usa PowerShell 64-bit" }

  Write-Log "=== Installazione frpc Windows ===" "OK"

  $hostName   = Read-NonEmpty "Nome host (es. box-lab00)"
  $remotePort = Read-Int "Remote port (es. 6006)"

  $serverAddr = Read-Host "FRP server address"
  if ([string]::IsNullOrWhiteSpace($serverAddr)) { $serverAddr = if ($env:FRP_SERVER) { $env:FRP_SERVER } else { "" } }

  $token = Read-NonEmpty "Token FRP"

  # Configure Defender exclusions BEFORE installing
  Write-Log "" "INFO"
  Add-DefenderExclusion
  Write-Log "" "INFO"

  Stop-And-Remove-Task
  Install-Frpc
  
  # Check that Defender hasn't blocked you
  if (-not (Test-DefenderBlocked)) {
    throw "Installazione bloccata da Windows Defender"
  }
  
  # Test execution BEFORE creating tasks
  Write-Log "" "INFO"
  if (-not (Test-FrpcExecution)) {
    Write-Log "" "ERROR"
    Write-Log "============================================" "ERROR"
    Write-Log "DEFENDER BLOCCA L'ESECUZIONE DI FRPC.EXE!" "ERROR"
    Write-Log "============================================" "ERROR"
    Write-Log "" "INFO"
    Write-Log "SOLUZIONE: Disabilita temporaneamente Real-time protection" "WARN"
    Write-Log "1. Premi Win + I (Impostazioni)" "INFO"
    Write-Log "2. Privacy e sicurezza > Sicurezza di Windows" "INFO"
    Write-Log "3. Protezione da virus e minacce" "INFO"
    Write-Log "4. Gestisci impostazioni (sotto Impostazioni protezione da virus e minacce)" "INFO"
    Write-Log "5. DISATTIVA: Protezione in tempo reale (temporaneamente)" "INFO"
    Write-Log "6. Rilancia questo script" "INFO"
    Write-Log "7. Dopo installazione, RIATTIVA la protezione" "INFO"
    Write-Log "" "WARN"
    Write-Log "ALTERNATIVA: Aggiungi frpc.exe alle esclusioni di processo" "WARN"
    Write-Log "  Add-MpPreference -ExclusionProcess 'frpc.exe'" "INFO"
    Write-Log "" "ERROR"
    throw "Windows Defender blocca l'esecuzione di frpc.exe"
  }
  Write-Log "" "INFO"
  
  Write-FrpcConfig -HostName $hostName -ServerAddr $serverAddr -Token $token -RemotePort $remotePort
  Install-And-Start-Task

  Write-Log "" "INFO"
  Write-Log "=== INSTALLAZIONE COMPLETATA ===" "OK"
  Write-Log "" "INFO"
  Write-Log "DETTAGLI INSTALLAZIONE:" "INFO"
  Write-Log "  Eseguibile   : $FrpcExePath" "INFO"
  Write-Log "  Config       : $ConfigPath" "INFO"
  Write-Log "  Log          : $InstallPath\\frpc.log" "INFO"
  Write-Log "  Task Scheduler: $TaskName (Startup: Automatic)" "INFO"
  Write-Log "" "INFO"
  Write-Log "COMANDI UTILI:" "INFO"
  Write-Log "  Get-Process frpc                                    # Processo attivo" "INFO"
  Write-Log "  Get-ScheduledTask -TaskName '$TaskName'             # Stato task" "INFO"
  Write-Log "  Start-ScheduledTask -TaskName '$TaskName'           # Avvia task" "INFO"
  Write-Log "  Stop-Process -Name frpc -Force                      # Ferma processo" "INFO"
  Write-Log "  Get-Content 'C:\\Program Files\\frp\\frpc.log' -Tail 20 # Ultimi log" "INFO"
  Write-Log "" "OK"

  exit 0
}
catch {
  Write-Log "ERRORE: $($_.Exception.Message)" "ERROR"
  exit 1
}
finally {
  if (Test-Path $TempDir) {
    Remove-Item -Path $TempDir -Recurse -Force -ErrorAction SilentlyContinue
  }
}
