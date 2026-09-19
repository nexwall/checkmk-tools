# Install CheckMK Agent + FRPC on QNAP NAS
> **Category:** Operational

## Description

Script for automatically installing CheckMK Agent and FRPC on QNAP NAS systems.

## Requirements

- QNAP NAS with QTS 4.x/5.x or QuTS hero
- SSH access active
- Root or admin user
- At least 100MB of disk space

## Installation

### 1. Upload the script to your NAS

```bash
# Via SCP
scp install-agent-frpc-qnap.sh admin@IP_QNAP:/tmp/

# Or download directly to the NAS
ssh admin@IP_QNAP
cd /tmp
wget https://raw.githubusercontent.com/nethesis/checkmk-tools/main/script-tools/install-agent-frpc-qnap.sh
chmod +x install-agent-frpc-qnap.sh
```

### 2. Run the installation

```bash
sudo ./install-agent-frpc-qnap.sh
```

## Options

```bash
# Interactive installation (default)
./install-agent-frpc-qnap.sh

# Uninstall FRPC only
./install-agent-frpc-qnap.sh --uninstall-frpc

# Uninstall Agent only
./install-agent-frpc-qnap.sh --uninstall-agent

# Uninstall everything
./install-agent-frpc-qnap.sh --uninstall

# Help
./install-agent-frpc-qnap.sh --help
```

## Dependency management

### If `socat` is not available

The script will attempt to automatically install `socat`. If that fails, you have three options:

#### Option 1: Install Entware (recommended)

1. Open **App Center** on QNAP
2. Search and install **Entware**
3. After installing Entware:
   ```bash
   opkg update
   opkg install socat
   ```
4. Rerun the installation script

#### Option 2: Download socat manually

```bash
# For QNAP x86_64
cd /tmp
wget http://bin.entware.net/x86-64/other/socat
chmod +x socat
mv socat /usr/local/bin/
```

#### Option 3: Use xinetd (alternative)

The script will automatically ask if you want to use xinetd instead of socat:
```
Want to try using xinetd instead of socat? [y/N]: yes
```

## Installation structure

```
/opt/checkmk/
├── bin/
│ └── check_mk_agent # CheckMK agent
├── log/
│ └── agent.log # Agent log
├── start_agent.sh # Startup script
└── stop_agent.sh # Stop script

/opt/frpc/
├── bin/
│ └── frpc # FRPC client
├── conf/
│ └── frpc.toml # Configuration
├── log/
│ ├── frpc.log # FRPC log
│ └── startup.log # Startup log
├── start_frpc.sh # Startup script
└── stop_frpc.sh # Stop script

/etc/config/autorun.sh # Autostart QNAP
```

## Useful commands

### CheckMK Agent

```bash
# Start agent
/opt/checkmk/start_agent.sh

# Stop agent
/opt/checkmk/stop_agent.sh

# Manual testing
/usr/bin/check_mk_agent

# Check port
nc localhost 6556

# Agent logs
tail -f /opt/checkmk/log/agent.log
```

### FRPC Client

```bash
# Start FRPC
/opt/frpc/start_frpc.sh

# Stop FRPC
/opt/frpc/stop_frpc.sh

# Check process
ps aux | grep frpc

# FRPC logs
tail -f /opt/frpc/log/frpc.log

# Edit configuration
vi /opt/frpc/conf/frpc.toml
```

## Troubleshooting

### Agent not responding

```bash
# Check process
ps aux | grep -E "socat|xinetd"

# Check port
netstat -tlnp | grep 6556

# Manual restart
/opt/checkmk/stop_agent.sh
/opt/checkmk/start_agent.sh

# Local test
echo "exit" | nc localhost 6556
```

### FRPC does not connect

```bash
# Check log
tail -50 /opt/frpc/log/frpc.log

# Check configuration
cat /opt/frpc/conf/frpc.toml

# Test server connection
nc -zv SERVER_IP 7000

# Restart
/opt/frpc/stop_frpc.sh
/opt/frpc/start_frpc.sh
```

### Autostart does not work

```bash
# Check autorun.sh
cat /etc/config/autorun.sh

# Check permissions
ls -la /etc/config/autorun.sh
chmod +x /etc/config/autorun.sh

# Manual autorun test
/etc/config/autorun.sh
```

## Notes

- Services start automatically on boot via `/etc/config/autorun.sh`
- Backup of `autorun.sh` is created automatically before changes
- CheckMK agent listens on TCP port **6556**
- FRPC connects to the FRP server specified during installation
- Logs are kept for 7 days (FRPC) or unlimited (Agent)

## Support

In case of problems:

1. Check the logs in `/opt/checkmk/log/` and `/opt/frpc/log/`
2. Check that the ports are not blocked by QNAP firewall
3. Check the configuration in `/opt/frpc/conf/frpc.toml`
4. Consult the official CheckMK and FRP documentation

## License

Script developed for internal use - Freely editable