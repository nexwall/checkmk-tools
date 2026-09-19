#!/usr/bin/env python3
"""checkmk_restore_compressed.py

Script to restore compressed CheckMK backups.
Version: 1.0.0"""

import argparse
import datetime as dt
import shutil
import socket
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0"


def log(message: str) -> None:
    print(f"[{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def fail(message: str, code: int = 1) -> None:
    print(f"[{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]  ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ripristino backup CheckMK compressi")
    parser.add_argument("backup_file", help="Path al backup .tar.gz")
    parser.add_argument("site_name", nargs="?", default="", help="Nome site (opzionale)")
    return parser.parse_args()


def detect_site_name(backup_file: Path) -> str:
    listing = run(["tar", "tzf", str(backup_file)], check=False)
    if listing.returncode != 0 or not listing.stdout.strip():
        return ""
    first_line = listing.stdout.splitlines()[0].strip()
    return first_line.split("/", 1)[0] if first_line else ""


def ensure_required_dirs(site_dir: Path) -> None:
    required = [
        site_dir / "var/nagios",
        site_dir / "var/nagios/rrd",
        site_dir / "var/log/apache",
        site_dir / "var/log/nagios",
        site_dir / "var/log/agent-receiver",
        site_dir / "var/check_mk/crashes",
        site_dir / "var/check_mk/inventory_archive",
        site_dir / "var/check_mk/logwatch",
        site_dir / "var/check_mk/wato/snapshots",
        site_dir / "var/tmp",
        site_dir / "tmp",
    ]

    for directory in required:
        if not directory.is_dir():
            log(f"  Creating: {directory}")
            directory.mkdir(parents=True, exist_ok=True)


def chown_recursive(site_name: str, path: Path) -> None:
    run(["chown", "-R", f"{site_name}:{site_name}", str(path)], check=False)


def chmod_path(mode: str, path: Path) -> None:
    run(["chmod", mode, str(path)], check=False)


def main() -> int:
    args = parse_args()
    if shutil.which("omd") is None:
        fail("Missing command: omd")

    backup_file = Path(args.backup_file)
    site_name = args.site_name.strip()

    if not backup_file.is_file():
        fail(f"Backup file not found: {backup_file}")

    if not site_name:
        site_name = detect_site_name(backup_file)
        log(f"Site name detected: {site_name}")

    if not site_name:
        fail("Unable to detect site name from backup. Specify site_name explicitly.")

    site_dir = Path(f"/opt/omd/sites/{site_name}")

    log("============================================")
    log("CheckMK Compressed Backup Restore")
    log("============================================")
    log(f"Backup file: {backup_file}")
    log(f"Site name:   {site_name}")
    log(f"Site dir:    {site_dir}")
    log("============================================")

    sites = run(["omd", "sites"], check=False).stdout
    if any(line.startswith(f"{site_name} ") for line in sites.splitlines()):
        log(f"  Site '{site_name}' exists, removing...")
        run(["omd", "stop", site_name], check=False)
        rm = run(["omd", "rm", "--kill", site_name], check=False)
        if rm.returncode != 0:
            fail("Failed to remove existing site")
        log(" Site removed")

    log(" Restoring backup...")
    restore = run(["omd", "restore", str(backup_file)], check=False)
    if restore.returncode != 0:
        fail("omd restore failed")
    log(" Backup restored successfully")

    log(" Creating missing directories...")
    ensure_required_dirs(site_dir)
    log(" Directories created")

    log(" Fixing ownership and permissions...")
    chown_recursive(site_name, site_dir / "var/log")
    chown_recursive(site_name, site_dir / "var/nagios")
    chown_recursive(site_name, site_dir / "var/check_mk")
    chown_recursive(site_name, site_dir / "var/tmp")
    chown_recursive(site_name, site_dir / "tmp")

    chmod_path("750", site_dir / "var/log/apache")
    chmod_path("755", site_dir / "var/log/nagios")
    chmod_path("755", site_dir / "var/nagios")
    log(" Ownership and permissions fixed")

    log(f" Starting site '{site_name}'...")
    start = run(["omd", "start", site_name], check=False)
    if start.returncode != 0:
        fail(f"Failed to start site. Check logs in {site_dir}/var/log/")
    log(" Site started successfully")

    log("")
    log("============================================")
    log("Site Status:")
    log("============================================")
    status = run(["omd", "status", site_name], check=False)
    if status.stdout:
        print(status.stdout.strip())

    host = socket.gethostname()
    log("")
    log("============================================")
    log(" RESTORE COMPLETED SUCCESSFULLY")
    log("============================================")
    log(f"Site '{site_name}' is ready at: http://{host}/{site_name}/")
    log("")
    log("Next steps:")
    log(f"  - Verify services are running: omd status {site_name}")
    log(f"  - Check logs if needed: tail -f {site_dir}/var/log/*.log")
    log("  - Access web interface and verify configuration")
    log("============================================")

    return 0


if __name__ == "__main__":
    sys.exit(main())
