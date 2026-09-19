# Install Agent Interactive - User Guide
> **Category:** Operational

Interactive script for automated installation/uninstallation of CheckMK Agent with FRPC client option.

## Features

- **Installation Wizard** CheckMK Agent (plain TCP 6556)
- **Multi-distro support**: Ubuntu, Debian, Rocky Linux, CentOS, RHEL, AlmaLinux, NethServer Enterprise, **OpenWrt/NethSec8**
- **Optional FRPC installation** with interactive configuration
- **Full Uninstall** with separate options for Agent and FRPC
- **Automatic detection** of the operating system
- **systemd/init.d** configuration complete
- **Colorful output** and user-friendly

## What the script does

### Part 1: CheckMK Agent (always installed)
1. Automatically detect your operating system
2. Download the correct CheckMK Agent package (DEB or RPM)
3. Install the agent
4. Disable TLS and standard configuration
5. Create plain systemd socket on port 6556
6. Launch and test the agent

### Part 2: FRPC Client (optional)
1. Asks if you want to install FRPC
2. Download and install FRPC v0.64.0
3. Interactive configuration with request for:
   - **Hostname** (default: current hostname)
   - **Remote FRP server** (default: <your-checkmk-server>)
   - **Remote port** (mandatory, e.g.: 20001)
   - **Security token** (default: conduit-reenact-talon-macarena-demotion-vaguely)
4. Generate `/etc/frp/frpc.toml` file with the configuration
5. Create systemd service for FRPC
6. Start and test the tunnel

## Requirements

- Supported operating system: 
  - **Debian-based**: Ubuntu, Debian
  - **RHEL-based**: Rocky Linux, CentOS, RHEL, AlmaLinux
  - **NethServer**: NethServer Enterprise (automatically detected)
  - **OpenWrt**: OpenWrt 23.05+, NethServer 8 Core (NethSec8)
- Root or sudo access
- Internet connection
- CheckMK Server reachable (for package downloads)

### Note on NethServer Enterprise
NethServer Enterprise is **automatically detected** via the `/etc/nethserver-release` file. The script will automatically use the appropriate RPM packages for installation.

### Note on OpenWrt/NethSec8
OpenWrt and NethServer 8 Core are discovered via `/etc/openwrt_release`. The script:
- Use **opkg** as package manager
- Manually extract the DEB package
- Configure **socat** as a listener on port 6556
- Create **init.d** service with procd (not systemd)
- Supports FRPC with dedicated init.d service

## Usage

### Installation

#### Method 1: Direct execution
```bash
sudo bash install-agent-interactive.sh
```

#### Method 2: With execute permissions
```bash
chmod +x install-agent-interactive.sh
sudo ./install-agent-interactive.sh
```

### Uninstall

#### Remove FRPC Client only
```bash
sudo ./install-agent-interactive.sh --uninstall-frpc
```

#### Remove CheckMK Agent only
```bash
sudo ./install-agent-interactive.sh --uninstall-agent
```

#### Remove All (Agent + FRPC)
```bash
sudo ./install-agent-interactive.sh --uninstall
```

#### Show help
```bash
./install-agent-interactive.sh --help
```

### Options available

| Option | Description |
|---------|-------------|
| _(none)_ | Complete interactive installation |
| `--uninstall-frpc` | Uninstall FRPC client only |
| `--uninstall-agent` | Uninstall CheckMK Agent | only
| `--uninstall` | Uninstall everything (with confirmation) |
| `--help` or `-h` | Show help message |

## Example of Interactive Session

```
╔══════════════════════════════ ══════════════════════════════╗
║ Interactive Installation CheckMK Agent + FRPC ║
║ Version: 1.0 - 2025-11-06 ║
╚══════════════════════════════ ══════════════════════════════╝

 System detected: Ubuntu 22.04 (deb)

═══ CHECKMK AGENT INSTALLATION ═══
 Download agent from: https://<your-checkmk-server>/monitoring/...
 Package installation...
 CheckMK Agent installed

═══ PLAIN AGENT CONFIGURATION ═══
 Disable TLS and standard sockets...
 I create systemd unit for plain agent...
 Reloading systemd and starting socket...
 Plain agent configured on port 6556

 Local test agent:
<<<check_mk>>>
Version: 2.4.0p12
Hostname: myserver
AgentOS: linux

════════════════════ ════════════════════
Do you want to install FRPC too? [y/N]: yes
════════════════════ ════════════════════

═══ FRPC CLIENT INSTALLATION ═══
 Download FRPC v0.64.0...
 Extraction...
 FRPC installed in /usr/local/bin/frpc

═══ FRPC CONFIGURATION ═══
Enter information for FRPC configuration:
Hostname [default: myserver]: 
Remote FRP server [default: <your-checkmk-server>]: 
Remote port [ex: 20001]: 20001
Security token [default: conduit-reenact-talon-macarena-demotion-vaguely]: 

 Creating file /etc/frp/frpc.toml...
 Configuration file created

 FRPC Configuration:
   Server: <your-checkmk-server>:7000
   Tunnel: myserver
   Remote port: 20001
   Local port: 6556

 Creating systemd service...
 FRPC started successfully

╔══════════════════════════════ ══════════════════════════════╗
║ INSTALLATION COMPLETE ║
╚══════════════════════════════ ══════════════════════════════╝

 SUMMARY:
    CheckMK Agent installed (plain TCP 6556)
    Active systemd socket: check-mk-agent-plain.socket
    FRPC Client installed and configured
    Active tunnel: <your-checkmk-server>:20001 → localhost:6556

 USEFUL COMMANDS:
   Local test agent: /usr/bin/check_mk_agent
   Status socket: systemctl status check-mk-agent-plain.socket
   Status FRPC: systemctl status frpc
   FRPC log: journalctl -u frpc -f
   FRPC Config: /etc/frp/frpc.toml

 Installation completed successfully!
```

