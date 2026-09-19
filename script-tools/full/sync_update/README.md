# sync_update

Repository synchronization and script/config update utilities.

## Auto-Git-Sync (Timer-Based Model)

The auto-git-sync system keeps `/opt/checkmk-tools/` synchronized with the upstream repository using a Python-managed, systemd timer-based architecture.

### Architecture

**Python-First Design:**
- Installer and orchestration logic is implemented in `../installation/install-checkmk-agent-linux.py`
- Configuration and scheduling are managed by Python code
- Minimal Bash wrapper is generated at installation time for systemd integration

**Runtime Model:**
- **Systemd Timer:** `auto-git-sync.timer` (configurable interval, default 30 seconds)
- **Oneshot Service:** `auto-git-sync.service` (Type=oneshot, triggered by timer)
- **Minimal Wrapper:** `/usr/local/bin/checkmk-git-sync.sh` (generated, not maintained in repo)
- **Fallback Cron:** On systems without systemd, sync runs every minute via crontab

### Sync Operation

Each sync cycle:
1. `git fetch origin main` — Fetch latest commits from upstream
2. `git fetch --tags origin` — Update release tags for traceability
3. `git reset --hard origin/main` — Reset working tree to upstream state
4. `git clean -fd` — Remove untracked files (safe on deploy clone)
5. Log status to `/var/log/auto-git-sync.log`

### Installation

```bash
# Install with systemd timer (default interval 30 seconds)
python3 ../installation/install-checkmk-agent-linux.py --git-interval 30

# Or with custom interval (5 minutes)
python3 ../installation/install-checkmk-agent-linux.py --git-interval 300
```

### Status and Logging

```bash
# Check timer and service status
systemctl status auto-git-sync.timer
systemctl status auto-git-sync.service

# View recent logs
tail -f /var/log/auto-git-sync.log
journalctl -u auto-git-sync.service -f

# Trigger immediate sync
systemctl start auto-git-sync.service

# List next scheduled runs
systemctl list-timers auto-git-sync.timer
```

### Cron Fallback (OpenWrt / No Systemd)

On systems without systemd, the installer automatically configures crontab:

```cron
* * * * * cd /opt/checkmk-tools && git fetch origin main && git fetch --tags origin && git reset --hard origin/main && git clean -fd >> /var/log/auto-git-sync.log 2>&1
```

### Design Rationale

- **Python Orchestration:** All orchestration, configuration, and logic is Python-based (Python-first policy)
- **Minimal Bash Wrapper:** The actual sync command is kept minimal for systemd integration, not as a maintained script
- **Systemd Timer:** Leverages standard systemd timers for reliability and easy interval adjustment
- **Stateless Design:** Each sync is independent; no long-running daemon process
- **Read-Only Deploy Clone:** The deploy clone `/opt/checkmk-tools/` is reset hard on every sync; safe for production use