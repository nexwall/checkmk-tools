# NethSecurity 8 - CheckMK Agent Installation

> **Category:** Operational

## MANDATORY PROCEDURE

**ONLY these 4 commands must be used:**

```bash
wget https://updates.nethsecurity.nethserver.org/checkmk_agent/8.7.2-checkmk_agent+a4de81a27/packages/x86_64/nethsecurity/ns-checkmk-utils_0.0.2-r1_all.ipk
wget https://nethsecurity.ams3.digitaloceanspaces.com/checkmk_agent/8.7.2-checkmk_agent+a4de81a27/packages/x86_64/nethsecurity/checkmk-agent_2.4.0p24-r1_all.ipk
opkg install checkmk-agent_2.4.0p24-r1_all.ipk
opkg install ns-checkmk-utils_0.0.2-r1_all.ipk
```

**DO NOT use** `install-checkmk-agent-persistent-nsec8.sh` or any other custom script.
These create unwanted artifacts and break the system after upgrades.

## What gets installed

- `checkmk-agent`: `/usr/sbin/check_mk_agent` + `/etc/init.d/check_mk_agent`
- `ns-checkmk-utils`: 13 local checks in `/usr/lib/check_mk_agent/local/`

## FRPC

Install separately. See FRPC documentation.
```

### Uninstall

```bash
bash install-checkmk-agent-debtools-frp-nsec8c-rocksolid.sh --uninstall
```

---

## Environment Variables

| Variable | Default | Description |
|-----------|---------|-------------|
| `CMK_SERVER` | `<your-checkmk-server>` | Hostname CheckMK server |
| `CMK_SITE` | `monitoring` | Site Name CheckMK |
| `CMK_PROTOCOL` | `https` | Protocol (http/https) |
| `DEB_URL` | (auto-detect) | Direct URL to the .deb agent |
| `FRP_VER` | `0.64.0` | FRP Client Version |
| `FRPC_BIN` | `/usr/local/bin/frpc` | FRP Binary Path |
| `FRPC_CONF` | `/etc/frp/frpc.toml` | Path config FRP |
| `NON_INTERACTIVE` | `0` | Non-interactive mode (1=disable prompts) |

---

## Installation workflow

### Step 1: CheckMK Agent

1. **Installation prerequisites**
   - Adds OpenWrt repositories (base, packages)
   - Install: `ca-bundle`, `ca-certificates`, `wget-ssl`, `socat`, `netcat`, `coreutils-realpath`
   - Install dpkg binaries: `tar`, `ar`, `gzip`

2. **Critical binary backups**
   - Save `tar`, `ar`, `gzip` to `/opt/checkmk-tools/BACKUP-BINARIES/`
   - Required for post-upgrade reinstallation

3. **Download and install agent**
   - Automatically detect CheckMK version from server
   - Download correct `.deb` for architecture
   - Extract and install with `dpkg`
   - Copy agent to `/usr/bin/check_mk_agent`

4. **Service configuration**
   - Create init script procd in `/etc/init.d/check_mk_agent`
   - Configure `socat` for TCP-LISTEN:6556
   - Enable and start service
   - Check connectivity with `nc 127.0.0.1 6556`

5. **ROCKSOLID protection**
   - Add files to `/etc/sysupgrade.conf`:
     ```
     /opt/checkmk-tools/BACKUP-BINARIES/tar
     /opt/checkmk-tools/BACKUP-BINARIES/ar
     /opt/checkmk-tools/BACKUP-BINARIES/gzip
     /etc/checkmk-post-upgrade.sh
     ```

### Phase 2: FRP Client (Optional)

**NOTE**: FRP is completely **OPTIONAL**. If you don't need reverse proxy tunnels:
- Answer **NO** to the "Do you want to configure FRP?" prompt.
- The script will complete the installation with CheckMK Agent only
- No `/opt/checkmk-tools/.frp-installed` markers will be created
- Autocheck will never attempt to start FRP
- Fully functional system without FRP

1. **Interactive configuration**
   - Prompt to enable FRP
   - If **NO**: skip the entire FRP phase
   - If **YES**: requires authentication token, remote port, proxy name

2. **Binary Download**
   - Download `frp_${FRP_VER}_linux_amd64.tar.gz`
   - Extract to `/usr/local/bin/frpc`
   - Set execution permissions

3. **Configuration generation**
   - Create `/etc/frp/frpc.toml` with tokens
   - Config format v0.x (`[common]` section)
   - TCP proxy configuration:
     ```toml
