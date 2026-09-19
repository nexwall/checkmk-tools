# CheckMK Tools - Complete Index

**Complete repository index for CheckMK monitoring, deployment, and management scripts.**

- **Repository**: [github.com/nethesis/checkmk-tools](https://github.com/nethesis/checkmk-tools)
- **Type**: Multi-platform monitoring toolkit
- **License**: GPL-2.0
- **Language**: Python, Bash, PowerShell
- **Scripts**: 424 files across the repository

---

## Quick Navigation

- [Overview](#overview)
- [Directory Structure](#directory-structure)
- [Script Categories](#script-categories)
  - [NethServer 7 Checks](#script-check-ns7-nethserver-7-checks)
  - [NethServer 8 Checks](#script-check-ns8-nethserver-8-checks)
  - [NethSecurity 8 Checks](#script-check-nsec8-nethsecurity-8-checks)
  - [Ubuntu/Linux Checks](#script-check-ubuntu-ubuntulinux-checks)
  - [Proxmox VE Checks](#script-check-proxmox-proxmox-ve-checks)
  - [tmate Server Checks](#script-check-tmate-server-tmate-server-checks)
  - [CheckMK Server Checks](#script-checkmk-checkmk-server-checks)
  - [Notification Integration](#script-notify-checkmk-notification-integration)
  - [Ydea Ticketing Integration](#ydea-toolkit-ydea-ticketing-integration)
  - [PowerShell Utilities](#script-ps-tools-powershell-utilities)
  - [script-tools/ - Core Deployment & Management Tools](#script-tools---core-deployment--management-tools)
- [Deployment Methods](#deployment-methods)
- [Installation Guide](#installation-guide)
- [Testing & Validation](#testing--validation)
- [Key Features](#key-features)
- [Troubleshooting](#troubleshooting)
- [Quick Reference](#quick-reference)

---

## Overview

**CheckMK Tools** is a comprehensive collection of scripts for managing CheckMK monitoring infrastructure across multiple platforms:

- ✅ **Multi-Platform**: Windows, Linux (NethServer 7/8, Ubuntu, Proxmox), NethSecurity 8
- ✅ **Automated Deployment**: Smart deployment for multi-host environments
- ✅ **Local Checks**: Custom monitoring scripts for infrastructure health
- ✅ **Notifications**: Integration with Ydea ticketing and email/Telegram systems
- ✅ **Backup & Recovery**: Cloud and local backup management
- ✅ **Upgrade-Resistant**: Persistent installation utilities for NethSecurity 8

---

## Directory Structure

```
checkmk-tools/
├── script-check-ns7/              # NethServer 7 monitoring scripts
├── script-check-ns8/              # NethServer 8 monitoring scripts
├── script-check-nsec8/            # NethSecurity 8 monitoring scripts
├── script-check-ubuntu/           # Ubuntu/Linux monitoring scripts
├── script-check-proxmox/          # Proxmox VE monitoring scripts
├── script-check-tmate-server/     # tmate Server monitoring scripts
├── script-check-windows/          # Windows Server monitoring docs
├── script-checkmk/                # CheckMK server-side scripts
├── script-tools/                  # Core deployment and management tools
│   └── full/                      # Organized in subdirectories (backup, deploy, install, etc.)
├── script-notify-checkmk/         # CheckMK notification integration
├── Ydea-Toolkit/                  # Ydea ticketing integration
├── script-ps-tools/               # PowerShell utilities
├── README.md                      # Main documentation
├── REPOSITORY_INDEX.md            # Repository structure reference
├── CONTEXTS_INDEX.md              # Available contexts
├── INDEX.md                       # Complete index
└── LICENSE                        # GPL-2.0 license
```

---

## Script Categories

### script-check-ns7/ - NethServer 7 Checks

Local check scripts for NethServer 7 monitoring (CentOS 7 based).

**Key Scripts:**
- `[check-pkg-install.py](file:///root/checkmk-tools/script-check-ns7/full/check-pkg-install.py)` - CheckMK Local Check for YUM package installations Monitor recent YUM activity (Installed/Updated/Erased/Removed). Che...
- `[check-sos-ns7.py](file:///root/checkmk-tools/script-check-ns7/full/check-sos-ns7.py)` - CheckMK Local Check for SOS session status Check SOS session status (WindMill VPN + SSH) on NethServer 7. Monitor sys...
- `[check-sosid-ns7.py](file:///root/checkmk-tools/script-check-ns7/full/check-sosid-ns7.py)` - CheckMK Local Check for SOS session ID Show SOS session ID if active on NethServer 7. Check systemd services and quer...
- `[check-ssh-failures.py](file:///root/checkmk-tools/script-check-ns7/full/check-ssh-failures.py)` - CheckMK Local Check for SSH banned IPs Count currently banned IPs by fail2ban SSH jail. NethServer 7.9 Version: 1.0.0
- `[check_cockpit_sessions.py](file:///root/checkmk-tools/script-check-ns7/full/check_cockpit_sessions.py)` - CheckMK Local Check for Cockpit session events Monitor Cockpit login/logout events from /var/log/messages and report ...
- `[check_dovecot_maxuserconn.py](file:///root/checkmk-tools/script-check-ns7/full/check_dovecot_maxuserconn.py)` - CheckMK Local Check for Dovecot max user connections Extract mail_max_userip_connections setting from doveconf. NethS...
- `[check_dovecot_sessions.py](file:///root/checkmk-tools/script-check-ns7/full/check_dovecot_sessions.py)` - CheckMK Local Check for Dovecot active sessions Count active Dovecot sessions via doveadm who command. NethServer 7.9...
- `[check_dovecot_status.py](file:///root/checkmk-tools/script-check-ns7/full/check_dovecot_status.py)` - CheckMK Local Check for Dovecot service status Check if Dovecot IMAP/POP3 service is active via systemctl. NethServer...
- `[check_dovecot_vsz.py](file:///root/checkmk-tools/script-check-ns7/full/check_dovecot_vsz.py)` - CheckMK Local Check for Dovecot VSZ memory limit Extract Dovecot VszLimit setting from system configuration. NethServ...
- `[check_fail2ban_status.py](file:///root/checkmk-tools/script-check-ns7/full/check_fail2ban_status.py)` - CheckMK Local Check for fail2ban service Check fail2ban service status and count banned IPs across all jails. NethSer...
- `[check_postfix_process.py](file:///root/checkmk-tools/script-check-ns7/full/check_postfix_process.py)` - CheckMK Local Check for Postfix process count Count running Postfix processes via pgrep. NethServer 7.9 Version: 1.0.0
- `[check_postfix_queue.py](file:///root/checkmk-tools/script-check-ns7/full/check_postfix_queue.py)` - CheckMK Local Check for Postfix mail queue Monitor Postfix mail queue size with thresholds. Thresholds: <20 OK, <100 ...
- `[check_postfix_status.py](file:///root/checkmk-tools/script-check-ns7/full/check_postfix_status.py)` - CheckMK Local Check for Postfix service status Check if Postfix mail server is active via systemctl. NethServer 7.9 V...
- `[check_ransomware_ns7.py](file:///root/checkmk-tools/script-check-ns7/full/check_ransomware_ns7.py)` - CheckMK Local Check for Ransomware detection Scan all Samba shares for suspicious files (encrypted extensions, ransom...
- `[check_ssh_all_sessions.py](file:///root/checkmk-tools/script-check-ns7/full/check_ssh_all_sessions.py)` - CheckMK Local Check for all SSH sessions Count all active SSH sessions (all users). NethServer 7.9 Version: 1.0.0
- `[check_ssh_root_logins.py](file:///root/checkmk-tools/script-check-ns7/full/check_ssh_root_logins.py)` - CheckMK Local Check for root SSH sessions Notify if there are SSH sessions opened as root (CRITICAL alert). NethServe...
- `[check_ssh_root_sessions.py](file:///root/checkmk-tools/script-check-ns7/full/check_ssh_root_sessions.py)` - CheckMK Local Check for SSH root session events Generate notification for every SSH root login and logout, using stat...
- `[check_webtop_https.py](file:///root/checkmk-tools/script-check-ns7/full/check_webtop_https.py)` - CheckMK Local Check for WebTop HTTPS reachability Test WebTop web interface reachability via HTTPS curl request. Neth...
- `[check_webtop_maxmemory.py](file:///root/checkmk-tools/script-check-ns7/full/check_webtop_maxmemory.py)` - CheckMK Local Check for WebTop MaxMemory setting Extract WebTop MaxMemory configuration value. NethServer 7.9 Version...
- `[check_webtop_status.py](file:///root/checkmk-tools/script-check-ns7/full/check_webtop_status.py)` - CheckMK Local Check for WebTop service status Check if WebTop Tomcat service is active via systemctl. NethServer 7.9 ...

### script-check-ns8/ - NethServer 8 Checks

Local check scripts for NethServer 8 (modular architecture, Podman/container based).

**Key Scripts:**
- `[acl-viewer.py](file:///root/checkmk-tools/script-check-ns8/full/acl-viewer.py)` - Samba Share NS8 ACL Viewer Reads *_smbacl.txt files generated by NS8 audit scripts and shows the permissions in reada...
- `[check-sos.py](file:///root/checkmk-tools/script-check-ns8/full/check-sos.py)` - CheckMK Local Check for SOS session Check if a remote support (SOS) session is active reading system logs in /var/log...
- `[check_ns8_container_health.py](file:///root/checkmk-tools/script-check-ns8/full/check_ns8_container_health.py)` - CheckMK Local Check for NS8 container health Monitor NS8 instance containers (runagent + podman): - count total/runni...
- `[check_ns8_container_inventory.py](file:///root/checkmk-tools/script-check-ns8/full/check_ns8_container_inventory.py)` - NS8 container inventory for CheckMK Version: 1.0.0
- `[check_ns8_container_resources.py](file:///root/checkmk-tools/script-check-ns8/full/check_ns8_container_resources.py)` - NS8 container resources for CheckMK Version: 1.1.0
- `[check_ns8_container_status.py](file:///root/checkmk-tools/script-check-ns8/full/check_ns8_container_status.py)` - NS8 container status for CheckMK Version: 1.3.0
- `[check_ns8_containers.py](file:///root/checkmk-tools/script-check-ns8/full/check_ns8_containers.py)` - Legacy check deprecato Version: 2.0.0
- `[check_ns8_services.py](file:///root/checkmk-tools/script-check-ns8/full/check_ns8_services.py)` - CheckMK Local Check for NS8 Mail Services Monitor main email services (clamav, rspamd, dovecot, postfix). Special con...
- `[check_ns8_smoke_test.py](file:///root/checkmk-tools/script-check-ns8/full/check_ns8_smoke_test.py)` - Minimal CheckMK local check for NS8 test pipeline Version: 1.0.0
- `[check_ns8_tomcat8.py](file:///root/checkmk-tools/script-check-ns8/full/check_ns8_tomcat8.py)` - Legacy check deprecato Version: 2.0.0
- `[check_ns8_webtop.py](file:///root/checkmk-tools/script-check-ns8/full/check_ns8_webtop.py)` - CheckMK Local Check for WebTop NS8 Monitor WebTop availability on NethServer 8. Check presence of WebTop instances an...
- `[check_nv8_status_extensions.py](file:///root/checkmk-tools/script-check-ns8/full/check_nv8_status_extensions.py)` - CheckMK Local Check for NethVoice NS8 extension recording status Monitor PJSIP registration of extensions (endpoints)...
- `[check_nv8_status_trunk.py](file:///root/checkmk-tools/script-check-ns8/full/check_nv8_status_trunk.py)` - CheckMK Local Check for NethVoice NS8 trunk status Monitor PJSIP trunk logging on NethVoice NS8. Use runagent + podma...
- `[monitor_podman_events.py](file:///root/checkmk-tools/script-check-ns8/full/monitor_podman_events.py)` - Daemon for monitoring Podman events Listen to Podman events in real time and only record events create/start/stop/rem...

### script-check-nsec8/ - NethSecurity 8 Checks

Monitoring scripts for NethSecurity 8 firewall/gateway (OpenWrt based).

**Key Scripts:**
- `[check_dhcp_leases.py](file:///root/checkmk-tools/script-check-nsec8/full/check_dhcp_leases.py)` - CheckMK local check DHCP leases per pool (pure Python). A separate CheckMK service for each DHCP pool active on NethS...
- `[check_dns_resolution.py](file:///root/checkmk-tools/script-check-nsec8/full/check_dns_resolution.py)` - CheckMK local check DNS resolution (Python puro).
- `[check_firewall_connections.py](file:///root/checkmk-tools/script-check-nsec8/full/check_firewall_connections.py)` - CheckMK local check conntrack (Python puro).
- `[check_firewall_rules.py](file:///root/checkmk-tools/script-check-nsec8/full/check_firewall_rules.py)` - CheckMK local check firewall rules (pure Python). Supports nftables (NethSecurity 8 / OpenWrt) and iptables (legacy s...
- `[check_firewall_traffic.py](file:///root/checkmk-tools/script-check-nsec8/full/check_firewall_traffic.py)` - CheckMK local check firewall traffic (Python puro).
- `[check_martian_packets.py](file:///root/checkmk-tools/script-check-nsec8/full/check_martian_packets.py)` - CheckMK local check martian packets (Python puro).
- `[check_opkg_packages.py](file:///root/checkmk-tools/script-check-nsec8/full/check_opkg_packages.py)` - CheckMK local check OPKG packages (Python puro).
- `[check_ovpn_host2net.py](file:///root/checkmk-tools/script-check-nsec8/full/check_ovpn_host2net.py)` - CheckMK local check OVPN host-to-net (pure Python).
- `[check_root_access.py](file:///root/checkmk-tools/script-check-nsec8/full/check_root_access.py)` - CheckMK local check root access (Python puro).
- `[check_uptime.py](file:///root/checkmk-tools/script-check-nsec8/full/check_uptime.py)` - CheckMK local check uptime/load (Python puro).
- `[check_vpn_tunnels.py](file:///root/checkmk-tools/script-check-nsec8/full/check_vpn_tunnels.py)` - CheckMK local check VPN tunnels (pure Python).
- `[check_wan_status.py](file:///root/checkmk-tools/script-check-nsec8/full/check_wan_status.py)` - CheckMK local check WAN status (Python puro). Version: 1.1.1
- `[check_wan_throughput.py](file:///root/checkmk-tools/script-check-nsec8/full/check_wan_throughput.py)` - CheckMK Local Check for WAN throughput on NethSecurity 8 Measures RX/TX throughput on the WAN interface in bytes/s. U...

### script-check-ubuntu/ - Ubuntu/Linux Checks

General Linux/Ubuntu monitoring scripts.

**Key Scripts:**
- `[check_arp_watch.py](file:///root/checkmk-tools/script-check-ubuntu/full/check_arp_watch.py)` - CheckMK Local Check for ARP monitoring Detect:   - CRITICAL: ARP spoofing (same IP, changed MAC)   - WARNING: New hos...
- `[check_disk_space.py](file:///root/checkmk-tools/script-check-ubuntu/full/check_disk_space.py)` - CheckMK Local Check for Disk Space Monitoring Monitors disk space usage on root filesystem with configurable threshol...
- `[check_efivars.py](file:///root/checkmk-tools/script-check-ubuntu/full/check_efivars.py)` - CheckMK Local Check for /sys/firmware/efi/efivars Monitor the filling of the efivarfs filesystem. WARNING at 80%, CRI...
- `[check_fail2ban_status.py](file:///root/checkmk-tools/script-check-ubuntu/full/check_fail2ban_status.py)` - CheckMK Local Check for Fail2ban Status Monitors fail2ban service status and counts banned IPs across all jails. Comp...
- `[check_ssh_all_sessions.py](file:///root/checkmk-tools/script-check-ubuntu/full/check_ssh_all_sessions.py)` - CheckMK Local Check for SSH Sessions Counts all active SSH sessions from all users and displays connected usernames. ...
- `[check_ssh_root_logins.py](file:///root/checkmk-tools/script-check-ubuntu/full/check_ssh_root_logins.py)` - CheckMK Local Check for Root SSH Sessions Monitors active root SSH sessions and reports IP addresses. Alerts based on...
- `[check_ssh_root_sessions.py](file:///root/checkmk-tools/script-check-ubuntu/full/check_ssh_root_sessions.py)` - CheckMK Local Check for Root SSH Session Events Tracks root SSH sessions and generates alerts for login/logout events...
- `[check_tmate_session.py](file:///root/checkmk-tools/script-check-ubuntu/full/check_tmate_session.py)` - CheckMK Local Check for active tmate sessions Outputs:   OK = session active, no viewer connected   WARNING = someone...

### script-check-proxmox/ - Proxmox VE Checks

Monitoring scripts for Proxmox Virtual Environment via API.

**Key Scripts:**
- `[check-proxmox-vm-status.py](file:///root/checkmk-tools/script-check-proxmox/full/check-proxmox-vm-status.py)` - CheckMK Local Check for Proxmox VM/CT Status Monitor runtime status of QEMU VMs and LXC containers with uptime. Proxm...
- `[check-proxmox_backup_status.py](file:///root/checkmk-tools/script-check-proxmox/full/check-proxmox_backup_status.py)` - CheckMK Local Check for Proxmox Backup Monitor last vzdump backup age (WARN 30 hours, CRIT 54 hours). Proxmox VE Vers...
- `[check-proxmox_lxc_runtime.py](file:///root/checkmk-tools/script-check-proxmox/full/check-proxmox_lxc_runtime.py)` - CheckMK Local Check for LXC Runtime Metrics Monitor CPU, memory, and disk usage for running LXC containers. Proxmox V...
- `[check-proxmox_lxc_status.py](file:///root/checkmk-tools/script-check-proxmox/full/check-proxmox_lxc_status.py)` - CheckMK Local Check for Proxmox LXC Containers Monitor LXC container status with summary and per-container checks. Pr...
- `[check-proxmox_qemu_guest_agent_status.py](file:///root/checkmk-tools/script-check-proxmox/full/check-proxmox_qemu_guest_agent_status.py)` - CheckMK Local Check for QEMU Guest Agent Verify QEMU Guest Agent status for all running VMs (pvesh JSON API). Proxmox...
- `[check-proxmox_qemu_runtime.py](file:///root/checkmk-tools/script-check-proxmox/full/check-proxmox_qemu_runtime.py)` - CheckMK Local Check for QEMU Runtime Metrics Monitor CPU, memory, and disk usage for running QEMU VMs. Proxmox VE Ver...
- `[check-proxmox_qemu_status.py](file:///root/checkmk-tools/script-check-proxmox/full/check-proxmox_qemu_status.py)` - CheckMK Local Check for Proxmox QEMU VMs Monitor QEMU VM status with summary and per-VM checks. Proxmox VE Version: 1...
- `[check-proxmox_services_status.py](file:///root/checkmk-tools/script-check-proxmox/full/check-proxmox_services_status.py)` - CheckMK Local Check for Proxmox Services Monitor essential Proxmox services (pvedaemon, pveproxy, pve-cluster, etc). ...
- `[check-proxmox_storage_status.py](file:///root/checkmk-tools/script-check-proxmox/full/check-proxmox_storage_status.py)` - CheckMK Local Check for Proxmox Storage Monitor storage usage with thresholds (WARN 80%, CRIT 90%). Proxmox VE Versio...
- `[check-proxmox_vm_monitor.py](file:///root/checkmk-tools/script-check-proxmox/full/check-proxmox_vm_monitor.py)` - CheckMK Local Check for Proxmox VM Monitor General VM and container health check with summary metrics. Proxmox VE Ver...

### script-check-tmate-server/ - tmate Server Checks

Monitoring scripts for tmate terminal sharing server.

**Key Scripts:**
- `[check_tmate_server.py](file:///root/checkmk-tools/script-check-tmate-server/full/check_tmate_server.py)` - CheckMK Local Check for the tmate SERVER Runs ONLY on the tmate server (checkmk-vps-02 / monitor01). Shows ALL connec...
- `[tmate-cleanup-stale.py](file:///root/checkmk-tools/script-check-tmate-server/full/tmate-cleanup-stale.py)` - Kill orphaned tmate-ssh-server daemon processes whose token no longer matches any active token file in /opt/tmate-tok...

### script-checkmk/ - CheckMK Server Checks

CheckMK server-side scripts and connectivity checks.

**Key Scripts:**
- `[check_host_connectivity.py](file:///root/checkmk-tools/script-checkmk/full/check_host_connectivity.py)` - Check host connectivity: ARP for same-subnet hosts, ICMP fallback for cross-VLAN hosts. Replaces check_icmp for hosts...
- `[check_host_connectivity_nmap.py](file:///root/checkmk-tools/script-checkmk/full/check_host_connectivity_nmap.py)` - Check host connectivity using nmap only (no subnet detection). nmap automatically selects ARP for same-subnet hosts a...
- `[check_host_connectivity_us.py](file:///root/checkmk-tools/script-checkmk/full/check_host_connectivity_us.py)` - Check host connectivity: ARP for same-subnet hosts, ICMP fallback for cross-VLAN hosts. Variant for multi-VLAN enviro...
- `[check_vpn_tunnels.py](file:///root/checkmk-tools/script-checkmk/full/check_vpn_tunnels.py)` - CheckMK local check: OpenVPN net-to-net tunnel status Pings the gateway of each remote subnet to verify the tunnel is...

### script-notify-checkmk/ - Notification Integration

Custom CheckMK notification scripts (Ydea ticketing, Telegram, Email with Real IP resolution).

**Key Scripts:**
- `[mail](file:///root/checkmk-tools/script-notify-checkmk/full/mail)` - Mail Bulk: yes This file is part of Checkmk (https://checkmk.com). It is subject to the terms and conditions defined ...
- `[mail-checkmk](file:///root/checkmk-tools/script-notify-checkmk/full/mail-checkmk)` - M@il Bulk: yes CheckMK notification script - sends HTML email with real IP and FRP tunnel detection. Version: 1.0.1 G...
- `[mail-checkmk.py](file:///root/checkmk-tools/script-notify-checkmk/full/mail-checkmk.py)` - M@il Bulk: yes CheckMK notification script - sends HTML email with real IP and FRP tunnel detection. Version: 1.0.0 G...
- `[mail_realip](file:///root/checkmk-tools/script-notify-checkmk/full/mail_realip)` - Mail Bulk: yes Funzione per ottenere colore stato Funzione per abbreviare stato
- `[mail_realip.py](file:///root/checkmk-tools/script-notify-checkmk/full/mail_realip.py)` - M@il Bulk: yes CheckMK notification script - sends HTML email with real IP and FRP tunnel detection. Version: 1.0.0
- `[notify_copilot_autofix.py](file:///root/checkmk-tools/script-notify-checkmk/full/notify_copilot_autofix.py)` - CheckMK notification plugin - triggers Copilot CLI autonomous investigation and autofix  Flow: CMK alert → this scrip...
- `[notify_ticket_watcher.py](file:///root/checkmk-tools/script-notify-checkmk/full/notify_ticket_watcher.py)` - CheckMK log watcher for Telegram ticket notifications Reads notify.log, intercepts [TICKET-EVENT] [CREATED] and sends...
- `[notify_ticket_watcher_sp.py](file:///root/checkmk-tools/script-notify-checkmk/full/notify_ticket_watcher_sp.py)` - Telegram ticket notification watcher - Studio Paci Reads notify.log, intercepts [TICKET-EVENT] [CREATED] and sends Te...
- `[telegram.py](file:///root/checkmk-tools/script-notify-checkmk/full/telegram.py)` - telegram - Generic Telegram Notification Bulk: no CheckMK notification script - sends alerts to a Telegram channel. C...
- `[telegram_c01.py](file:///root/checkmk-tools/script-notify-checkmk/full/telegram_c01.py)` - telegram_c01 - Telegram notification script for customer C01. Version: 1.5.0
- `[telegram_c01_selfmon.py](file:///root/checkmk-tools/script-notify-checkmk/full/telegram_c01_selfmon.py)` - telegram_c01_selfmon - Telegram self-monitoring notification script for customer C01. Version: 1.5.0
- `[telegram_cl00.py](file:///root/checkmk-tools/script-notify-checkmk/full/telegram_cl00.py)` - telegram_cl00 - Telegram notification script for customer CL00. Version: 1.7.0
- `[telegram_get_chatid.py](file:///root/checkmk-tools/script-notify-checkmk/full/telegram_get_chatid.py)` - Utility to get CHAT_ID and verify TOKEN Usage:     python3 telegram_get_chatid.py     python3 telegram_get_chatid.py ...
- `[telegram_realip](file:///root/checkmk-tools/script-notify-checkmk/full/telegram_realip)` - Telegram - v1.1.0 URL-encode helper (returns value instead of printing directly)
- `[telegram_realip.py](file:///root/checkmk-tools/script-notify-checkmk/full/telegram_realip.py)` - telegram_realip - Telegram Notification with Real IP Support Bulk: no CheckMK notification script - sends Telegram me...
- `[telegram_selfmon](file:///root/checkmk-tools/script-notify-checkmk/full/telegram_selfmon)` - Telegram Self-Monitoring - v1.1.0 Script dedicato per notifiche dell'host "monitor" (self-monitoring CheckMK) CHAT_ID...
- `[telegram_selfmon.py](file:///root/checkmk-tools/script-notify-checkmk/full/telegram_selfmon.py)` - telegram_selfmon - Generic Telegram Self-Monitoring Notification Bulk: no CheckMK notification script - sends self-mo...
- `[telegram_tmate](file:///root/checkmk-tools/script-notify-checkmk/full/telegram_tmate)` - telegram_tmate.py - Telegram notifications for Check MK Tmate channel TOKEN and CHAT_ID read from OMD standard enviro...
- `[telegram_tmate.env.template](file:///root/checkmk-tools/script-notify-checkmk/full/telegram_tmate.env.template)` - telegram_tmate.env Configurazione notifiche Telegram - Canale: Check MK Tmate  ISTRUZIONI: 1. Crea il bot su Telegram...
- `[telegram_tmate.py](file:///root/checkmk-tools/script-notify-checkmk/full/telegram_tmate.py)` - Telegram notifications for Check MK Tmate channel TOKEN and CHAT_ID read from OMD standard environment file:   /omd/s...
- `[ydea_ag](file:///root/checkmk-tools/script-notify-checkmk/full/ydea_ag)` - Ydea AG Copia completa di ydea_ag + funzioni intelligenti per rilevare e descrivere problemi HOST DOWN (connection re...
- `[ydea_ag.py](file:///root/checkmk-tools/script-notify-checkmk/full/ydea_ag.py)` - ydea_ag - Ydea Ticketing Integration with Smart Detection Bulk: no CheckMK notification script - integrates with Ydea...
- `[ydea_ag_testing](file:///root/checkmk-tools/script-notify-checkmk/full/ydea_ag_testing)` - ydea_ag - Ydea Ticketing Integration with Smart Detection Bulk: no CheckMK notification script - integrates with Ydea...
- `[ydea_cache_validator.py](file:///root/checkmk-tools/script-notify-checkmk/full/ydea_cache_validator.py)` - Cache Integrity Validator for Ydea Integration Periodically checks if tickets in the local JSON cache actually exist ...
- `[ydea_la](file:///root/checkmk-tools/script-notify-checkmk/full/ydea_la)` - Ydea LA Copia completa di ydea_la + funzioni intelligenti per rilevare e descrivere problemi HOST DOWN (connection re...
- `[ydea_la.py](file:///root/checkmk-tools/script-notify-checkmk/full/ydea_la.py)` - ydea_la - Ydea Ticketing Integration with Smart Detection (LA Environment) Bulk: no CheckMK notification script - int...
- `[ydea_la_testing](file:///root/checkmk-tools/script-notify-checkmk/full/ydea_la_testing)` - ydea_la - Ydea Ticketing Integration with Smart Detection (LA Environment) Bulk: no CheckMK notification script - int...

### Ydea-Toolkit/ - Ydea Ticketing Integration

Complete integration and utility scripts for Ydea ticketing system.

**Key Scripts:**
- `[analyze-custom-attributes.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/analyze-custom-attributes.sh)` - Analyze the customAttributes of many tickets Temporary file to collect all customAttributes
- `[analyze-ticket-data.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/analyze-ticket-data.sh)` - analyze-ticket-data.sh ÔÇö Analyze existing tickets to extract categories, priorities and SLA Extracts unique IDs fro...
- `[analyze_custom_attributes.py](file:///root/checkmk-tools/Ydea-Toolkit/full/analyze_custom_attributes.py)` - Analizza custom attributes ticket
- `[analyze_ticket_data.py](file:///root/checkmk-tools/Ydea-Toolkit/full/analyze_ticket_data.py)` - Analizza dati ticket
- `[create-monitoring-ticket.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/create-monitoring-ticket.sh)` - Create Ydea ticket from CheckMK alarm Load Premium_Mon configuration Read parameters from CheckMK
- `[create-ticket-ita.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/create-ticket-ita.sh)` - Convert Italian priority to English
- `[create_monitoring_ticket.py](file:///root/checkmk-tools/Ydea-Toolkit/full/create_monitoring_ticket.py)` - Create Ydea ticket from CheckMK alarm Convert CheckMK alarms to Ydea tickets with: - Automatic determination of type ...
- `[create_ticket_ita.py](file:///root/checkmk-tools/Ydea-Toolkit/full/create_ticket_ita.py)` - Create test tickets in Italian
- `[esempi-ydea.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/esempi-ydea.sh)` - examples-ydea.sh - Example script for common operations Upload credentials Ticket aperti
- `[esempi_ydea.py](file:///root/checkmk-tools/Ydea-Toolkit/full/esempi_ydea.py)` - Esempi uso API Ydea
- `[explore-anagrafica.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/explore-anagrafica.sh)` - Explore the registry data to find the ALS Test various registry endpoints
- `[explore-sla-endpoint.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/explore-sla-endpoint.sh)` - Explore possible SLA endpoints/fields in YDEA API Test 1: Cerca endpoint /sla Test 2: Cerca nella struttura anagrafica
- `[explore-ydea-api.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/explore-ydea-api.sh)` - explore-ydea-api.sh — Explore available Ydea API endpoints Use this script to find out what endpoints exist and how t...
- `[explore_anagrafica.py](file:///root/checkmk-tools/Ydea-Toolkit/full/explore_anagrafica.py)` - Esplora endpoint anagrafica
- `[explore_sla_endpoint.py](file:///root/checkmk-tools/Ydea-Toolkit/full/explore_sla_endpoint.py)` - Esplora endpoint SLA
- `[explore_ydea_api.py](file:///root/checkmk-tools/Ydea-Toolkit/full/explore_ydea_api.py)` - Explore available Ydea API endpoints Test various API endpoints to discover available functionality. Usage:     explo...
- `[get-full-ticket.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/get-full-ticket.sh)` - ${TICKET_ID}..."ensure_token ${TICKET_ID} (ALL FIELDS):" 1528466 (with manual SLA):"
- `[get-ticket-by-id.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/get-ticket-by-id.sh)` - Retrieves a specific ticket by numeric ID Toolkit source for helper functions only Make sure you have the token
- `[get-ticket-detail.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/get-ticket-detail.sh)` - ${TICKET_ID}..."ensure_token
- `[get_full_ticket.py](file:///root/checkmk-tools/Ydea-Toolkit/full/get_full_ticket.py)` - Retrieve full ticket with all details Usage:     get_full_ticket.py <ticket_id> Version: 1.0.0
- `[get_ticket_by_id.py](file:///root/checkmk-tools/Ydea-Toolkit/full/get_ticket_by_id.py)` - Retrieve Ydea ticket details by ID Retrieves and displays complete details of a Ydea ticket given its ID. Usage:     ...
- `[get_ticket_detail.py](file:///root/checkmk-tools/Ydea-Toolkit/full/get_ticket_detail.py)` - Get ticket detail by ID Usage:     get_ticket_detail.py <ticket_id> Version: 1.0.0
- `[inspect-ticket.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/inspect-ticket.sh)` - Inspect a single ticket to see the complete structure Toolkit source for helper functions only Make sure you have the...
- `[inspect_ticket.py](file:///root/checkmk-tools/Ydea-Toolkit/full/inspect_ticket.py)` - Inspect complete Ydea ticket structure Shows all fields and structure of a ticket for analysis. Usage:     inspect_ti...
- `[install-ydea-checkmk-integration.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/install-ydea-checkmk-integration.sh)` - install-ydea-checkmk-integration.sh Quick installation script CheckMK integration → Ydea Output colors Configuration ...
- `[install_ydea_checkmk_integration.py](file:///root/checkmk-tools/Ydea-Toolkit/full/install_ydea_checkmk_integration.py)` - CheckMK integration installer → Ydea Quick installation script to integrate CheckMK with Ydea Toolkit. Copy notificat...
- `[list-tipo-values.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/list-tipo-values.sh)` - List all values ​​of the 'type' field
- `[list_tipo_values.py](file:///root/checkmk-tools/Ydea-Toolkit/full/list_tipo_values.py)` - List of possible values for ticket 'type' field Usage:     list_type_values.py Version: 1.0.0
- `[quick-test-ydea-api.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/quick-test-ydea-api.sh)` - quick-test-ydea-api.sh — Ydea API connection quick test Verify that your credentials work before running full discove...
- `[quick_test_ydea_api.py](file:///root/checkmk-tools/Ydea-Toolkit/full/quick_test_ydea_api.py)` - Quick test Ydea API Test rapido funzionalità base API Ydea: login, get tickets, get categories. Usage:     quick_test...
- `[search-anagrafica.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/search-anagrafica.sh)` - No description available
- `[search-sla-in-contracts.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/search-sla-in-contracts.sh)` - Search SLA Premium_Mon in contracts Retrieve all contracts (paged)
- `[search-ticket-by-code.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/search-ticket-by-code.sh)` - Search for a ticket by code (e.g. TK25/003209) Toolkit source for helper functions only Make sure you have the token
- `[search_anagrafica.py](file:///root/checkmk-tools/Ydea-Toolkit/full/search_anagrafica.py)` - Search registry by name Usage:     search_anagrafica.py <search_term> Version: 1.0.0
- `[search_sla_in_contracts.py](file:///root/checkmk-tools/Ydea-Toolkit/full/search_sla_in_contracts.py)` - Cerca SLA nei contratti
- `[search_ticket_by_code.py](file:///root/checkmk-tools/Ydea-Toolkit/full/search_ticket_by_code.py)` - Search Ydea tickets by code Search for Ydea tickets using the ticket code (e.g. TK26/000123). Usage:     search_ticke...
- `[sla-premium-mon-ids.example.json](file:///root/checkmk-tools/Ydea-Toolkit/full/sla-premium-mon-ids.example.json)` - No description available
- `[test-contract-variants.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/test-contract-variants.sh)` - Test contract field variants for SLA Test contract (configured on UI with Premium_Mon SLA)
- `[test-curl.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/test-curl.sh)` - No description available
- `[test-sla-api.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/test-sla-api.sh)` - Test new YDEA API for automatic SLA  YDEA has implemented API for automatic SLA insertion: - Default SLA of the regis...
- `[test-ticket-creation-web.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/test-ticket-creation-web.sh)` - Test ticket creation via HTML form (real data from HAR) Configuration Credentials (to be configured)
- `[test-ticket-creation.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/test-ticket-creation.sh)` - Test ticket creation for each typeset -euo pipefail Test cases for each type (including WARNING)declare -A Pause betw...
- `[test-ticket-with-contract.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/test-ticket-with-contract.sh)` - ############################################################################### Script to test the creation of a tick...
- `[test-ydea-integration.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/test-ydea-integration.sh)` - Complete CheckMK integration test script → Ydea Run this script to verify that everything is working correctly Colori...
- `[test_contract_variants.py](file:///root/checkmk-tools/Ydea-Toolkit/full/test_contract_variants.py)` - Test varianti contratti
- `[test_curl.py](file:///root/checkmk-tools/Ydea-Toolkit/full/test_curl.py)` - Basic Ydea API connection test with curl-like output Test the basic connection to the Ydea API by showing headers and...
- `[test_sla_api.py](file:///root/checkmk-tools/Ydea-Toolkit/full/test_sla_api.py)` - Test endpoint SLA
- `[test_ticket_creation.py](file:///root/checkmk-tools/Ydea-Toolkit/full/test_ticket_creation.py)` - Test creazione ticket
- `[test_ticket_creation_web.py](file:///root/checkmk-tools/Ydea-Toolkit/full/test_ticket_creation_web.py)` - Test ticket creation via HTML Form (Web Scraping) Simulate a browser for: 1. Log in to the web 2. Extract CSRF token ...
- `[test_ticket_with_contract.py](file:///root/checkmk-tools/Ydea-Toolkit/full/test_ticket_with_contract.py)` - Test ticket creation with associated contract Prerequisites: 1. Contract created in Ydea UI for registry number 23392...
- `[test_ydea_integration.py](file:///root/checkmk-tools/Ydea-Toolkit/full/test_ydea_integration.py)` - Complete CheckMK -> Ydea integration test Performs a series of tests to verify: 1. File existence and permissions 2. ...
- `[ydea-discover-sla-ids.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/ydea-discover-sla-ids.sh)` - ydea-discover-sla-ids.sh — Discover IDs by categories, subcategories and custom SLA Used to find IDs needed for ticke...
- `[ydea-health-monitor.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/ydea-health-monitor.sh)` - Monitoraggio disponibilità Ydea API Check every 15 minutes if Ydea is reachable and notify via email if down Use abso...
- `[ydea-monitoring-integration.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/ydea-monitoring-integration.sh)` - ydea-monitoring-integration.sh Integration between monitoring systems and Ydea for automatic ticket creation Configur...
- `[ydea-templates.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/ydea-templates.sh)` - Default templates for Ydea tickets Generate JSON for ticket creation via Ydea API
- `[ydea-ticket-monitor.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/ydea-ticket-monitor.sh)` - Automatic tracking ticket status monitoring Periodically updates the status of tickets and removes old resolved ones ...
- `[ydea-toolkit-clean.sh](file:///root/checkmk-tools/Ydea-Toolkit/full/ydea-toolkit-clean.sh)` - ydea-toolkit.sh - Complete toolkit for Ydea API v2 Includes login, token management and ticket helper functions Load ...
- `[ydea-toolkit.py](file:///root/checkmk-tools/Ydea-Toolkit/full/ydea-toolkit.py)` - Complete toolkit for Ydea API v2 Includes login, token management, CRUD ticket, tracking system, logging. Python conv...
- `[ydea_common.py](file:///root/checkmk-tools/Ydea-Toolkit/full/ydea_common.py)` - Shared module for Ydea-Toolkit common utilities Provides common functionality used by all scripts: - Logging utilitie...
- `[ydea_discover_sla_ids.py](file:///root/checkmk-tools/Ydea-Toolkit/full/ydea_discover_sla_ids.py)` - Discover IDs by categories, subcategories and custom SLA Used to find IDs needed for ticket management with Premium_M...
- `[ydea_health_monitor.py](file:///root/checkmk-tools/Ydea-Toolkit/full/ydea_health_monitor.py)` - Ydea API availability monitor Periodically checks if Ydea is reachable and notifies via email if down/recovery. Manag...
- `[ydea_la_testing](file:///root/checkmk-tools/Ydea-Toolkit/full/ydea_la_testing)` - Ydea Ticketing Integration with Smart Detection (LA Testing Environment) Bulk: no CheckMK notification script - integ...
- `[ydea_monitoring_integration.py](file:///root/checkmk-tools/Ydea-Toolkit/full/ydea_monitoring_integration.py)` - System monitoring integration with Ydea Monitor CPU, memory, disk and systemd services. Automatically create Ydea tic...
- `[ydea_notify_correlator.py](file:///root/checkmk-tools/Ydea-Toolkit/full/ydea_notify_correlator.py)` - Correlate CheckMK notify.log with ydea-toolkit.log to produce a unified timeline. Each CheckMK notification that invo...
- `[ydea_templates.py](file:///root/checkmk-tools/Ydea-Toolkit/full/ydea_templates.py)` - Default templates for Ydea tickets Generate JSON for ticket creation via Ydea API with predefined templates for vario...
- `[ydea_ticket_monitor.py](file:///root/checkmk-tools/Ydea-Toolkit/full/ydea_ticket_monitor.py)` - Automatic tracking ticket status monitoring Periodically updates the status of tickets and removes old resolved ones....

### script-ps-tools/ - PowerShell Utilities

PowerShell scripts for Windows automation, backups, and integrity verification.

**Key Scripts:**
- `[backup-quick.ps1](file:///root/checkmk-tools/script-ps-tools/backup-quick.ps1)` - Quick Backup Script Repository CheckMK-Tools QUICK version without integrity check (to be used after check-integrity....
- `[backup-simple-pc.ps1](file:///root/checkmk-tools/script-ps-tools/backup-simple-pc.ps1)` - Automatic Backup Script Repository CheckMK-Tools Simplified version for Scheduled Task (ASCII characters only)
- `[backup-simple.ps1](file:///root/checkmk-tools/script-ps-tools/backup-simple.ps1)` - Automatic Backup Script Repository CheckMK-Tools Simplified version for Scheduled Task (ASCII characters only)
- `[backup-sync-complete.ps1](file:///root/checkmk-tools/script-ps-tools/backup-sync-complete.ps1)` - Full Backup Script CheckMK-Tools Repository Local + optional backup to network share (configure BACKUP_NETWORK_PATH e...
- `[check-backup-status.ps1](file:///root/checkmk-tools/script-ps-tools/check-backup-status.ps1)` - Check Automatic Backup Status Show last run results and log Verify that the task exists Ottieni info task
- `[check-integrity.ps1](file:///root/checkmk-tools/script-ps-tools/check-integrity.ps1)` - CheckMK-Tools Repository Integrity Check Script Verify syntax of all scripts without backing up
- `[fix-py36-compat.ps1](file:///root/checkmk-tools/script-ps-tools/fix-py36-compat.ps1)` - Fix Python 3.6 compatibility - remove unsupported reconfigure() Removes reconfigure() lines that don't work on Python...
- `[repair-corrupted-scripts.ps1](file:///root/checkmk-tools/script-ps-tools/repair-corrupted-scripts.ps1)` - Script Repair Corrupted Scripts Repair corrupt scripts in install/checkmk-installer/ using the correct versions ═════...
- `[repair-with-confirmation.ps1](file:///root/checkmk-tools/script-ps-tools/repair-with-confirmation.ps1)` - > Check WSL
- `[run-backup-unattended.ps1](file:///root/checkmk-tools/script-ps-tools/run-backup-unattended.ps1)` - Wrapper for performing backups in unattended mode with logging Create log folder if it does not exist Record start of...
- `[run-backup-with-log.ps1](file:///root/checkmk-tools/script-ps-tools/run-backup-with-log.ps1)` - Wrapper for logging backups Ensure that the log folder exists Run backups
- `[setup-backup-task.ps1](file:///root/checkmk-tools/script-ps-tools/setup-backup-task.ps1)` - Setup Scheduled Task for Automatic Backup Runs backup-sync-complete.ps1 every hour Verify that the script exists ════...

### script-tools/ - Core Deployment & Management Tools

Utility scripts for agent installation, deployment, backup, sync, and upgrades. Organised by subfolder:

#### `script-tools/full/backup_restore/` - Backup & Recovery management

- `[README.md](file:///root/checkmk-tools/script-tools/full/backup_restore/README.md)` - backup_restore
- `[backup-checkmk.py](file:///root/checkmk-tools/script-tools/full/backup_restore/backup-checkmk.py)` - backup-checkmk.py Creates an OMD site backup archive and removes archives older than retention days. Version: 1.0.0
- `[checkmk_backup.py](file:///root/checkmk-tools/script-tools/full/backup_restore/checkmk_backup.py)` - CheckMK Disaster Recovery Backup Tool Performs a complete backup of a CheckMK site for Disaster Recovery. Includes co...
- `[checkmk_backup_cleanup.py](file:///root/checkmk-tools/script-tools/full/backup_restore/checkmk_backup_cleanup.py)` - CheckMK Backup Cleanup Tool Manages CheckMK backup retention and renaming: - Renames completed backups with timestamp...
- `[checkmk_compress_native_backup.py](file:///root/checkmk-tools/script-tools/full/backup_restore/checkmk_compress_native_backup.py)` - checkmk_compress_native_backup.py Version: 1.0.0
- `[checkmk_config_backup.py](file:///root/checkmk-tools/script-tools/full/backup_restore/checkmk_config_backup.py)` - Full DR backup of CheckMK configuration. Version: 1.0.0
- `[checkmk_config_backup_minimal.py](file:///root/checkmk-tools/script-tools/full/backup_restore/checkmk_config_backup_minimal.py)` - CheckMK configuration minimal backup. Version: 1.0.0
- `[checkmk_config_backup_ultra_minimal.py](file:///root/checkmk-tools/script-tools/full/backup_restore/checkmk_config_backup_ultra_minimal.py)` - CheckMK ultra-minimal backup. Version: 1.0.0
- `[checkmk_download_backup.py](file:///root/checkmk-tools/script-tools/full/backup_restore/checkmk_download_backup.py)` - CheckMK Backup Download Tool Download CheckMK backups from DigitalOcean Spaces using rclone: - Interactive UI with co...
- `[checkmk_manage_job00_daily.py](file:///root/checkmk-tools/script-tools/full/backup_restore/checkmk_manage_job00_daily.py)` - CheckMK Job00 Daily Backup Management Manages daily compressed CheckMK backups (job00-complete): - Compresses from 36...
- `[checkmk_manage_job01_weekly.py](file:///root/checkmk-tools/script-tools/full/backup_restore/checkmk_manage_job01_weekly.py)` - CheckMK Job01 Weekly Backup Management Manages weekly full CheckMK backups (job01-complete): - Direct upload without ...
- `[checkmk_rclone_space_dyn.py](file:///root/checkmk-tools/script-tools/full/backup_restore/checkmk_rclone_space_dyn.py)` - checkmk_rclone_space_dyn.py Version: 1.0.0
- `[checkmk_rclone_space_pers.py](file:///root/checkmk-tools/script-tools/full/backup_restore/checkmk_rclone_space_pers.py)` - checkmk_rclone_space_pers.py Version: 1.0.0
- `[checkmk_rclone_spaces.py](file:///root/checkmk-tools/script-tools/full/backup_restore/checkmk_rclone_spaces.py)` - checkmk_rclone_spaces.py Version: 1.0.0
- `[checkmk_restore.py](file:///root/checkmk-tools/script-tools/full/backup_restore/checkmk_restore.py)` - CheckMK Disaster Recovery Restore Tool Interactive tool for restoring CheckMK sites from DR backups. Supports direct ...
- `[checkmk_restore_compressed.py](file:///root/checkmk-tools/script-tools/full/backup_restore/checkmk_restore_compressed.py)` - checkmk_restore_compressed.py Script to restore compressed CheckMK backups. Version: 1.0.0
- `[checkmk_restore_dr.py](file:///root/checkmk-tools/script-tools/full/backup_restore/checkmk_restore_dr.py)` - checkmk_restore_dr.py Python entrypoint for the interactive DR restore workflow. Delegates to the existing canonical ...
- `[cleanup-checkmk-retention.py](file:///root/checkmk-tools/script-tools/full/backup_restore/cleanup-checkmk-retention.py)` - cleanup-checkmk-retention.py Python entrypoint that delegates to cleanup-checkmk-retention.sh. Version: 1.0.0
- `[install-backup-jobs.py](file:///root/checkmk-tools/script-tools/full/backup_restore/install-backup-jobs.py)` - Install systemd timers for automatic CheckMK backups - job00: Compressed daily (1.2MB), retention 90, 03:00 - job01: ...
- `[patch-wrapper-multicandidate.py](file:///root/checkmk-tools/script-tools/full/backup_restore/patch-wrapper-multicandidate.py)` - Patch the deployed wrapper on srv-monitoring to process ALL backup candidates (not just the newest one). Fixes: job01...
- `[patch-wrapper-sort-fix.py](file:///root/checkmk-tools/script-tools/full/backup_restore/patch-wrapper-sort-fix.py)` - Patch /usr/local/sbin/checkmk_cloud_backup_push_run.sh - fix remote retention sort bug.
- `[checkmk-backup-job00.service](file:///root/checkmk-tools/script-tools/full/backup_restore/systemd/checkmk-backup-job00.service)` - No description available
- `[checkmk-backup-job00.timer](file:///root/checkmk-tools/script-tools/full/backup_restore/systemd/checkmk-backup-job00.timer)` - No description available
- `[checkmk-backup-job01.service](file:///root/checkmk-tools/script-tools/full/backup_restore/systemd/checkmk-backup-job01.service)` - No description available
- `[checkmk-backup-job01.timer](file:///root/checkmk-tools/script-tools/full/backup_restore/systemd/checkmk-backup-job01.timer)` - No description available

#### `script-tools/full/deploy/` - OS-aware agent and script deployment

- `[README.md](file:///root/checkmk-tools/script-tools/full/deploy/README.md)` - deploy
- `[auto-deploy-checks.py](file:///root/checkmk-tools/script-tools/full/deploy/auto-deploy-checks.py)` - Auto Deploy CheckMK Checks - Interactive Install/Remove CheckMK script Interactive menu for: - Install CheckMK script...
- `[deploy-from-repo.py](file:///root/checkmk-tools/script-tools/full/deploy/deploy-from-repo.py)` - deploy-from-repo.py Python entrypoint that delegates to deploy-from-repo.sh. Version: 1.0.0
- `[deploy-monitoring-scripts.py](file:///root/checkmk-tools/script-tools/full/deploy/deploy-monitoring-scripts.py)` - deploy-monitoring-scripts.py Python entrypoint that delegates to deploy-monitoring-scripts.sh. Version: 1.0.0
- `[deploy-plain-agent-multi.py](file:///root/checkmk-tools/script-tools/full/deploy/deploy-plain-agent-multi.py)` - deploy-plain-agent-multi.py Python entrypoint that delegates to deploy-plain-agent-multi.sh. Version: 1.0.0
- `[deploy-plain-agent.py](file:///root/checkmk-tools/script-tools/full/deploy/deploy-plain-agent.py)` - deploy-plain-agent.py Python entrypoint that delegates to deploy-plain-agent.sh. Version: 1.0.0
- `[deploy_monitoring.py](file:///root/checkmk-tools/script-tools/full/deploy/deploy_monitoring.py)` - Deploy CheckMK Local Checks Interactive deployment of control scripts (r*.sh) from the repository to the local CheckM...
- `[smart-deploy-hybrid.py](file:///root/checkmk-tools/script-tools/full/deploy/smart-deploy-hybrid.py)` - smart-deploy-hybrid.py Python entrypoint that delegates to smart-deploy-hybrid.sh. Version: 1.0.0
- `[smart_deploy.py](file:///root/checkmk-tools/script-tools/full/deploy/smart_deploy.py)` - Smart Deploy for CheckMK Scripts Create "smart" wrappers for CheckMK scripts that handle: - Automatic download from G...

#### `script-tools/full/installation/` - Agent, service, and sync installers

- `[I-install-checkmk-sync.py](file:///root/checkmk-tools/script-tools/full/installation/I-install-checkmk-sync.py)` - install-checkmk-sync.py - CheckMK unified installer Execute in sequence:   STEP A → CheckMK Agent install (download f...
- `[INSTALLA-FRPC.cmd](file:///root/checkmk-tools/script-tools/full/installation/INSTALLA-FRPC.cmd)` - No description available
- `[README.md](file:///root/checkmk-tools/script-tools/full/installation/README.md)` - installation
- `[.env.example](file:///root/checkmk-tools/script-tools/full/installation/checkmk/.env.example)` - SSH Root SMTP relay for Postfix (loopback-only if left empty) Firewall Certbot
- `[README.md](file:///root/checkmk-tools/script-tools/full/installation/checkmk/README.md)` - checkmk (Python) # Usage (Ubuntu) Menu (recommended) Guided setup: generate .env without having to edit it by hand Al...
- `[installer.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/installer.py)` - checkmk - Python guided installer (Ubuntu) for CheckMK and related services. Re-implements the workflow in script-too...
- `[__init__.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/lib/__init__.py)` - No description available
- `[common.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/lib/common.py)` - No description available
- `[config.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/lib/config.py)` - No description available
- `[__init__.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/__init__.py)` - No description available
- `[apache.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/apache.py)` - No description available
- `[auto_git_sync.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/auto_git_sync.py)` - No description available
- `[backup_jobs.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/backup_jobs.py)` - No description available
- `[certbot.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/certbot.py)` - No description available
- `[checkmk.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/checkmk.py)` - No description available
- `[checkmk_auto_upgrade.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/checkmk_auto_upgrade.py)` - No description available
- `[config_backup.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/config_backup.py)` - No description available
- `[config_backup_minimal.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/config_backup_minimal.py)` - No description available
- `[config_backup_ultra_minimal.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/config_backup_ultra_minimal.py)` - No description available
- `[deploy_checks.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/deploy_checks.py)` - No description available
- `[dns_refresh.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/dns_refresh.py)` - Refresh DNS cache every 30 seconds, reload CheckMK config every 5 minutes. Needed for DHCP hosts that can change IP a...
- `[fail2ban.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/fail2ban.py)` - IP always whitelisted (never banned) Constructs ignoreip by merging the fixed IPs with those from the config
- `[firewall.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/firewall.py)` - No description available
- `[log_optimizer.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/log_optimizer.py)` - No description available
- `[notify_scripts.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/notify_scripts.py)` - No description available
- `[ntp.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/ntp.py)` - No description available
- `[packages.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/packages.py)` - No description available
- `[postfix.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/postfix.py)` - Configure Postfix SMTP relay with SASL authentication.
- `[rclone_setup.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/rclone_setup.py)` - No description available
- `[remove_all.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/remove_all.py)` - backup_file() now stores everything in _BACKUP_DIR (/var/backups/checkmk-installer) plus we still clean any stale .ba...
- `[ssh.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/ssh.py)` - No description available
- `[system_auto_updates.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/system_auto_updates.py)` - No description available
- `[timeshift.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/timeshift.py)` - Minimum free space required on the partition (GB) Returns (device, avail_gb) of the root filesystem, or None if undet...
- `[unattended.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/unattended.py)` - No description available
- `[verify.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/verify.py)` - No description available
- `[ydea_toolkit.py](file:///root/checkmk-tools/script-tools/full/installation/checkmk/steps/ydea_toolkit.py)` - No description available
- `[install-agent-nsec8.py](file:///root/checkmk-tools/script-tools/full/installation/install-agent-nsec8.py)` - install-agent-nsec8.py — CheckMK Agent Installer — PERSISTENT Edition Install and configure CheckMK Agent on NethSecu...
- `[install-checkmk-log-optimizer.py](file:///root/checkmk-tools/script-tools/full/installation/install-checkmk-log-optimizer.py)` - install-checkmk-log-optimizer.py Python entrypoint that delegates to install-checkmk-log-optimizer.sh. Version: 1.0.0
- `[install-checkmk-agent-linux.py](file:///root/checkmk-tools/script-tools/full/installation/install-checkmk-agent-linux.py)` - CheckMK unified installer Execute in sequence:   STEP A → CheckMK Agent install (download from CMK server, TCP 6556)...
- `[install-frpc-pc.ps1](file:///root/checkmk-tools/script-tools/full/installation/install-frpc-pc.ps1)` - >
- `[install-tmate-client.py](file:///root/checkmk-tools/script-tools/full/installation/install-tmate-client.py)` - Install and configure tmate client to connect to a self-hosted tmate server  After installation the SSH token is avai...
- `[install-tmate-server.py](file:///root/checkmk-tools/script-tools/full/installation/install-tmate-server.py)` - Install and configure tmate-ssh-server + token receiver infrastructure on a VPS  What it does: 1. Install tmate + tma...
- `[install_frpc.py](file:///root/checkmk-tools/script-tools/full/installation/install_frpc.py)` - Standalone FRPC Installer Quick installation and configuration of FRPC (Fast Reverse Proxy Client). Supports Linux (s...
- `[setup-persistent-nsec8.py](file:///root/checkmk-tools/script-tools/full/installation/setup-persistent-nsec8.py)` - setup-persistent-nsec8.py — CheckMK Persistent Setup (NO agent install) Configure everything needed for CheckMK persi...
- `[setup-tmate-token-push.py](file:///root/checkmk-tools/script-tools/full/installation/setup-tmate-token-push.py)` - Configure tmate token push on a CLIENT HOST  Installs the private key and configures the systemd service to push the ...
- `[tmate-receive-token.py](file:///root/checkmk-tools/script-tools/full/installation/tmate-receive-token.py)` - tmate-receive-token.py Forced command on the server: receives tmate tokens from clients via SSH  Called from /root/.s...

#### `script-tools/full/misc/` - Miscellaneous utilities (swap, compression, disaster recovery)

- `[README.md](file:///root/checkmk-tools/script-tools/full/misc/README.md)` - misc
- `[checkmk_compress.py](file:///root/checkmk-tools/script-tools/full/misc/checkmk_compress.py)` - Compress Native CheckMK Backups Optimize CheckMK native backups by removing heavy files (RRD, tmp, etc.) and recompre...
- `[checkmk_disaster_recovery.py](file:///root/checkmk-tools/script-tools/full/misc/checkmk_disaster_recovery.py)` - CheckMK Disaster Recovery Tool Complete disaster recovery solution for CheckMK: 1. Lists available backups on cloud (...
- `[increase-swap.py](file:///root/checkmk-tools/script-tools/full/misc/increase-swap.py)` - increase-swap.py Python entrypoint that delegates to increase-swap.sh. Version: 1.0.0

#### `script-tools/full/monitoring_diagnostics/` - Diagnostics, tuning, and host status checking

- `[README.md](file:///root/checkmk-tools/script-tools/full/monitoring_diagnostics/README.md)` - monitoring_diagnostics
- `[check_host_alive.py](file:///root/checkmk-tools/script-tools/full/monitoring_diagnostics/check_host_alive.py)` - CheckMK/Nagios active check: host UP/DOWN via multi-layer probe Replaces check_icmp for hosts that block ICMP ping (N...
- `[check_host_down_confidence.py](file:///root/checkmk-tools/script-tools/full/monitoring_diagnostics/check_host_down_confidence.py)` - OFFLINE HOST reliability diagnosis Performs multi-layer diagnosis to determine with high confidence if a host is real...
- `[check_host_status.py](file:///root/checkmk-tools/script-tools/full/monitoring_diagnostics/check_host_status.py)` - CheckMK/Nagios plugin: Host UP/DOWN via multi-probe confidence scoring Replaces check_icmp with a multi-layer approac...
- `[checkmk-tuning-check.py](file:///root/checkmk-tools/script-tools/full/monitoring_diagnostics/checkmk-tuning-check.py)` - Checks the status of Nagios/CheckMK RAW tuning and automatically applies the fix if necessary. Diagnosis logic:   - R...
- `[checkmk-tuning-interactive-v3.py](file:///root/checkmk-tools/script-tools/full/monitoring_diagnostics/checkmk-tuning-interactive-v3.py)` - Wrapper deprecated variant. Use checkmk-tuning-interactive.py Version: 1.0.0
- `[checkmk-tuning-interactive-v4.py](file:///root/checkmk-tools/script-tools/full/monitoring_diagnostics/checkmk-tuning-interactive-v4.py)` - Wrapper deprecated variant. Use checkmk-tuning-interactive.py Version: 1.0.0
- `[checkmk-tuning-interactive-v5.py](file:///root/checkmk-tools/script-tools/full/monitoring_diagnostics/checkmk-tuning-interactive-v5.py)` - Wrapper deprecated variant. Use checkmk-tuning-interactive.py Version: 1.0.0
- `[checkmk-tuning-interactive.py](file:///root/checkmk-tools/script-tools/full/monitoring_diagnostics/checkmk-tuning-interactive.py)` - checkmk-tuning-interactive.py Interactive (simple) tuning for Checkmk RAW / OMD (Nagios core). Version: 1.0.0
- `[checkmk_cleanup.py](file:///root/checkmk-tools/script-tools/full/monitoring_diagnostics/checkmk_cleanup.py)` - CheckMK Backup Retention & Cleanup Tool Manages the rotation of CheckMK local backups. Features: - Rename completed b...
- `[debug-monitor.py](file:///root/checkmk-tools/script-tools/full/monitoring_diagnostics/debug-monitor.py)` - debug-monitor.py Python entrypoint that delegates to debug-monitor.sh. Version: 1.0.0
- `[distributed-monitoring-setup.py](file:///root/checkmk-tools/script-tools/full/monitoring_diagnostics/distributed-monitoring-setup.py)` - distributed-monitoring-setup.py Python entrypoint that delegates to distributed-monitoring-setup.sh. Version: 1.0.0
- `[fix_stale_checkmk.py](file:///root/checkmk-tools/script-tools/full/monitoring_diagnostics/fix_stale_checkmk.py)` - Fixes Check_MK* stale services MECHANISM:   1. Enable passive_checks on the Check_MK* service (ENABLE_PASSIVE_SVC_CHE...

#### `script-tools/full/network_scan/` - Network discovery via nmap

- `[README.md](file:///root/checkmk-tools/script-tools/full/network_scan/README.md)` - network_scan
- `[network_scan_to_folder.py](file:///root/checkmk-tools/script-tools/full/network_scan/network_scan_to_folder.py)` - Network scan and CheckMK folder creation Phase 1: Ping sweep subnet → collects active IPs Step 2: Reverse DNS for eac...
- `[scan-nmap-interattivo-verbose-multi-options.py](file:///root/checkmk-tools/script-tools/full/network_scan/scan-nmap-interattivo-verbose-multi-options.py)` - scan-nmap-interattivo-verbose-multi-options.py Python entrypoint that delegates to scan-nmap-interattivo-verbose-mult...
- `[scan-nmap-interattivo-verbose.py](file:///root/checkmk-tools/script-tools/full/network_scan/scan-nmap-interattivo-verbose.py)` - scan-nmap-interattivo-verbose.py Python entrypoint that delegates to scan-nmap-interattivo-verbose.sh. Version: 1.0.0
- `[scan_nmap.py](file:///root/checkmk-tools/script-tools/full/network_scan/scan_nmap.py)` - Interactive Nmap Scanner Interactive wrapper for Nmap. Features: - Target selection (Host/Range/CIDR or File) - Port ...

#### `script-tools/full/sync_update/` - Automated repository synchronization

- `[README.md](file:///root/checkmk-tools/script-tools/full/sync_update/README.md)` - sync_update
- `[auto_git_sync.py](file:///root/checkmk-tools/script-tools/full/sync_update/auto_git_sync.py)` - Periodic git pull loop for /opt/checkmk-tools (or TARGET_DIR env var). Runs forever, sleeping SYNC_INTERVAL seconds b...
- `[cmk-local-discovery-trigger.py](file:///root/checkmk-tools/script-tools/full/sync_update/cmk-local-discovery-trigger.py)` - cmk-local-discovery-trigger.py Detect changes in local check services seen by CheckMK (via `cmk -d HOST`) e launch di...
- `[diagnose-auto-git-sync.py](file:///root/checkmk-tools/script-tools/full/sync_update/diagnose-auto-git-sync.py)` - diagnose-auto-git-sync.py Python entrypoint that delegates to diagnose-auto-git-sync.sh. Version: 1.0.0
- `[install-cmk-local-discovery-trigger.py](file:///root/checkmk-tools/script-tools/full/sync_update/install-cmk-local-discovery-trigger.py)` - install-cmk-local-discovery-trigger.py Systemd installer for cmk-local-discovery-trigger.py with production guardrail...
- `[sync-python-full-checks.py](file:///root/checkmk-tools/script-tools/full/sync_update/sync-python-full-checks.py)` - Synchronize and deploy Python local checks Copy Python checks from script-check-*/full/*.py to /usr/lib/check_mk_agen...
- `[update-all-scripts.py](file:///root/checkmk-tools/script-tools/full/sync_update/update-all-scripts.py)` - update-all-scripts.py Python entrypoint that delegates to update-all-scripts.sh. Version: 1.0.0
- `[update-crontab-frequency.py](file:///root/checkmk-tools/script-tools/full/sync_update/update-crontab-frequency.py)` - update-crontab-frequency.py Python entrypoint that delegates to update-crontab-frequency.sh. Version: 1.0.0
- `[update-deployed-launchers.sh](file:///root/checkmk-tools/script-tools/full/sync_update/update-deployed-launchers.sh)` - Updates remote launchers deployed on the server Sincronizza r*.sh dal repository alle destinazioni Find all launchers...
- `[update-scripts-from-repo.py](file:///root/checkmk-tools/script-tools/full/sync_update/update-scripts-from-repo.py)` - update-scripts-from-repo.py Python entrypoint that delegates to update-scripts-from-repo.sh. Version: 1.0.0
- `[update_cron_freq.py](file:///root/checkmk-tools/script-tools/full/sync_update/update_cron_freq.py)` - Update Cron Job Frequency Interactive script to change the execution frequency of specific jobs in the crontab. Targe...
- `[update_deployed_launchers.py](file:///root/checkmk-tools/script-tools/full/sync_update/update_deployed_launchers.py)` - Updates launchers deployed from the repository. Version: 1.0.0
- `[update_scripts.py](file:///root/checkmk-tools/script-tools/full/sync_update/update_scripts.py)` - Update CheckMK Scripts from Repo Update the scripts installed on the system by copying them from the local repository...

#### `script-tools/full/upgrade_maintenance/` - CheckMK agent upgrade and performance tuning

- `[README.md](file:///root/checkmk-tools/script-tools/full/upgrade_maintenance/README.md)` - upgrade_maintenance
- `[checkmk-optimize.sh](file:///root/checkmk-tools/script-tools/full/upgrade_maintenance/checkmk-optimize.sh)` - checkmk-optimize.sh "Balanced" optimizations for Checkmk hosts (Ubuntu/Debian). Simple output (ASCII-only), with back...
- `[checkmk_optimize.py](file:///root/checkmk-tools/script-tools/full/upgrade_maintenance/checkmk_optimize.py)` - CheckMK Host Optimization Tool Balanced optimizations for CheckMK hosts (Debian/Ubuntu). Features: - Timeshift snapsh...
- `[persistent-startup-check.py](file:///root/checkmk-tools/script-tools/full/upgrade_maintenance/persistent-startup-check.py)` - PERSISTENT Startup Verification Automatically checks and restores critical CheckMK services after a major upgrade of ...
- `[pre-upgrade-nsec8.py](file:///root/checkmk-tools/script-tools/full/upgrade_maintenance/pre-upgrade-nsec8.py)` - pre-upgrade-nsec8.py Python entrypoint that delegates to pre-upgrade-nsec8.sh. Version: 1.0.0
- `[setup-auto-updates.sh](file:///root/checkmk-tools/script-tools/full/upgrade_maintenance/setup-auto-updates.sh)` - ############################################################################## Script: setup-auto-updates.sh Descript...
- `[setup-auto-upgrade-checkmk.py](file:///root/checkmk-tools/script-tools/full/upgrade_maintenance/setup-auto-upgrade-checkmk.py)` - setup-auto-upgrade-checkmk.py Configure cron auto-upgrade using upgrade-checkmk.py (not shell). Version: 1.1.0
- `[setup_auto_updates.py](file:///root/checkmk-tools/script-tools/full/upgrade_maintenance/setup_auto_updates.py)` - Setup System Auto-Updates Configure automatic system updates (apt update/upgrade) via cronjob. Features: - Interactiv...
- `[setup_checkmk_upgrade.py](file:///root/checkmk-tools/script-tools/full/upgrade_maintenance/setup_checkmk_upgrade.py)` - Setup CheckMK Auto-Upgrade Configure Cron jobs to automatically update CheckMK RAW Edition. Features: - Interactive m...
- `[startup_check.py](file:///root/checkmk-tools/script-tools/full/upgrade_maintenance/startup_check.py)` - Rocksolid Startup Check & Remediation Check and restore critical services at startup. Features: - Restore critical bi...
- `[sync-checks.py](file:///root/checkmk-tools/script-tools/full/upgrade_maintenance/sync-checks.py)` - Lightweight download of check scripts from GitHub. Replaces git clone/pull: only downloads the 13 necessary .py files...
- `[update_checkmk_agent.py](file:///root/checkmk-tools/script-tools/full/upgrade_maintenance/update_checkmk_agent.py)` - Automatically update CheckMK Agent Check if the local agent is aligned with the CheckMK server version. If the server...
- `[upgrade-checkmk.py](file:///root/checkmk-tools/script-tools/full/upgrade_maintenance/upgrade-checkmk.py)` - upgrade-checkmk.py Python wrapper for upgrade-checkmk.sh with outcome management for automations/emails: - No updates...
- `[upgrade_checkmk.py](file:///root/checkmk-tools/script-tools/full/upgrade_maintenance/upgrade_checkmk.py)` - CheckMK Upgrade Automation Automates the CheckMK update process (CRE/Community Edition). Features: - Current and late...

#### `script-tools/full/wrappers_templates/` - Script templates and wrappers

- `[README.md](file:///root/checkmk-tools/script-tools/full/wrappers_templates/README.md)` - wrappers_templates
- `[smart-wrapper-example.py](file:///root/checkmk-tools/script-tools/full/wrappers_templates/smart-wrapper-example.py)` - smart-wrapper-example.py Python entrypoint that delegates to smart-wrapper-example.sh. Version: 1.0.0
- `[smart-wrapper-template.py](file:///root/checkmk-tools/script-tools/full/wrappers_templates/smart-wrapper-template.py)` - smart-wrapper-template.py Python entrypoint that delegates to smart-wrapper-template.sh. Version: 1.0.0

---

## Deployment Methods

### Method 1: From GitHub (Direct execution)

```bash
# Download and run agent installer directly
curl -fsSL https://raw.githubusercontent.com/nethesis/checkmk-tools/main/script-tools/full/installation/install-checkmk-agent-linux.py | python3
```

### Method 2: From Local Repository (Preferred)

```bash
# Direct execution from local repo
python3 /opt/checkmk-tools/script-tools/full/installation/install-checkmk-agent-linux.py

# Git pull first (auto-pull runs periodically)
cd /opt/checkmk-tools && git pull
```

---

## Installation Guide

### Platform-Specific Installation

#### NethServer 7 / 8
Deploy the corresponding python check scripts from the repository to local directory:
```bash
cp /opt/checkmk-tools/script-check-ns8/full/check_ns8_services.py /usr/lib/check_mk_agent/local/check_ns8_services
chmod +x /usr/lib/check_mk_agent/local/check_ns8_services
```

#### NethSecurity 8 (Official packages only)
```bash
wget https://updates.nethsecurity.nethserver.org/checkmk_agent/*/packages/x86_64/nethsecurity/checkmk-agent_*.ipk
opkg install checkmk-agent_*.ipk
```

---

## Testing & Validation

### Syntax Validation
Validate Python syntax:
```bash
python3 -m py_compile script.py
```

Validate PowerShell syntax:
```powershell
powershell -Command "[System.Management.Automation.PSParser]::Tokenize((Get-Content 'script.ps1' -Raw), [ref]$null)"
```

### Repository Integrity Check
```powershell
powershell.exe -File .\script-ps-tools\check-integrity.ps1
```

---

## Key Features

- **ROCKSOLID Mode**: Upgrade-resistant persistent agent setup on NethSecurity 8 (`script-tools/full/installation/setup-persistent-nsec8.py`).
- **Smart Deploy**: Batch agent deployment for multi-host environments (`script-tools/full/deploy/smart-deploy-hybrid.py`).
- **Auto Git Sync**: Automatic repository updates and scheduling (`script-tools/full/sync_update/auto_git_sync.py`).
- **Cloud Backup Integration**: automated rclone upload to S3/Spaces (`script-tools/full/backup_restore/checkmk_rclone_space_dyn.py`).
- **Ydea Integration**: Alert and ticketing system bridge (`Ydea-Toolkit/full/ydea_monitoring_integration.py`).

---

## Troubleshooting

Check agent socket status:
```bash
systemctl status check-mk-agent.socket
```

Test agent output:
```bash
check_mk_agent | head -30
```

---

## Quick Reference

### File Locations

| Component | Path | Platform |
|-----------|------|----------|
| CheckMK Agent | `/usr/sbin/check_mk_agent` | Linux |
| Local Checks | `/usr/lib/check_mk_agent/local/` | Linux |
| Repository | `/opt/checkmk-tools/` | Linux |
| Logs | `/var/log/checkmk-*` | Linux |

---

**Last Updated**: June 15, 2026
**Maintainer**: Nethesis
**License**: GPL-2.0
