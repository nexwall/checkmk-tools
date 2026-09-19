# CheckMK Tools Collection

[![License](https://img.shields.io/badge/license-GPL--2.0-blue.svg)](LICENSE)
[![CheckMK](https://img.shields.io/badge/CheckMK-Compatible-green.svg)](https://checkmk.com/)
[![Python](https://img.shields.io/badge/Python-3.6+-blue.svg)](https://www.python.org/)

Complete collection of scripts for monitoring and managing infrastructures with CheckMK. Includes local check scripts for multiple platforms, custom notification systems, deployment tools, cloud backup, and Ydea ticketing integration.

---

## Index

- [Repository Structure](#repository-structure)
- [Check Scripts](#check-scripts)
  - [NethServer 7](#nethserver-7)
  - [NethServer 8](#nethserver-8)
  - [NethSecurity 8](#nethsecurity-8)
  - [Ubuntu/Linux](#ubuntulinux)
  - [Proxmox](#proxmox)
  - [tmate Server](#tmate-server)
  - [Windows](#windows)
  - [CheckMK Server-Side Checks](#checkmk-server-side-checks)
- [Notification Scripts](#notification-scripts)
- [Deployment Tools](#deployment-tools)
- [Ydea Toolkit](#ydea-toolkit)
- [Nethesis Branding](#nethesis-branding)
- [Installation](#installation)
- [Contributing](#contributing)
- [License](#license)

---

## Main Features

### Multi-Platform

- **Windows**: PowerShell scripts for Windows Server (AD, IIS, Ransomware Detection)
- **Linux**: Python scripts for NethServer, NethSecurity, Ubuntu, Proxmox
- **Container**: Podman/Docker monitoring on NethServer 8

### ROCKSOLID Mode - Upgrade Resistant Agent

- **NethSecurity 8**: CheckMK + FRP agent installation resistant to major upgrades
- **Auto-Recovery**: Startup script that restores services automatically
- **Binary Backup**: Protect `tar`, `ar`, `gzip` from corruption
- **FRP Dual-Format**: Support FRP v0.x and v1.x with auto detection
- **Dynamic packages**: Download from OpenWrt upstream repositories at runtime

### Automated Deployment

- **Smart Deploy**: Hybrid system for multi-host deployment
- **Interactive Menu**: Interactive deployment with script selection for OS
- **Agent Installer**: Unified agent installation script for multiple platforms

### Nethesis Branding for CheckMK

- **CSS override**: Logo, colors and CSS for CheckMK Facelift theme
- **Multi-server**: Deploy to all servers with a single script
- **Static assets**: SVG files in `nethesis-brand/`

### Automated Cloud Backup

- **rclone Integration**: Backup CheckMK to cloud storage (S3, DigitalOcean Spaces, etc.)
- **Intelligent Retention**: Automatic local and remote retention management
- **Monitoring Timer**: Systemd timer for periodic backup checks

### Advanced Notifications

- **Email Real IP**: Notifications with real IP even behind FRP proxy
- **Telegram Integration**: Telegram notifications with scenario detection
- **Ydea Ticketing**: Automatic ticket creation from CheckMK events

---

## Repository Structure

```text
checkmk-tools/
├── script-check-ns7/           # NethServer 7 check scripts
│   ├── full/                   # Python check scripts
│   └── doc/
├── script-check-ns8/           # NethServer 8 check scripts
│   ├── full/                   # Python check scripts
│   └── doc/
├── script-check-nsec8/         # NethSecurity 8 check scripts
│   ├── full/                   # Production Python check scripts
│   ├── tests/                  # pytest suite + staged/WIP checks
│   └── doc/
├── script-check-ubuntu/        # Ubuntu/Linux check scripts
│   ├── full/                   # Python check scripts
│   └── doc/
├── script-check-proxmox/       # Proxmox VE check scripts
│   ├── full/                   # Python check scripts
│   └── doc/
├── script-check-tmate-server/  # tmate server check scripts
│   └── full/
├── script-check-windows/       # Windows check scripts (PowerShell)
│   ├── full/
│   └── doc/
├── script-checkmk/             # CheckMK server-side check scripts
│   └── full/                   # Host connectivity, VPN tunnel checks
├── script-notify-checkmk/      # CheckMK notification scripts
│   ├── full/                   # Email, Telegram, Ydea, ticket watchers
│   ├── beta/                   # M@il-20 / Telegram-20 rate-limited notifiers
│   ├── reporting/              # Alarm/notification reporting & recurrence analysis
│   └── doc/
├── script-tools/                    # Deployment and management tools
│   ├── full/
│   │   ├── agent_maintenance/       # CheckMK agent sync (multi-OS)
│   │   ├── audit_ns8/               # NS8 audit reports
│   │   ├── backup_restore/          # Backup, restore, rclone cloud sync
│   │   ├── clients/                 # Client-side setup scripts (SMTP, etc.)
│   │   ├── deploy/                  # Agent and check-script deployment
│   │   ├── installation/            # Agent/FRPC/tmate installers
│   │   ├── monitoring_diagnostics/  # Tuning, diagnostics, flapping analysis
│   │   ├── network_scan/            # nmap-based network scanning
│   │   ├── sync_update/             # Auto-git-sync, script/crontab updates
│   │   ├── systemd/                 # Systemd unit templates (backup jobs)
│   │   ├── upgrade_maintenance/     # CheckMK/agent upgrade automation
│   │   ├── vulnerability_management/ # GVM/OpenVAS -> CISO Assistant import
│   │   └── wrappers_templates/      # Wrapper/template examples
│   └── doc/
├── Ydea-Toolkit/                # Ydea ticketing integration & API toolkit
│   ├── full/                    # Integration + exploration/test scripts
│   ├── config/                  # Configuration files
│   └── doc/
├── nethesis-brand/              # CheckMK Nethesis branding assets
│   ├── theme.css
│   └── *.svg
├── script-ps-tools/             # PowerShell backup/maintenance tools (Windows)
├── copilot/                     # Internal AI-agent automation scripts (ops use)
├── docs/                        # Release notes (PENDING_RELEASE.md)
└── deploy-nethesis-brand.sh     # Deploy branding on CheckMK servers
```

---

## Check Scripts

All check scripts follow the CheckMK local check output format:

```text
<STATE> <SERVICE_NAME> - <message>
```

States: `0`=OK, `1`=WARNING, `2`=CRITICAL, `3`=UNKNOWN.

Scripts are deployed to `/usr/lib/check_mk_agent/local/` on the monitored host, **without the `.py` extension**.

### NethServer 7

**Directory**: `script-check-ns7/full/`

Complete monitoring for NethServer 7 (CentOS 7 based).

| Script | Description |
| -------- | ----------- |
| `check_cockpit_sessions.py` | Active Cockpit sessions |
| `check_dovecot_sessions.py` | IMAP/POP3 active sessions |
| `check_dovecot_maxuserconn.py` | Max connections per user |
| `check_dovecot_status.py` | Dovecot service status |
| `check_dovecot_vsz.py` | Dovecot memory usage (VSZ) |
| `check_postfix_status.py` | Postfix service status |
| `check_postfix_process.py` | Active Postfix processes |
| `check_postfix_queue.py` | Email queue length |
| `check_webtop_status.py` | Webtop5 service status |
| `check_webtop_maxmemory.py` | Webtop memory allocation |
| `check_webtop_https.py` | Webtop HTTPS / certificate expiry |
| `check_ssh_root_logins.py` | SSH root login attempts |
| `check_ssh_root_sessions.py` | Active root SSH sessions |
| `check_ssh_all_sessions.py` | All SSH sessions |
| `check-ssh-failures.py` | SSH failed attempts |
| `check_fail2ban_status.py` | Fail2ban service status |
| `check_ransomware_ns7.py` | Ransomware detection |
| `check-sos-ns7.py` | SOS report generation |
| `check-sosid-ns7.py` | SOS report case ID tracking |
| `check-pkg-install.py` | Installed package count |

---

### NethServer 8

**Directory**: `script-check-ns8/full/`

Monitoring for NethServer 8 (Podman/Container based).

| Script | Description |
| -------- | ----------- |
| `check_ns8_containers.py` | Container status overview |
| `check_ns8_container_status.py` | Individual container status |
| `check_ns8_container_health.py` | Container health checks |
| `check_ns8_container_resources.py` | Container CPU/memory usage |
| `check_ns8_container_inventory.py` | Container inventory |
| `check_ns8_services.py` | NS8 service status |
| `check_ns8_webtop.py` | Webtop service monitoring |
| `check_ns8_tomcat8.py` | Tomcat8 status |
| `check_ns8_smoke_test.py` | Smoke test for NS8 modules |
| `check_nv8_status_trunk.py` | NethVoice trunk status |
| `check_nv8_status_extensions.py` | NethVoice extensions status |
| `check-sos.py` | SOS report generation |
| `acl-viewer.py` | ACL permissions viewer |
| `monitor_podman_events.py` | Real-time Podman event monitor |

---

### NethSecurity 8

**Directory**: `script-check-nsec8/full/`

Monitoring for NethSecurity 8 (OpenWrt-based firewall).

| Script | Description |
| -------- | ----------- |
| `check_wan_status.py` | WAN interface status |
| `check_wan_throughput.py` | WAN bandwidth utilization |
| `check_vpn_tunnels.py` | VPN tunnel status |
| `check_ovpn_host2net.py` | OpenVPN host-to-net connections |
| `check_firewall_rules.py` | Firewall rule count and status |
| `check_firewall_connections.py` | Active firewall connections |
| `check_firewall_traffic.py` | Firewall traffic statistics |
| `check_dhcp_leases.py` | DHCP lease usage |
| `check_dns_resolution.py` | DNS resolution check |
| `check_root_access.py` | Root access attempts |

---

### Ubuntu/Linux

**Directory**: `script-check-ubuntu/full/`

Generic check scripts for Ubuntu/Debian distributions.

| Script | Description |
| -------- | ----------- |
| `check_disk_space.py` | Disk space usage |
| `check_fail2ban_status.py` | Fail2ban status and ban count |
| `check_ssh_root_logins.py` | SSH root login attempts |
| `check_ssh_root_sessions.py` | Active root SSH sessions |
| `check_ssh_all_sessions.py` | All SSH sessions |
| `check_arp_watch.py` | ARP watch / MAC address changes |
| `check_tmate_session.py` | tmate session status |
| `check_efivars.py` | EFI variables check |
| `check_notification_by_script.py` | Notification activity grouped by script (Ydea, mail, Telegram, etc.) |
| `check_notification_limiter_status.py` | M@il-20 / Telegram-20 delivery and rate-limiter status |

---

### Proxmox

**Directory**: `script-check-proxmox/full/`

Proxmox Virtual Environment monitoring via API.

| Script | Description |
| -------- | ----------- |
| `check-proxmox-vm-status.py` | VM running/stopped status |
| `check-proxmox_qemu_status.py` | QEMU VM status |
| `check-proxmox_qemu_runtime.py` | QEMU VM runtime |
| `check-proxmox_qemu_guest_agent_status.py` | QEMU Guest Agent status |
| `check-proxmox_lxc_status.py` | LXC container status |
| `check-proxmox_lxc_runtime.py` | LXC container runtime |
| `check-proxmox_storage_status.py` | Storage pool status |
| `check-proxmox_backup_status.py` | Backup job status |
| `check-proxmox_services_status.py` | Proxmox service status |
| `check-proxmox_vm_monitor.py` | General VM monitor (CPU, RAM, Disk) |

**Requirements**: Proxmox API token with read permissions, `curl`, `jq`.

---

### tmate Server

**Directory**: `script-check-tmate-server/full/`

| Script | Description |
| -------- | ----------- |
| `check_tmate_server.py` | tmate-ssh-server connectivity and status |

---

### Windows

**Directory**: `script-check-windows/`

PowerShell scripts for Windows Server monitoring including ransomware detection on network shares.

**Features**:

- Multi-pattern detection (suspicious extensions, known ransomware patterns, I/O speed)
- Canary file monitoring
- Timeout protection for slow/blocked shares
- Detailed metrics per share

**Quick Start**:

```powershell
# Deploy on Windows Server
Copy-Item check_ransomware_activity.ps1, ransomware_config.json `
    -Destination "C:\ProgramData\checkmk\agent\local\"

# Manual test
.\check_ransomware_activity.ps1 -VerboseLog
```

**Documentation**: [script-check-windows/README.md](script-check-windows/README.md)

---

### CheckMK Server-Side Checks

**Directory**: `script-checkmk/full/`

Checks that run on the CheckMK server itself rather than on the monitored host.

| Script | Description |
| -------- | ----------- |
| `check_host_connectivity.py` | ARP (same-subnet) + ICMP fallback (cross-VLAN) host reachability, replaces `check_icmp` behind active firewalls |
| `check_host_connectivity_nmap.py` | Host connectivity via nmap only (auto ARP/ICMP selection) |
| `check_host_connectivity_us.py` | Host connectivity variant for multi-VLAN setups where the monitoring server can't reach hosts directly |
| `check_vpn_tunnels.py` | OpenVPN net-to-net tunnel status via remote-subnet gateway ping |

---

## Notification Scripts

**Directory**: `script-notify-checkmk/full/`

Custom CheckMK notification scripts with real IP detection (for hosts behind FRP proxy), HTML email with graphs, and Telegram integration.

### Real IP Detection

Extracts the real client IP even when hosts are behind an FRP proxy:

```python
if 'NOTIFY_HOSTLABEL_real_ip' in os.environ:
    real_ip = os.environ['NOTIFY_HOSTLABEL_real_ip']
```

### Email

| Script | Description |
| -------- | ----------- |
| `mail_realip` | Email with real IP extraction (FRP-aware) |
| `mail-checkmk` | Standard CheckMK email notification wrapper |

### Telegram

| Script | Description |
| -------- | ----------- |
| `telegram_realip` | Telegram notification with real IP |
| `telegram_selfmon` | Telegram self-monitoring alert |
| `telegram_c01` | Telegram channel C01 |
| `telegram_c01_selfmon` | Telegram C01 self-monitoring |
| `telegram_cl00` | Telegram CL00 notifications |
| `telegram_tmate.py` | Telegram tmate session notifications |
| `telegram_get_chatid.py` | Utility to retrieve a Telegram chat ID |

### Ydea Integration

| Script | Description |
| -------- | ----------- |
| `ydea_la` | Ydea LA ticketing notification |
| `ydea_ag` | Ydea AG ticketing notification |
| `ydea_ag_testing` / `ydea_la_testing` | Testing variants of the Ydea notifications |
| `ydea_cache_validator.py` | Ticket cache validator |
| `notify_ticket_watcher.py` | Monitor open notification tickets |
| `notify_ticket_watcher_sp.py` | Ticket watcher variant (SP site) |
| `notify_copilot_autofix.py` | Trigger AI-agent autofix workflow from a notification event |

### Rate-Limited Notifiers (beta)

**Directory**: `script-notify-checkmk/beta/`

| Script | Description |
| -------- | ----------- |
| `M@il-20` | Email notifier with adaptive cooldown / rate limiting |
| `Telegram-20` | Telegram notifier with adaptive cooldown / rate limiting |

Monitored on the target host via `check_notification_limiter_status.py` (see [Ubuntu/Linux](#ubuntulinux)).

### Reporting

**Directory**: `script-notify-checkmk/reporting/`

| Script | Description |
| -------- | ----------- |
| `daily_alarm_report.py` | Daily summary report of CheckMK alarms |
| `notification-limiter-report.py` | Read-only recurrence/time-of-day insights for rate-limited notifications |
| `analyze_notification_recurrence.py` | Recurring alert pattern analysis module |

### Deployment

```bash
# On CheckMK server (as site user)
cp mail_realip /omd/sites/SITENAME/local/share/check_mk/notifications/
chmod +x /omd/sites/SITENAME/local/share/check_mk/notifications/mail_realip

# Configure in Web GUI:
# Setup -> Notifications -> New Rule -> Notification Method: mail_realip
```

**Documentation**: [script-notify-checkmk/TESTING_GUIDE.md](script-notify-checkmk/TESTING_GUIDE.md)

---

## Deployment Tools

**Directory**: `script-tools/full/`

Python tools for CheckMK agent deployment, infrastructure management, backup, and tuning, organized by function into subfolders (no loose scripts in the folder root — see `script-tools/full/README.md`).

### Agent Installation & Sync

| Script | Description |
| -------- | ----------- |
| `installation/install-agent-nsec8.py` | ROCKSOLID CheckMK+FRP agent installer for NethSecurity 8 |
| `installation/setup-persistent-nsec8.py` | Upgrade-resistant persistence setup for NethSecurity 8 |
| `installation/install_frpc.py` | FRP client installation |
| `agent_maintenance/checkmk-agent-autoupdate-linux.py` | Multi-OS agent sync (Debian/RHEL/NethSecurity/NS8), verify-only by default, structured status reporting |
| `agent_maintenance/checkmk-agent-sync.service` / `.timer` | Optional systemd units for scheduled agent sync (daily, randomized delay) |
| `deploy/deploy-plain-agent.py` | Deploy agent to a single host |
| `deploy/deploy-plain-agent-multi.py` | Multi-host deployment from list |

#### NethSecurity 8 - Official Installation Procedure

```bash
wget https://updates.nethsecurity.nethserver.org/checkmk_agent/8.7.2-checkmk_agent+a4de81a27/packages/x86_64/nethsecurity/ns-checkmk-utils_0.0.2-r1_all.ipk
wget https://nethsecurity.ams3.digitaloceanspaces.com/checkmk_agent/8.7.2-checkmk_agent+a4de81a27/packages/x86_64/nethsecurity/checkmk-agent_2.4.0p24-r1_all.ipk
opkg install checkmk-agent_2.4.0p24-r1_all.ipk
opkg install ns-checkmk-utils_0.0.2-r1_all.ipk
```

**Validated on**: NethSecurity 8.7.2 (OpenWrt), CheckMK Agent 2.4.0p24.

### tmate Integration

| Script | Description |
| -------- | ----------- |
| `installation/install-tmate-server.py` | Install and configure tmate-ssh-server |
| `installation/install-tmate-client.py` | Install and configure tmate client |
| `installation/setup-tmate-token-push.py` | Configure token push to server |
| `installation/tmate-receive-token.py` | Receive and store tmate tokens (forced command) |

### Backup and Recovery

| Script | Description |
| -------- | ----------- |
| `backup_restore/checkmk_rclone_space_dyn.py` | Cloud backup with rclone (S3/Spaces) |
| `backup_restore/checkmk_backup.py` | Local CheckMK backup |
| `backup_restore/checkmk_restore.py` | CheckMK restore |
| `backup_restore/checkmk_restore_dr.py` | Disaster recovery restore workflow |
| `backup_restore/checkmk_manage_job00_daily.py` / `checkmk_manage_job01_weekly.py` | Scheduled backup job managers |
| `backup_restore/cleanup-checkmk-retention.py` | Backup retention cleanup |
| `systemd/checkmk-backup-job00.service` / `checkmk-backup-job01.service` | Systemd units for scheduled backup jobs |

### CheckMK Tuning, Upgrade & Diagnostics

| Script | Description |
| -------- | ----------- |
| `monitoring_diagnostics/checkmk-tuning-interactive-v5.py` | Interactive CheckMK tuning wizard |
| `upgrade_maintenance/checkmk_optimize.py` | Automated CheckMK optimization |
| `upgrade_maintenance/upgrade-checkmk.py` | Automated CheckMK upgrade |
| `upgrade_maintenance/setup-auto-upgrade-checkmk.py` | Setup auto-upgrade via crontab |
| `upgrade_maintenance/pre-upgrade-nsec8.py` | Pre-upgrade checks for NethSecurity 8 |
| `monitoring_diagnostics/flapping_analyzer.py` | Detect flapping services/hosts |
| `monitoring_diagnostics/fix_stale_checkmk.py` | Recover stale/hung CheckMK checks |
| `monitoring_diagnostics/check_hostgroup_service_status.py` | Service status summary by host group |
| `monitoring_diagnostics/distributed-monitoring-setup.py` | Distributed monitoring site setup |

### NS8 Audit Reports

| Script | Description |
| -------- | ----------- |
| `audit_ns8/ns8-audit-report-unified.py` | Unified NS8 audit report |
| `audit_ns8/ns8-biweekly-audit-report.py` | Biweekly NS8 audit report |

### Network Scan

| Script | Description |
| -------- | ----------- |
| `network_scan/scan_nmap.py` | nmap-based network scan |
| `network_scan/network_scan_to_folder.py` | Scan and export results to folder |
| `network_scan/scan-nmap-interattivo-verbose-multi-options.py` | Interactive multi-option nmap scan |

### Vulnerability Management

| Script | Description |
| -------- | ----------- |
| `vulnerability_management/gvm_to_ciso_import.py` | Import GVM/OpenVAS (by task name, read-only GMP lookup) or nmap scan results into CISO Assistant via REST API - interactive wizard or CLI |
| `vulnerability_management/default_creds_check.py` | Active default/weak-credential and misconfiguration probe (SSH, FTP, SMB, mail, HTTP admin panels, VNC, Redis, MongoDB, SNMP, CheckMK agent) - imports findings into CISO Assistant, supports save-and-import-later via --from-log |

### Monitoring Script Deployment

| Script | Description |
| -------- | ----------- |
| `deploy/deploy-monitoring-scripts.py` | OS-aware interactive script deployment |
| `deploy/smart-deploy-hybrid.py` | Multi-host deployment with cache |
| `deploy/deploy_monitoring.py` | Batch monitoring deployment |
| `deploy/auto-deploy-checks.py` | Automated check-script deployment |

### Repository Sync

The repository is automatically synchronized on CheckMK servers using a Python-managed, systemd timer-based model:

```bash
# Install auto-sync (systemd timer-based, with fallback to cron on systems without systemd)
python3 installation/install-checkmk-agent-linux.py --git-interval 30
```

**Active Model:**
- **Architecture:** Python orchestration (`sync_update/auto_git_sync.py`) with minimal Bash runtime wrapper
- **Systemd Mode:** Timer (`auto-git-sync.timer`) + oneshot service (`auto-git-sync.service`)
- **Sync Logic:** `git fetch origin main` → `git reset --hard origin/main` → `git clean -fd`
- **Cron Fallback:** On systems without systemd (OpenWrt, NethSecurity 8), sync runs every minute via cron
- **Log:** `/var/log/auto-git-sync.log`

**Important:** `/opt/checkmk-tools/` is a read-only deploy clone managed by auto-sync. Never edit files directly in `/opt/checkmk-tools/` — all changes will be overwritten on the next sync cycle. Real editing must occur in your editable source workspace, then committed and pushed to the repository. The auto-sync timer will automatically pull updates.

---

## Ydea Toolkit

**Directory**: `Ydea-Toolkit/`

Integration between CheckMK and the Ydea helpdesk system for automatic ticket creation from monitoring events, plus a broad set of Ydea REST API exploration/test scripts (each with both a `.py` implementation and a `.sh` wrapper) used to reverse-engineer SLA, contract, and ticket endpoints.

**Structure**:

- `full/` — Integration scripts + API exploration/test scripts
- `config/` — Configuration files (`credentials.sh.template`, `premium-mon-config.json`)
- `doc/` — Documentation (including `README-CHECKMK-INTEGRATION.md`)

### Features

- Automatic ticket creation from CheckMK PROBLEM/RECOVERY events
- SLA discovery from customer contracts
- Ticket deduplication and state tracking
- Health monitor for integration status
- Correlator to link CheckMK notifications back to existing Ydea tickets

### Key Scripts

| Script | Description |
| -------- | ----------- |
| `ydea_monitoring_integration.py` | Core CheckMK-Ydea integration |
| `install_ydea_checkmk_integration.py` | Automated installation |
| `ydea_health_monitor.py` | Integration health monitoring |
| `ydea_ticket_monitor.py` | Open ticket monitor |
| `ydea_discover_sla_ids.py` | Automatic SLA discovery from contracts |
| `ydea_notify_correlator.py` | Correlate CheckMK notifications with existing tickets |
| `ydea_common.py` | Shared API client/helpers |
| `ydea_templates.py` | Ticket message templates |
| `ydea-toolkit.py` | Ydea API master toolkit |

The remaining `explore_*`, `search_*`, `get_*`, `test_*`, and `analyze_*` scripts (with matching `.sh` wrappers) are ad-hoc tools for exploring the Ydea API surface (anagrafica, SLA, tickets, contracts) — see `Ydea-Toolkit/doc/` for details.

### Configuration

```bash
# Required: .env file with credentials
YDEA_ID="your_company_id"
YDEA_API_KEY="YOUR_API_KEY_HERE"
YDEA_CONTRATTO_ID="your_contract_id"
```

### Quick Start

```bash
# 1. Installation
cd Ydea-Toolkit/full
python3 install_ydea_checkmk_integration.py

# 2. Configure credentials
cp .env.example .env
vim .env

# 3. Automatic SLA discovery
python3 ydea_discover_sla_ids.py

# 4. Monitor health
python3 ydea_health_monitor.py
```

**Documentation**: [Ydea-Toolkit/doc/README.md](Ydea-Toolkit/doc/README.md)

---

## Nethesis Branding

**Directory**: `nethesis-brand/`

CSS and SVG assets to apply Nethesis visual identity to the CheckMK web interface (Facelift theme).

**Files**:

- `theme.css` — CSS overrides for colors and fonts
- `checkmk_logo.svg` — Login page logo (290px)
- `icon_checkmk_logo.svg` — Sidebar icon (40px)
- `icon_checkmk_logo_min.svg` — Sidebar icon (28px)

**Deploy**:

```bash
./deploy-nethesis-brand.sh
```

---

## Installation

### Requirements

**Linux (all platforms)**:

- Python 3.6+
- CheckMK Agent installed
- `curl` (for some tools)

**Windows**:

- PowerShell 5.1+
- CheckMK Agent for Windows

### Deploy a Check Script

```bash
# Clone the repository
git clone https://github.com/Coverup20/checkmk-tools.git /opt/checkmk-tools

# Copy the desired script to the local checks directory (no extension)
cp /opt/checkmk-tools/script-check-ns7/full/check_dovecot_status.py \
   /usr/lib/check_mk_agent/local/check_dovecot_status
chmod +x /usr/lib/check_mk_agent/local/check_dovecot_status

# Verify output
/usr/lib/check_mk_agent/local/check_dovecot_status
```

Scripts are deployed **without the `.py` extension** so CheckMK executes them directly.

### Auto-Sync Setup

To keep scripts automatically updated on a server:

```bash
python3 /opt/checkmk-tools/script-tools/full/installation/install-checkmk-agent-linux.py --git-interval 60
```

### Notification Script Installation

```bash
# On CheckMK server (as root)
git clone https://github.com/Coverup20/checkmk-tools.git /tmp/checkmk-tools
cp /tmp/checkmk-tools/script-notify-checkmk/full/mail_realip \
   /omd/sites/SITENAME/local/share/check_mk/notifications/
chmod +x /omd/sites/SITENAME/local/share/check_mk/notifications/mail_realip
```

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/check-name`
3. Write the script following the Python style below
4. Commit: `git commit -m 'feat(platform): add check_name v1.0.0'`
5. Open a Pull Request

### Python Style

All scripts follow the Nethesis Python style (reference: `NethServer/nethsecurity`):

```python
#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Check <service> status

import subprocess

SERVICE = "ServiceName"

## Utils

def run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 1, "", str(e)

## Check

def check():
    rc, out, err = run(["systemctl", "is-active", "myservice"])
    if rc != 0:
        print(f"2 {SERVICE} - CRITICAL: service not running")
        return
    print(f"0 {SERVICE} - OK: running")

check()
```

**Rules**:

- No classes, no `if __name__ == "__main__"` — call the function directly at module level
- No type hints, no docstrings on obvious functions
- `subprocess.run` with `capture_output=True, text=True` — never `shell=True`
- CheckMK output format: `<STATE> <SERVICE> - <message>`
- Script version in `VERSION = "x.y.z"` variable at module level

### Naming Convention

- Check scripts: `check_<name>.py`
- Deployed name (no extension): `check_<name>`
- CheckMK service name: `ServiceName` (matches the `SERVICE` constant)

---

## Auto-Sync System

The repository uses an automatic synchronization system on CheckMK servers:

```text
Local Editable Workspace
    ↓ [git commit & push]
GitHub (Coverup20/checkmk-tools)
    ↓ [auto-git-sync timer - configurable interval, default 30s]
/opt/checkmk-tools/ (read-only deploy clone on servers)
    ↓ [execute scripts from synchronized repo]
Production
```

**Sync Model:**
- **Timer:** `auto-git-sync.timer` runs on a configurable schedule (default 30 seconds)
- **Service:** `auto-git-sync.service` (Type=oneshot) is triggered by the timer
- **Runtime:** Minimal Bash wrapper (`/usr/local/bin/checkmk-git-sync.sh`) generated during installation
- **Behavior:** Fetch origin/main, reset hard, clean working directory
- **Logging:** All sync operations logged to `/var/log/auto-git-sync.log`

### Check Sync Status

```bash
# Timer status
systemctl status auto-git-sync.timer

# Service status
systemctl status auto-git-sync.service

# View recent logs
journalctl -u auto-git-sync.service -f
tail -f /var/log/auto-git-sync.log

# List scheduled timer runs
systemctl list-timers auto-git-sync.timer
```

### Manual Sync (Force Immediate Pull)

```bash
# Trigger sync immediately (do NOT edit /opt/checkmk-tools directly)
systemctl start auto-git-sync.service
```

---

## CheckMK Cloud Backup

Complete script for automated CheckMK backup to cloud storage via rclone.

**File**: `script-tools/full/backup_restore/checkmk_rclone_space_dyn.py`

**Features**:

- Multi-cloud: S3, DigitalOcean Spaces, Google Drive, etc.
- Automatic local and remote retention management
- Systemd timer for periodic backup checks
- S3-compatible API (no mkdir required)

**Quick Start**:

```bash
cd /opt/checkmk-tools/script-tools/full/backup_restore
python3 checkmk_rclone_space_dyn.py setup
```

---

## Security

- Do not commit credentials in config files — use environment variables
- Limit file permissions: `600` for sensitive configs (`.env`, key files)
- Use HTTPS for API communications
- Set timeouts for all network operations

---

## License

GPL-2.0-only — see [LICENSE](LICENSE) for details.

---

## Platform Coverage

| Platform | Check Scripts | Description |
| ---------- | -------------- | ----------- |
| NethServer 7 | 20 | CentOS 7 based server |
| NethServer 8 | 14 | Container/Podman based server |
| NethSecurity 8 | 10 | OpenWrt-based firewall |
| Ubuntu/Linux | 10 | Generic Debian/Ubuntu |
| Proxmox VE | 10 | Virtualization platform |
| tmate Server | 1 | SSH session sharing |
| CheckMK Server-Side | 4 | Host connectivity, VPN tunnels (run on the CheckMK server) |
| Windows | - | PowerShell scripts |
