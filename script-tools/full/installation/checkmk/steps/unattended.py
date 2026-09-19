from __future__ import annotations

from pathlib import Path

from lib.common import backup_file, log_header, log_info, log_success, run as run_cmd, run_capture
from lib.config import InstallerConfig


def run_step(_: InstallerConfig) -> None:
    log_header("21-UNATTENDED-UPGRADES")
    log_info("Configuring unattended-upgrades (security updates)...")

    run_cmd(["apt-get", "install", "-y", "unattended-upgrades"])

    distro_id = run_capture(["bash", "-lc", ". /etc/os-release; echo ${ID:-Ubuntu}"], check=False) or "Ubuntu"
    codename = run_capture(["lsb_release", "-cs"], check=False) or "jammy"

    config_50 = Path("/etc/apt/apt.conf.d/50unattended-upgrades")
    if config_50.exists():
        backup_file(config_50)

    config_50.write_text(
        "\n".join(
            [
                "Unattended-Upgrade::Allowed-Origins {",
                f"    \"{distro_id}:{codename}-security\";",
                f"    \"{distro_id}ESMApps:{codename}-apps-security\";",
                f"    \"{distro_id}ESM:{codename}-infra-security\";",
                "};",
                'Unattended-Upgrade::AutoFixInterruptedDpkg "true";',
                'Unattended-Upgrade::MinimalSteps "true";',
                'Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";',
                'Unattended-Upgrade::Remove-Unused-Dependencies "true";',
                'Unattended-Upgrade::Automatic-Reboot "false";',
                'Unattended-Upgrade::Automatic-Reboot-Time "03:00";',
                "",
            ]
        ),
        encoding="utf-8",
    )

    config_20 = Path("/etc/apt/apt.conf.d/20auto-upgrades")
    if config_20.exists():
        backup_file(config_20)
    config_20.write_text(
        "\n".join(
            [
                'APT::Periodic::Update-Package-Lists "1";',
                'APT::Periodic::Download-Upgradeable-Packages "1";',
                'APT::Periodic::AutocleanInterval "7";',
                'APT::Periodic::Unattended-Upgrade "1";',
                "",
            ]
        ),
        encoding="utf-8",
    )

    log_success("unattended-upgrades configured")


def run(cfg: InstallerConfig) -> None:
    run_step(cfg)
