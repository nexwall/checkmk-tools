# CheckMK Tools Repository Index

Organized repository for CheckMK management, Ydea integration, and monitoring scripts.

## Directory structure

### **script-tools/** - Core tools
Script for CheckMK management, deployment and maintenance.

- **`full/`** - Complete standalone scripts
  - Automatic Git sync via systemd timer (`install-checkmk-agent-linux.py` — Python-first orchestration)
  - Update & upgrade (`update-all-scripts.sh`, `upgrade-checkmk.sh`)
  - Deployment agents (`deploy-plain-agent.sh`, `smart-deploy-hybrid.sh`)
  - Installation FRPC (`install-frpc.sh`, `install-frpc2.sh`)
  - CheckMK tuning (v3, v4, v5)
  - Network tools (nmap scan)

### **Ydea-Toolkit/** - Ydea integration
Complete integration with Ydea ticketing system.

- **`full/`** - Complete Ydea scripts
  - Complete Toolkit (`ydea-toolkit.sh`)
  - Monitoring integration (`ydea-monitoring-integration.sh`)
  - Health & ticket monitor
  - Templates and utilities

### **script-notify-checkmk/** - CheckMK notifications
Advanced notification scripts for CheckMK.

- **`full/`** - Complete notification scripts
  - `ydea_realip` - Create automatic tickets on Ydea
  - `mail_realip` - Email with real IP resolution
  - `telegram_realip` - Telegram notifications
  - Documentation (TESTING_GUIDE, CHANGELOG, FIX guides)

### **nethesis-brand/** - Nethesis branding for CheckMK

Assets and script for the rebranding of the CheckMK interface with Nethesis visual identity.

- `checkmk_logo.svg` — Login page logo (290px, white background, green border `#3ecf8e`)
- `icon_checkmk_logo.svg` — N icon for sidebar (40×40px, rounded corners)
- `icon_checkmk_logo_min.svg` — Minimal N icon (28×28px)
- `nethesis_color.png` — Color wordmark logo (source downloaded from nethesis.it)
- `nethesis_n_icon.png` — Favicon N (source)
- `theme.css` — CSS override: `#0369a1` / `#1a425c` colors, gradient login background

**Deployment script**: `deploy-nethesis-brand.sh` (root repo)
- Usage: `bash deploy-nethesis-brand.sh` (all servers) or `bash deploy-nethesis-brand.sh <host>`
- Configured target servers: `checkmk-vps-01`, `checkmk-vps-02`, `srv-monitoring-sp`, `srv-monitoring-us`

### **Fix/** - Fix and troubleshooting script
Troubleshooting CheckMK and components.

- **`full/`** - Complete script fixes
  - CheckMK fixes (`force-update-checkmk.sh`, `fix-frp-checkmk-host.sh`)
  - Windows fixes (PowerShell scripts)
  - Ransomware protection fixes
  - Git credentials fixes

### **script-check-{ns7,ns8,ubuntu,windows}/** - Check script
Monitoring script for different platforms.

- **`polling/`** - Check with active polling
- **`nopolling/`** - Passive/on-demand checks

### **Proxmox/** - Proxmox script
Monitoring and management Proxmox VE.

- **`polling/`** - Check with polling
- **`nopolling/`** - Passive checks

### **Install/** - Installer and bootstrap
Installation script and bootstrap.

- **`checkmk-installer/`** - CheckMK Installer
- **`Agent-FRPC/`** - Agent + FRPC installer
- **`install-cmk8/`** - CheckMK v8 installer
- `bootstrap-installer.sh`, `make-bootstrap-iso.sh`

### **test script/** - Test script
Script for testing and validation.

### **deploy script/** - Deployment script
Script for automatic deployment.

---

## Quick Start

### Using Full Scripts (Recommended)

```bash
# Run full script directly from GitHub
curl -fsSL https://raw.githubusercontent.com/nethesis/checkmk-tools/main/script-tools/full/installation/install-auto-git-sync.sh | bash
```

### I use Local Scripts

```bash
# Clone repository
git clone https://github.com/nethesis/checkmk-tools.git
cd checkmk-tools

# Run complete script
chmod +x script-tools/full/installation/install-auto-git-sync.sh
sudo ./script-tools/full/installation/install-auto-git-sync.sh
```

---

## Conventions

### File Nomenclature
- **`{name}.sh`** - Complete script (in the `full/` folder)

### Structure note
The `remote/` directories have been removed: the repository only uses full scripts in `full/` and documentation in `doc/`.

---

## Useful Links

- **GitHub**: https://github.com/nethesis/checkmk-tools
- **GitLab**: https://gitlab.com/nethesis/checkmk-tools
- **CheckMK documentation**: https://docs.checkmk.com/

---

## Documentation file

- `README.md` - Main readme
- `DOCUMENTATION_INDEX.md` - Documentation index
- `PROJECT_STATUS.md` - Project status
- `SESSION_COMPLETE.md` - Complete sessions
- `COMPLETION_SUMMARY.md` - Completion summary
- Various `*_SUMMARY.md`, `*_CHANGELOG.md` - Specific documents

---

## Windows Automations (PowerShell)

PowerShell Script for Windows Automation:
- `backup-sync-complete.ps1` - Full backup and sync
- `setup-automation.ps1` - Automation setup
- `setup-backup-automation.ps1` - Auto backup setup
- `quick-backup.ps1` - Quick backup
- Various script fixes (`fix-*.ps1`)

---

**Maintainer**: Nethesis  
**License**: MIT (unless otherwise specified)