# CheckMK Agent + FRPC Interactive Installer for Windows
> **Category:** Operational

**Version:** 1.1 (2025-11-07)  
**Compatibility:** Windows 10, 11, Server 2019, Server 2022  
**Language:** PowerShell 5.0+

## Overview

Interactive installation script for CheckMK Agent and FRPC Client on Windows systems. The script handles:

- **CheckMK Agent** installation (plain TCP on port 6556)
- **FRPC Client** installation (tunnel client with TLS encryption)
- Service management and autostart configuration
- Complete uninstallation with cleanup

## Requirements

- **Windows 10 or later** / **Windows Server 2019 or later**
- **Administrator** privileges required
- **PowerShell 5.0** or higher
- **Internet connectivity** for package downloads
- **Minimum 500 MB** free disk space

## Installation

### 1. Download the Script

```powershell
# Clone the repository
git clone https://github.com/nethesis/checkmk-tools.git
cd checkmk-tools/script-tools
```

### 2. Run with Administrator Privileges

```powershell
# Method 1: Right-click PowerShell, select "Run as Administrator"
# Then run:
.\install-agent-interactive.ps1

# Method 2: From admin PowerShell console
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
.\install-agent-interactive.ps1
```

### 3. Follow the Interactive Prompts

The script will:
1. Display system information (OS, version, architecture)
2. Request confirmation to proceed
3. Install CheckMK Agent
4. Ask if FRPC should be installed
5. If yes, prompt for FRPC configuration parameters

## Configuration Parameters

### For FRPC Installation

When prompted, provide:

| Parameters | Description | Example |
|-----------|-------------|---------|
| **Hostname** | Display name for the tunnel | `ws-server-01` |
| **FRP Server** | Remote FRP server address | `<your-checkmk-server>` |
| **Remote Port** | Remote port tunnel | `20001` |
| **Auth Token** | Security token (optional) | `secret-token-string` |

### Example FRPC Configuration

```toml
[common]
server_addr = "<your-checkmk-server>"
server_port = 7000
auth.method = "token"
auth.token = "your-secret-token"
tls.enable = true
log.to = "C:\ProgramData\frp\logs\frpc.log"
log.level = "debug"

[ws-server-01]
type = "tcp"
local_ip = "127.0.0.1"
local_port = 6556
remote_port = 20001
```

## Installation Directories

### CheckMK Agent
- **Installation:** `C:\Program Files (x86)\checkmk\service\`
- **Config:** `C:\ProgramData\checkmk\`
- **Service Name:** `CheckMK Agent`
- **Port:** TCP 6556 (loopback)

### FRPC Client
- **Binary:** `C:\Program Files\frp\frpc.exe`
- **Config:** `C:\ProgramData\frp\frpc.toml`
- **Logs:** `C:\ProgramData\frp\logs\frpc.log`
- **Service Name:** `frpc`

## Usage Examples

### Standard Installation

```powershell
# Run script with administrator privileges
.\install-agent-interactive.ps1

# Follow prompts for CheckMK Agent and FRPC
```

### Uninstall FRPC Only

```powershell
.\install-agent-interactive.ps1 --uninstall-frpc
```

### Uninstall CheckMK Agent Only

```powershell
.\install-agent-interactive.ps1 --uninstall-agent
```

### Uninstall Everything

```powershell
.\install-agent-interactive.ps1 --uninstall
```

### ShowHelp

```powershell
.\install-agent-interactive.ps1 --help
```

## Post-Installation Verification

### Verify Services are Running

```powershell
# CheckMK Agent
Get-Service -Name 'CheckMK Agent' | Format-List

# FRPC (if installed)
Get-Service -Name 'frpc' | Format-List
```

### Test Connectivity

```powershell
# Test CheckMK Agent (localhost:6556)
Test-NetConnection -ComputerName 127.0.0.1 -Port 6556

# Verify CheckMK Agent version
C:\'Program Files (x86)'\checkmk\service\check_mk_agent.exe
```

### Check FRPC Logs

```powershell
# View last 50 lines of FRPC log
Get-Content 'C:\ProgramData\frp\logs\frpc.log' -Tail 50 -Wait

