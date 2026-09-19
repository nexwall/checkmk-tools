#!/usr/bin/env python3
"""backup-checkmk.py

Creates an OMD site backup archive and removes archives older than retention days.
Version: 1.0.0"""

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0"


def run_cmd(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main() -> int:
    parser = argparse.ArgumentParser(description="CheckMK OMD backup")
    parser.add_argument("--site", default="monitoring", help="CheckMK site name")
    parser.add_argument("--backup-dir", default="/opt/backups/checkmk", help="Backup destination directory")
    parser.add_argument("--retention-days", type=int, default=30, help="Delete backups older than N days")
    args = parser.parse_args()

    backup_dir = Path(args.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"{args.site}_{timestamp}.tar.gz"

    print(f"Creating backup: {backup_file}")
    result = run_cmd(["omd", "backup", args.site, str(backup_file)])
    if result.returncode != 0:
        print(result.stderr.strip() or "omd backup failed", file=sys.stderr)
        return result.returncode

    removed = 0
    cutoff = dt.datetime.now().timestamp() - (args.retention_days * 86400)
    for file_path in backup_dir.glob("*.tar.gz"):
        if file_path.stat().st_mtime < cutoff:
            file_path.unlink(missing_ok=True)
            removed += 1

    print(f"Backup completed: {backup_file}")
    print(f"Retention cleanup removed: {removed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