## FRPC Configuration Generated

The `/etc/frp/frpc.toml` file is automatically created with this structure:

```toml
# FRPC Client configuration
# Generated on 2025-11-06

[common]
server_addr = "<your-checkmk-server>"
server_port = 7000
auth.method = "token"
auth.token = "conduit-reenact-talon-macarena-demotion-vaguely"
tls.enable = true
log.to = "/var/log/frpc.log"
log.level = "debug"

[myserver]
type = "tcp"
local_ip = "127.0.0.1"
local_port = 6556
remote_port = 20001
```

**Format Notes:**
- `[common]` section with global parameters
- `[hostname]` section for each tunnel
- Log level `debug` for complete troubleshooting
- Log saved in `/var/log/frpc.log`

## Post-Installation Verification

### CheckMK Agent
```bash
# Local test of the agent
/usr/bin/check_mk_agent

# Check systemd socket
systemctl status check-mk-agent-plain.socket

# Remote testing (from CheckMK server)
telnet <HOST_IP> 6556
```

### FRPC (if installed)
```bash
# Service status
systemctl status frpc

# View real-time logs
journalctl -u frpc -f

# Check configuration file
cat /etc/frp/frpc.toml

# Restarting service
systemctl restart frpc
```

## Services Management

### Restarting Agent
```bash
systemctl restart check-mk-agent-plain.socket
```

### Restarting FRPC
```bash
systemctl restart frpc
```

### Edit FRPC configuration
```bash
# Edit the file
nano /etc/frp/frpc.toml

# Reboot to apply changes
systemctl restart frpc
```

## Examples Uninstallation

### Uninstall FRPC only (keep Agent)
```bash
sudo ./install-agent-interactive.sh --uninstall-frpc
```
**Output:**
```
╔══════════════════════════════ ══════════════════════════════╗
║ UNINSTALLING FRPC CLIENT ║
╚══════════════════════════════ ══════════════════════════════╝

  FRPC removal in progress...

  FRPC service stop...
  Disable FRPC service...
  Removing systemd files...
  Removal executable...
  Removing configuration directory...
  Removing log files...

 Uninstalled FRPC completely
 Files removed:
   • /usr/local/bin/frpc
   • /etc/frp/
   • /etc/systemd/system/frpc.service
   • /var/log/frpc.log
```

### Uninstall Agent only (keep FRPC)
```bash
sudo ./install-agent-interactive.sh --uninstall-agent
```
**Removes:**
- Check-mk-agent package
- Socket systemd plain
- Directory /etc/check_mk
- Plugin agents

### Uninstall everything
```bash
sudo ./install-agent-interactive.sh --uninstall
```
**Prompts for confirmation** before proceeding with complete removal of Agent and FRPC.

## Configuration File

| Files | Description |
|------|-------------|
| `/etc/systemd/system/check-mk-agent-plain.socket` | Socket systemd agent plain |
| `/etc/systemd/system/check-mk-agent-plain@.service` | Service systemd agent plain |
| `/etc/frp/frpc.toml` | Client FRPC Configuration |
| `/etc/systemd/system/frpc.service` | Service systemd FRPC |
| `/var/log/frpc.log` | FRPC client log |

## Important Notes

1. **Port 6556**: The CheckMK agent listens on this port (plain TCP, no TLS)
2. **Firewall**: Make sure port 6556 is open if you log in remotely directly
3. **FRPC Tunnel**: If you use FRPC, traffic goes through the secure tunnel
4. **FRPC Token**: Default token is shared, use custom token in production
5. **Updates**: The script installs CheckMK Agent v2.4.0p12 and FRPC v0.64.0

## Troubleshooting

### Agent not responding
```bash
# Check active socket
systemctl status check-mk-agent-plain.socket

# Restart socket
systemctl restart check-mk-agent-plain.socket

# Local test
/usr/bin/check_mk_agent
```

### FRPC does not connect
```bash
# Check log
journalctl -u frpc -n 50

# Test connection to server
telnet <your-checkmk-server> 7000

# Check configuration
cat /etc/frp/frpc.toml

# Restart service
systemctl restart frpc
```

### Port already in use
```bash
# Check who uses port 6556
ss -tulpn | grep 6556

# Stop any conflicting service
systemctl stop check-mk-agent.socket
systemctl disable check-mk-agent.socket
```

## Useful Links

- [CheckMK Agent Documentation](https://docs.checkmk.com/latest/en/agent_linux.html)
- [FRP GitHub Repository](https://github.com/fatedier/frp)
- [FRP Documentation](https://gofrp.org/en/)

## Author

Script created to simplify the deployment of CheckMK Agent with FRPC support.

## License

Free to use for CheckMK monitoring purposes.

---

**Version**: 1.2  
**Date**: 2025-11-07  
**Compatibility**: Ubuntu, Debian, Rocky Linux, CentOS, RHEL, AlmaLinux, NethServer Enterprise, OpenWrt 23.05+, NethSec8