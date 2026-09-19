from __future__ import annotations

from lib.common import log_header, log_info, log_success, run as run_cmd
from lib.config import InstallerConfig


def run_step(_: InstallerConfig) -> None:
    log_header("20-PACKAGES")
    log_info("Installing base packages...")
    run_cmd(["apt-get", "update"])
    run_cmd(
        [
            "apt-get",
            "install",
            "-y",
            "curl",
            "wget",
            "git",
            "python3",
            "python3-pip",
            "vim",
            "htop",
            "net-tools",
            "dnsutils",
            "apt-transport-https",
            "ca-certificates",
            "gnupg",
            "lsb-release",
            "software-properties-common",
            "unattended-upgrades",
        ]
    )
    log_success("Packages installed")


def run(cfg: InstallerConfig) -> None:
    run_step(cfg)
