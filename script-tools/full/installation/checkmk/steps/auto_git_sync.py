from __future__ import annotations

from pathlib import Path

from lib.common import backup_file, command_exists, log_header, log_info, log_success, log_warn, run as run_cmd
from lib.config import InstallerConfig


SERVICE_NAME = "auto-git-sync.service"
SERVICE_PATH = Path("/etc/systemd/system") / SERVICE_NAME
INSTALL_SCRIPT_PATH = Path("/usr/local/bin/auto-git-sync.py")


def _find_repo_root() -> Path | None:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "script-tools" / "full").exists():
            return parent
    return None


def _write_service_file(cfg: InstallerConfig) -> None:
    interval = max(5, int(cfg.auto_git_sync_interval_sec))
    repo_url = cfg.auto_git_sync_repo_url.strip() or "https://github.com/nethesis/checkmk-tools.git"
    target_dir = cfg.auto_git_sync_target_dir.strip() or "/opt/checkmk-tools"

    content = f"""[Unit]
Description=Auto Git Sync Service
Documentation=https://github.com/nethesis/checkmk-tools
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=REPO_URL={repo_url}
Environment=TARGET_DIR={target_dir}
Environment=SYNC_INTERVAL={interval}
ExecStart=/usr/bin/python3 {INSTALL_SCRIPT_PATH} {interval}
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=auto-git-sync
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target"""

    if SERVICE_PATH.exists():
        backup_file(SERVICE_PATH)
    SERVICE_PATH.write_text(content, encoding="utf-8")


def run_step(cfg: InstallerConfig) -> None:
    log_header("65-AUTO-GIT-SYNC")

    if not cfg.enable_auto_git_sync:
        log_info("ENABLE_AUTO_GIT_SYNC=false: skipping")
        return

    if not command_exists("systemctl"):
        log_warn("systemctl not found: cannot install auto-git-sync.service")
        return

    repo_root = _find_repo_root()
    if repo_root is None:
        log_warn("Repository root not found (script-tools/full missing). Skipping auto git sync setup.")
        return

    source_script = repo_root / "script-tools" / "full" / "sync_update" / "auto_git_sync.py"
    if not source_script.exists():
        log_warn(f"auto_git_sync.py not found at: {source_script}. Skipping.")
        return

    log_info(f"Installing auto git sync script to {INSTALL_SCRIPT_PATH} ...")
    INSTALL_SCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    INSTALL_SCRIPT_PATH.write_text(source_script.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    run_cmd(["chmod", "+x", str(INSTALL_SCRIPT_PATH)])

    log_info(f"Writing systemd unit: {SERVICE_PATH} ...")
    _write_service_file(cfg)

    log_info("Enabling and starting auto-git-sync.service ...")
    run_cmd(["systemctl", "daemon-reload"])
    run_cmd(["systemctl", "enable", "--now", SERVICE_NAME])
    run_cmd(["systemctl", "restart", SERVICE_NAME], check=False)

    log_success("Auto git sync enabled")


def run(cfg: InstallerConfig) -> None:
    run_step(cfg)
