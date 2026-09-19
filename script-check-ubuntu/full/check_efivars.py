#!/usr/bin/env python3
"""check_efivars.py - CheckMK Local Check for /sys/firmware/efi/efivars

Monitor the filling of the efivarfs filesystem.
WARNING at 80%, CRITICAL at 95%.

Version: 1.0.0"""

import subprocess
import sys

VERSION = "1.0.0"
SERVICE = "EFI.Vars"
EFIVARS_PATH = "/sys/firmware/efi/efivars"
WARN_PCT = 80
CRIT_PCT = 95


def main() -> int:
    try:
        result = subprocess.run(
            ["df", "-k", EFIVARS_PATH],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5
        )
    except Exception as e:
        print(f"3 {SERVICE} - UNKNOWN: impossibile eseguire df: {e}")
        return 0

    if result.returncode != 0:
        # efivarfs not mounted (non-UEFI system)
        print(f"0 {SERVICE} - OK: efivarfs not present (non-UEFI system)")
        return 0

    lines = result.stdout.strip().splitlines()
    if len(lines) < 2:
        print(f"3 {SERVICE} - UNKNOWN: unexpected df output")
        return 0

    # Filesystem 1K-blocks Used Available Use% Mounted on
    parts = lines[1].split()
    if len(parts) < 5:
        print(f"3 {SERVICE} - UNKNOWN: df parsing failed")
        return 0

    try:
        total_kb = int(parts[1])
        used_kb = int(parts[2])
        avail_kb = int(parts[3])
        pct = int(parts[4].rstrip("%"))
    except (ValueError, IndexError) as e:
        print(f"3 {SERVICE} - UNKNOWN: error parsing values: {e}")
        return 0

    total_kb_str = f"{total_kb}KB"
    used_kb_str = f"{used_kb}KB"
    avail_kb_str = f"{avail_kb}KB"
    msg = f"{pct}% used ({used_kb_str}/{total_kb_str}, avail {avail_kb_str})"
    metrics = f"used_pct={pct};{WARN_PCT};{CRIT_PCT};0;100 used_kb={used_kb};;;0;{total_kb}"

    if pct >= CRIT_PCT:
        print(f"2 {SERVICE} {metrics} CRITICAL: {msg}")
    elif pct >= WARN_PCT:
        print(f"1 {SERVICE} {metrics} WARNING: {msg}")
    else:
        print(f"0 {SERVICE} {metrics} OK: {msg}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