[common]
     serverAddr = "SERVER"
     serverPort = 7000
     auth.method = "token"
     auth.token = "TOKEN"
     
     [[proxies]]
     name = "PROXY_NAME"
     type = "tcp"
     localIP = "127.0.0.1"
     localPort = 6556
     remotePort = REMOTE_PORT
     ```

4. **Init script procd**
   - Create `/etc/init.d/frpc`
   - Enable autostart
   - Start service
   - Check active process

5. **ROCKSOLID protection**
   - Adds to sysupgrade.conf:
     ```
     /usr/local/bin/frpc
     /etc/frp/frpc.toml
     /etc/init.d/frpc
     /opt/checkmk-tools/.frp-installed
     ```
   - Create marker file `/opt/checkmk-tools/.frp-installed`

### Step 3: Autocheck Boot

1. **Autocheck script**
   - DO NOT copy local file (it would be corrupted)
   - Configure `/etc/rc.local` to run from GitHub:
     ```bash
   curl -fsSL https://raw.githubusercontent.com/nethesis/checkmk-tools/main/script-tools/full/upgrade_maintenance/rocksolid-startup-check.sh | bash
     ```

2. **rc.local protection**
   - Add `/etc/rc.local` to sysupgrade.conf
   - Guarantees autocheck execution at every boot

---

## Post-Upgrade: Auto-Recovery

After a major upgrade, the system automatically performs:

### 1. Boot and rc.local

```
System restarts
    |
    v
/etc/rc.local executed
    |
    v
curl download rocksolid-startup-check.sh from GitHub
    |
    v
Autocheck script executed
```

### 2. Autocheck Workflow

```
Check CheckMK Agent (port 6556)
    |
    +-- If active: OK
    |
    +-- If NOT active:
        |
        +-- Restore tar/ar/gzip from backup
        +-- Reinstall agent from .deb
        +-- Configure socat
        +-- Start service
        
Verify FRP markers (.frp-installed)
    |
    +-- If NOT exists: Skip FRP
    |
    +-- If exists:
        |
        +-- Verify frpc binary
        +-- Check frpc.toml config
        +-- Check frpc process
        +-- If NOT active: /etc/init.d/frpc restart

Custom repository cleanup
    |
    +-- Check /etc/opkg/customfeeds.conf
    +-- If it contains unauthorized OpenWrt repos:
        |
        +-- Create backup .backup
        +-- Empty file (header only)
        +-- Prevents future conflicts
```

### 3. Result

- **Recovery time**: 20-30 seconds from boot
- **CheckMK Agent**: Operational
- **FRP Client**: Operational (if configured)
- **Repository**: Clean (no conflicts)
- **Log**: `/var/log/rocksolid-startup.log`

---

## Protected Files in sysupgrade.conf

The script automatically adds these files to survive major upgrades:

### CheckMK Agent
```
/opt/checkmk-tools/BACKUP-BINARIES/tar
/opt/checkmk-tools/BACKUP-BINARIES/ar
/opt/checkmk-tools/BACKUP-BINARIES/gzip
/opt/checkmk-tools/BACKUP-BINARIES/check-mk-agent.deb
/etc/checkmk-post-upgrade.sh
```

### FRP Client
```
/usr/local/bin/frpc
/etc/frp/frpc.toml
/etc/init.d/frpc
/opt/checkmk-tools/.frp-installed
```

### System
```
/etc/rc.local
```

---

## Log and Check

### Check Installation

```bash
# CheckMK Agent
nc 127.0.0.1 6556 | head
pgrep -fa "socat.*6556"

