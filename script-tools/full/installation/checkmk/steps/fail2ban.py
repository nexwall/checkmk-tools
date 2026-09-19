from __future__ import annotations

from pathlib import Path

from lib.common import backup_file, command_exists, log_header, log_info, log_success, run as run_cmd
from lib.config import InstallerConfig

# IP always whitelisted (never banned)
_ALWAYS_IGNORE = ["127.0.0.1/8", "::1"]


def run_step(cfg: InstallerConfig) -> None:
    log_header("40-FAIL2BAN")
    log_info("Installing and configuring Fail2Ban...")
    run_cmd(["apt-get", "install", "-y", "fail2ban"])

    jail_local = Path("/etc/fail2ban/jail.local")
    if jail_local.exists():
        backup = backup_file(jail_local)
        log_info(f"Backup created: {backup}")

    # Constructs ignoreip by merging the fixed IPs with those from the config
    extra_ips = [ip.strip() for ip in cfg.fail2ban_ignoreip.split() if ip.strip()]
    all_ips = " ".join(dict.fromkeys(_ALWAYS_IGNORE + extra_ips))  # deduplica, mantiene ordine
    if extra_ips:
        log_info(f"Whitelist IP fail2ban: {all_ips}")

    jail_local.write_text(
        "\n".join(
            [
                "[DEFAULT]",
                f"ignoreip = {all_ips}",
                "bantime = 3600",
                "findtime = 600",
                "maxretry = 5",
                "",
                "[sshd]",
                "enabled = true",
                f"port = {cfg.ssh_port}",
                "logpath = /var/log/auth.log",
                "",
            ]
        ),
        encoding="utf-8",
    )

    # Validate configuration before rebooting — crash if jail.local is corrupt
    run_cmd(["fail2ban-client", "-t"])

    if command_exists("systemctl"):
        run_cmd(["systemctl", "enable", "fail2ban"], check=False)
        run_cmd(["systemctl", "restart", "fail2ban"], check=False)
    log_success("Fail2Ban configured")


def run(cfg: InstallerConfig) -> None:
    run_step(cfg)
