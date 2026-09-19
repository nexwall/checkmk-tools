# CheckMK Tools Repository - Complete Contexts Index

## Repository Overview
This repository contains tools, scripts, and documentation for CheckMK monitoring system integration, deployment automation, and distributed monitoring setup.

---

## 📁 Main Directories

### `/script-check-ns7/`
Local check scripts for NethServer 7 monitoring (CentOS 7 based).

### `/script-check-ns8/`
Local check scripts for NethServer 8 (modular architecture, Podman/container based).

### `/script-check-nsec8/`
Monitoring scripts for NethSecurity 8 firewall/gateway (OpenWrt based).

### `/script-check-ubuntu/`
General Linux/Ubuntu monitoring scripts.

### `/script-check-proxmox/`
Monitoring scripts for Proxmox Virtual Environment via API.

### `/script-check-tmate-server/`
Monitoring scripts for tmate terminal sharing server.

### `/script-checkmk/`
CheckMK server-side scripts and connectivity checks.

### `/script-notify-checkmk/`
Custom CheckMK notification scripts (Ydea ticketing, Telegram, Email with Real IP resolution).

### `/Ydea-Toolkit/`
Complete integration and utility scripts for Ydea ticketing system.

### `/script-ps-tools/`
PowerShell scripts for Windows automation, backups, and integrity verification.

### `/script-tools/`
Utility scripts for automation, backup, sync, upgrade and maintenance.

---

## 📄 Key Documentation Files

- `README.md` - Main readme with project description
- `INDEX.md` - Complete scripts index with links and descriptions
- `REPOSITORY_INDEX.md` - File system layout and repository index
- `CONTEXTS_INDEX.md` - Context mapping index
- `MACHINE_ACCESS_GUIDE.md` - System access and FRP configuration guide

## 📊 Contexts Summary

| Context | Type | Purpose |
|---------|------|---------|
| Distributed Monitoring | Setup Guide | Configure multi-site monitoring architecture |
| YDEA Integration | Integration | Integrate YDEA toolkit with CheckMK |
| FRP Connectivity | Network | Configure FRP tunnel connectivity |
| Notifications | Deployment | Enhanced notification system setup |
| Auto Git Sync | Automation | Automated Git synchronization |
| Host Labels | Configuration | Configure CheckMK host labels |
| Launcher System | Automation | Main deployment launcher scripts |
| Windows Integration | Windows | Windows-specific tools and checks |
| Ubuntu Integration | Linux | Ubuntu-specific tools and checks |
| Proxmox Integration | Hypervisor | Proxmox monitoring integration |

---

## 🚀 Quick Start

1. **Review README.md** - Understand the project structure
2. **Check INDEX.md** - Find the right monitoring script for your platform
3. **Deploy script** - Copy the python scripts from `script-check-*/full/` without `.py` extension to agent local directory