# FRP Client (if configured)
pgrep -does frpc
cat /etc/frp/frpc.toml

# Active protections
grep -E "check_mk|frpc" /etc/sysupgrade.conf

# FRP markers
ls -lh /opt/checkmk-tools/.frp-installed
```

### Log Autocheck

```bash
# Log complete
cat /var/log/rocksolid-startup.log

# Last 30 lines
tail -30 /var/log/rocksolid-startup.log

# Only errors
grep -i "error\|fail\|warn" /var/log/rocksolid-startup.log
```

### Test CheckMK Agent

```bash
# Local test
echo "<<<check_mk>>>" | nc 127.0.0.1 6556 -w 3

# Test from CheckMK server
ssh monitoring@checkmk-server "cmk-agent-ctl dump"
```

---

## Troubleshooting

### CheckMK Agent is not responding

```bash
# Check process
pgrep -do socat

# If not active, restart
/etc/init.d/check_mk_agent restart

# Check connectivity
nc 127.0.0.1 6556

# Error log
logread | grep -i checkmk
```

### FRP Client does not connect

```bash
# Check process
pgrep -does frpc

# If not active, restart
/etc/init.d/frpc restart

# FRP logs
tail -50 /var/log/frpc.log

# Server connectivity test
nc -zv FRPC_SERVER 7000

# Check config
cat /etc/frp/frpc.toml
```

### Post-upgrade services do not restart

```bash
# Run autocheck manually
curl -fsSL https://raw.githubusercontent.com/nethesis/checkmk-tools/main/script-tools/full/upgrade_maintenance/rocksolid-startup-check.sh | bash

# Check log
tail -50 /var/log/rocksolid-startup.log

# Run manual post-upgrade script
bash /etc/checkmk-post-upgrade.sh
# Verify surviving protected files
ls -lh /opt/checkmk-tools/BACKUP-BINARIES/
ls -lh /usr/local/bin/frpc
ls -lh /etc/frp/frpc.toml
```

### Corrupt binaries after upgrade

```bash
# Verify binary backups
ls -lh /opt/checkmk-tools/BACKUP-BINARIES/

# Restore manually
cp /opt/checkmk-tools/BACKUP-BINARIES/tar /bin/tar
cp /opt/checkmk-tools/BACKUP-BINARIES/ar /usr/bin/ar
cp /opt/checkmk-tools/BACKUP-BINARIES/gzip /bin/gzip
chmod +x /bin/tar /usr/bin/ar /bin/gzip

# Reinstall agent
bash /etc/checkmk-post-upgrade.sh
```

---

## Useful Commands

### Services Management

```bash
# CheckMK Agent
/etc/init.d/check_mk_agent start|stop|restart|status

# FRP Client
/etc/init.d/frpc start|stop|restart|status

# Check processes
ps | grep -E "socat|frpc"
```

### Manual Backup

```bash
# Complete configuration backup
tar -czf /tmp/checkmk-backup.tar.gz \
  /opt/checkmk-tools/BACKUP-BINARIES/ \
  /usr/local/bin/frpc \
  /etc/frp/frpc.toml \
  /etc/init.d/frpc \
  /etc/init.d/check_mk_agent \
  /etc/rc.local \
  /etc/sysupgrade.conf

# Copy backup to remote server
scp /tmp/checkmk-backup.tar.gz user@server:/backup/
```

### Test Major Upgrade

```bash
#1. Pre-upgrade: Check status
echo "=== PRE-UPGRADE ===" > /tmp/pre-upgrade.log
pgrep -fa "socat|frpc" >> /tmp/pre-upgrade.log
grep -c checkmk /etc/sysupgrade.conf >> /tmp/pre-upgrade.log

# 2. Perform major upgrade via web interface

