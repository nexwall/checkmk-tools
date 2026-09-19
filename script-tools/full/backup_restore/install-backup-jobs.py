#!/usr/bin/env python3
"""install-backup-jobs.py - Install systemd timers for automatic CheckMK backups

- job00: Compressed daily (1.2MB), retention 90, 03:00
- job01: Normal weekly (362MB), retention 5, Sunday 04:00

Usage: python3 install-backup-jobs.py

Version: 1.1.0"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "1.1.0"

SCRIPT_DIR = Path(__file__).parent.resolve()
SYSTEMD_SRC = SCRIPT_DIR / "systemd"
SYSTEMD_DEST = Path("/etc/systemd/system")

UNITS = {
    "job00": {
        "service": "checkmk-backup-job00.service",
        "timer":   "checkmk-backup-job00.timer",
    },
    "job01": {
        "service": "checkmk-backup-job01.service",
        "timer":   "checkmk-backup-job01.timer",
    },
}


def check_root() -> None:
    if os.geteuid() != 0:
        print(" This script must be run as root")
        sys.exit(1)


def ask_mode() -> str:
    print()
    print("Select schedule mode:")
    print("  1)  TEST MODE - Every minute (for immediate testing)")
    print("  2)  PRODUCTION MODE - job00 daily 03:00, job01 Sunday 04:00")
    print()
    choice = input("Enter choice [1-2]: ").strip()
    if choice == "1":
        print(" TEST MODE selected - timers will run every minute")
        return "test"
    else:
        print(" PRODUCTION MODE selected - standard schedule")
        return "production"


def patch_timer_test(content: str) -> str:
    """Patchs timer to run every minute."""
    content = re.sub(r"^OnCalendar=.*$", "OnCalendar=*-*-* *:*:00", content, flags=re.MULTILINE)
    content = re.sub(r"^RandomizedDelaySec=.*$", "#RandomizedDelaySec=", content, flags=re.MULTILINE)
    return content


def install_unit(name: str, src: Path, mode: str) -> None:
    dest = SYSTEMD_DEST / name
    content = src.read_text()

    if mode == "test" and name.endswith(".timer"):
        content = patch_timer_test(content)

    dest.write_text(content)
    print(f"   {name} → {dest}")


def run(cmd: list) -> None:
    subprocess.run(cmd, check=True)


def show_status() -> None:
    print()
    print("=" * 44)
    print("Installation Status")
    print("=" * 44)
    for job, units in UNITS.items():
        timer = units["timer"]
        print(f"\n{timer}:")
        subprocess.run(["systemctl", "status", timer, "--no-pager", "-l"], check=False)
        print("\nNext run:")
        subprocess.run(["systemctl", "list-timers", timer, "--no-pager"], check=False)
        print()


def main() -> int:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print(f"install-backup-jobs.py v{VERSION}")
        print(__doc__)
        return 0

    print("=" * 44)
    print("CheckMK Backup Jobs Installation")
    print("=" * 44)

    check_root()

    mode = ask_mode()
    print()

    # Install units systemd
    print("  Installing systemd units...")
    for job, units in UNITS.items():
        for unit_name in (units["service"], units["timer"]):
            src = SYSTEMD_SRC / unit_name
            if not src.exists():
                print(f"   Source not found: {src}", file=sys.stderr)
                return 1
            install_unit(unit_name, src, mode)

    # Reload systemd
    print("\n Reloading systemd daemon...")
    run(["systemctl", "daemon-reload"])
    print(" Systemd reloaded")

    # Enable and start timers
    print("\n Enabling and starting timers...")
    for job, units in UNITS.items():
        timer = units["timer"]
        run(["systemctl", "enable", timer])
        run(["systemctl", "start", timer])
        print(f"   {timer} enabled and started")

    show_status()

    print("=" * 44)
    print(" Installation Completed Successfully")
    print("=" * 44)
    print()
    print("Logs:")
    print("  - Job00: tail -f /var/log/checkmk-backup-job00.log")
    print("  - Job01: tail -f /var/log/checkmk-backup-job01.log")
    print()
    print("Manual run:")
    print("  - Job00: systemctl start checkmk-backup-job00.service")
    print("  - Job01: systemctl start checkmk-backup-job01.service")
    print("=" * 44)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
