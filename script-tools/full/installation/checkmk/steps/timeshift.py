from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lib.common import command_exists, log_header, log_info, log_success, log_warn, run as run_cmd
from lib.config import InstallerConfig

# Minimum free space required on the partition (GB)
_MIN_FREE_GB = 5


def _root_device_info() -> tuple[str, float] | None:
    """Returns (device, avail_gb) of the root filesystem, or None if undetectable."""
    try:
        out = subprocess.run(
            ["df", "--output=source,avail", "/"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        lines = out.stdout.strip().splitlines()
        if len(lines) < 2:
            return None
        parts = lines[1].split()
        device = parts[0]
        avail_gb = int(parts[1]) / (1024 * 1024)
        return device, avail_gb
    except Exception:
        return None


def _device_uuid(device: str) -> str | None:
    """Reads the device UUID via blkid."""
    try:
        out = subprocess.run(
            ["blkid", "-s", "UUID", "-o", "value", device],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        uuid = out.stdout.strip()
        return uuid if uuid else None
    except Exception:
        return None


def _write_timeshift_config(uuid: str) -> None:
    """Scrive /etc/timeshift/timeshift.json puntando al device corretto."""
    conf_dir = Path("/etc/timeshift")
    conf_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "backup_device_uuid": uuid,
        "do_first_run": "false",
        "backup_levels": ["D"],
        "schedule_monthly": "false",
        "schedule_weekly": "false",
        "schedule_daily": "false",
        "schedule_hourly": "false",
        "schedule_boot": "false",
        "count_monthly": "2",
        "count_weekly": "3",
        "count_daily": "5",
        "count_hourly": "6",
        "count_boot": "5",
        "snapshot_type": "RSYNC",
        "exclude": ["/root/**", "/home/**/.cache/**"],
    }
    conf_file = conf_dir / "timeshift.json"
    conf_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
    log_info(f"Timeshift configurato: device UUID {uuid} → {conf_file}")


def run_step(_: InstallerConfig) -> None:
    log_header("80-TIMESHIFT")
    log_info("Installing Timeshift...")

    if command_exists("add-apt-repository"):
        run_cmd(["add-apt-repository", "-y", "ppa:teejee2008/timeshift"], check=False)
    run_cmd(["apt-get", "update"])
    run_cmd(["apt-get", "install", "-y", "timeshift"], check=False)

    if not command_exists("timeshift"):
        log_warn("Timeshift non trovato dopo installazione. Skip.")
        log_success("Timeshift step completed")
        return

    # Find the root device and check available space
    info = _root_device_info()
    if info is None:
        log_warn("Impossibile determinare il device root. Skip snapshot.")
        log_success("Timeshift step completed")
        return

    device, avail_gb = info
    log_info(f"Root device: {device} — spazio libero: {avail_gb:.1f} GB")

    if avail_gb < _MIN_FREE_GB:
        log_warn(f"Spazio insufficiente ({avail_gb:.1f} GB < {_MIN_FREE_GB} GB minimi). Skip snapshot.")
        log_success("Timeshift step completed")
        return

    # Configure Timeshift to use the root device (not /boot)
    uuid = _device_uuid(device)
    if uuid:
        _write_timeshift_config(uuid)
    else:
        log_warn(f"UUID non trovato per {device}. Timeshift potrebbe scegliere il device sbagliato.")

    run_cmd(
        ["timeshift", "--create", "--comments", "Initial snapshot after CheckMK installation", "--tags", "D"],
        check=False,
    )
    log_success("Timeshift step completed")


def run(cfg: InstallerConfig) -> None:
    run_step(cfg)