#3. Post-upgrade: Check status
sleep 60 # Wait for complete boot
echo "=== POST-UPGRADE ===" > /tmp/post-upgrade.log
pgrep -fa "socat|frpc" >> /tmp/post-upgrade.log
tail -30 /var/log/rocksolid-startup.log >> /tmp/post-upgrade.log

#4. Compare
cat /tmp/pre-upgrade.log /tmp/post-upgrade.log
```

---

## FAQ

### Q: Does the script work on architectures other than x86_64?
**A**: Currently only supports x86_64. For ARM/MIPS edit `REPO_BASE` and `REPO_PACKAGES`.

### Q: Can I use CheckMK server other than <your-checkmk-server>?
**A**: Yes, set `export CMK_SERVER="your-server.com"` before running.

### Q: Is FRP mandatory?
**A**: No, it's completely optional. During installation you will be asked if you want to configure FRP. If you answer NO:
- Only CheckMK Agent (port 6556) will be installed
- No FRP markers created
- Autocheck works normally (only checks CheckMK Agent)
- Fully operational system without tunnels
- You can always install FRP later by re-running the script

### Q: What happens if I disable FRP after installation?
**A**: Remove marker: `rm /opt/checkmk-tools/.frp-installed`. Autocheck will no longer attempt to restart it.

### Q: Can I reinstall without uninstalling?
**A**: Yes, the script detects existing installations and updates the files.

### Q: How do I update the FRP version?
**A**: Edit `FRP_VER` and rerun the script, or manually download and replace `/usr/local/bin/frpc`.

### Q: Are custom repositories removed on every boot?
**A**: No, only if they contain OpenWrt repos. Official NethSecurity repositories are not touched.

### Q: Can I run autocheck manually?
**A**: Yes: `curl -fsSL https://raw.githubusercontent.com/.../rocksolid-startup-check.sh | bash`

---

## Security

### FRP Token Protection

The FRP token is stored in `/etc/frp/frpc.toml` which is:
- Protected in sysupgrade.conf (survives upgrade)
- Readable only by root (chmod 600 recommended)
- Never exposed in log or output

### Curl from GitHub

Autocheck script run via curl from GitHub:
- Use HTTPS (TLS encryption)
- Checked repository (github.com/nethesis/checkmk-tools)
- No local execution (no corrupt files)

Considerations:
- Requires trust in the GitHub repository
- Alternative: Private fork and change URL to rc.local

---

## Technical Architecture

### Why dpkg on OpenWrt?

CheckMK provides agents as a `.deb` package (Debian). OpenWrt uses `opkg` (not compatible with .deb). Solution:

1. Install essential dpkg binaries: `tar`, `ar`, `gzip`
2. Use custom script to extract .deb
3. Install content manually
4. Bypass dependency resolution of dpkg

### Why socat instead of xinetd?

- OpenWrt does not include xinetd
- `socat` is lighter and more flexible
- Easier configuration via procedure
- No additional dependencies

### Why FRP instead of SSH tunnel?

- Lighter FRP than OpenSSH server
- Simplified configuration (one TOML file)
- Multiplex support (multiple tunnels on one connection)
- Automatic reconnect
- Does not require SSH accounts on the firewall

---

## References
- **CheckMK**: https://checkmk.com/
- **FRP**: https://github.com/fatedier/frp
- **OpenWrt**: https://openwrt.org/
- **NethSecurity**: https://www.nethsecurity.org/
- **Repository**: https://github.com/nethesis/checkmk-tools

---

## License

Script part of the checkmk-tools project.
Internal use Nethesis / laboratory.

---

## Changelog

### v2.0 - ROCKSOLID Edition (2026-01-29)
- Added file protection in sysupgrade.conf
- Automatic backup of critical binaries
- Post-upgrade auto-recovery
- Autocheck run by GitHub (curl-based)
- Automatic cleanup of conflicting repositories
- Explicit FRP config file protection (frpc.toml)
- Marker-based FRP detection

### v1.0 - Initial Release
- Basic CheckMK Agent installation
- Support FRP tunnel
- Procd/socat configuration