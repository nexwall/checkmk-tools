from __future__ import annotations

from pathlib import Path

from lib.common import backup_file, command_exists, log_header, log_info, log_success, run as run_cmd
from lib.config import InstallerConfig


def run_step(cfg: InstallerConfig) -> None:
    log_header("15-NTP")
    log_info("Configuring timezone and NTP (chrony)...")

    run_cmd(["apt-get", "update"])
    run_cmd(["apt-get", "install", "-y", "chrony"])

    if command_exists("timedatectl") and cfg.timezone:
        run_cmd(["timedatectl", "set-timezone", cfg.timezone], check=False)

    chrony_conf = Path("/etc/chrony/chrony.conf")
    if chrony_conf.exists() and cfg.ntp_servers:
        backup = backup_file(chrony_conf)
        log_info(f"Backup created: {backup}")
        current = chrony_conf.read_text(encoding="utf-8", errors="replace")
        appended = ["\n# Added by checkmk Python installer\n"]
        for server in cfg.ntp_servers:
            appended.append(f"server {server} iburst\n")
        chrony_conf.write_text(current + "".join(appended), encoding="utf-8")

    if command_exists("systemctl"):
        run_cmd(["systemctl", "enable", "chrony"], check=False)
        run_cmd(["systemctl", "restart", "chrony"], check=False)
    if command_exists("chronyc"):
        run_cmd(["chronyc", "makestep"], check=False)

    log_success("NTP configured")


def run(cfg: InstallerConfig) -> None:
    run_step(cfg)