# Follow log in real-time
Get-Content 'C:\ProgramData\frp\logs\frpc.log' -Wait
```

## Troubleshooting

### PowerShell Execution Policy Error

```powershell
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope CurrentUser -Force
```

### Script Not Running as Administrator

- Right-click on PowerShell
- Select "Run as Administrator"
- Navigate to script directory
- Run: `.\install-agent-interactive.ps1`

### MSI Installation Fails

1. Check internet connectivity
2. Verify firewall allows downloads from <your-checkmk-server>
3. Check disk space (minimum 500 MB)
4. View MSI log:
   ```powershell
   Get-Content "$env:TEMP\CheckMK-Setup\checkmk-install.log" -Tail 50
   ```
### FRPC Service Won't Start

1. Check configuration file:
   ```powershell
   Get-Content 'C:\ProgramData\frp\frpc.toml'
   ```

2. Verify network connectivity to FRP server:
   ```powershell
   Test-NetConnection -ComputerName <your-checkmk-server> -Port 7000
   ```

3. Check FRPC logs for errors:
   ```powershell
   Get-Content 'C:\ProgramData\frp\logs\frpc.log' -Tail 100
   ```

## Service Management

### Restart CheckMK Agent

```powershell
Restart-Service -Name 'CheckMK Agent'
```

### Restart FRPC

```powershell
Restart-Service -Name 'frpc'
```

### Stop Services

```powershell
Stop-Service -Name 'CheckMK Agent'
Stop-Service -Name 'frpc'
```

### Start Services

```powershell
Start-Service -Name 'CheckMK Agent'
Start-Service -Name 'frpc'
```

### Disable Autostart

```powershell
Set-Service -Name 'CheckMK Agent' -StartupType Manual
Set-Service -Name 'frpc' -StartupType Manual
```

### Enable Autostart

```powershell
Set-Service -Name 'CheckMK Agent' -StartupType Automatic
Set-Service -Name 'frpc' -StartupType Automatic
```

## Log Files

### CheckMK Agent

- **Windows Events:** Event Viewer → Windows Logs → Application (Filter by "CheckMK")

### FRPC

- **Log Location:** `C:\ProgramData\frp\logs\frpc.log`
- **View in PowerShell:**
  ```powershell
  Get-Content 'C:\ProgramData\frp\logs\frpc.log' -Tail 50
  ```

## Advanced Configuration

### Custom FRPC Configuration

Edit the configuration file directly:

```powershell
# Open FRPC config
notepad 'C:\ProgramData\frp\frpc.toml'

# Restart service to apply changes
Restart-Service -Name 'frpc'
```

### Multiple Tunnels

Add additional tunnel sections to `frpc.toml`:

```toml
[rdp-tunnel]
type = "tcp"
local_ip = "127.0.0.1"
local_port = 3389
remote_port = 20002

[ssh-tunnel]
type = "tcp"
local_ip = "127.0.0.1"
local_port = 22
remote_port = 20022
```

Then restart: `Restart-Service -Name 'frpc'`

## Security Considerations

1. **Change Auth Token:** Replace default token with strong, unique value
2. **Enable TLS:** Already enabled (`tls.enable = true`)
3. **Limit Port Access:** Windows Firewall configured automatically
4. **Log Rotation:** Consider implementing log rotation for `/logs/` directory
5. **Regular Updates:** Check for CheckMK and FRPC updates regularly

## Uninstallation

### RemoveEverything

```powershell
.\install-agent-interactive.ps1 --uninstall
```

Or manually:

```powershell
# Remove services
sc.exe delete frpc
sc.exe delete "CheckMK Agent"

# Remove directories
Remove-Item -Path 'C:\Program Files\frp' -Recurse -Force
Remove-Item -Path 'C:\Program Files (x86)\checkmk' -Recurse -Force
Remove-Item -Path 'C:\ProgramData\frp' -Recurse -Force
Remove-Item -Path 'C:\ProgramData\checkmk' -Recurse -Force
```

## Comparison with Linux/OpenWrt Installer

| Features | Windows | Linux/OpenWrt |
|---------|---------|---------------|
| **Installation Method** | MSI | Package from source |
| **Service Manager** | Windows Services (sc.exe) | systemd / init.d |
| **Config Location** | `C:\ProgramData\*` | `/etc/checkmk/` |
| **FRPC Config Format** | TOML (.toml) | TOML (.toml) |
| **Package Manager** | Manual download | apt/opkg |

## Version History

### Version 1.1 (2025-11-07)
- Complete syntax rewrite - all PowerShell errors fixed
- Removed emoji characters for better encoding compatibility
- Simplified mathematical expressions for robustness
- Improved error handling and logging
- Full feature parity with bash version

### Version 1.0 (Initial)
- Basic Windows installer
- CheckMK Agent installation
- FRPC configuration

## Support and Issues

For bug reports and feature requests:
- **GitHub Issues:** https://github.com/nethesis/checkmk-tools/issues
- **Author:** Nethesis
## License

MIT License - See LICENSE file for details

## Related Scripts

- **Linux/OpenWrt Installer:** `install-agent-interactive.sh`
- **Backup/Sync:** `backup-sync-complete.ps1`
- **Configuration Tools:** `script-tools/` directory

---

**Last Updated:** 2025-11-07  
**Status:** Production Ready - Fully Tested