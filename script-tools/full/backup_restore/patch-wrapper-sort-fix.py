#!/usr/bin/env python3
"""Patch /usr/local/sbin/checkmk_cloud_backup_push_run.sh - fix remote retention sort bug."""
import sys
from pathlib import Path

WRAPPER = Path("/usr/local/sbin/checkmk_cloud_backup_push_run.sh")

# OLD: double backslashes produced by raw-string bug in .py installer
OLD = r"""mapfile -t sorted_backups < <(
      printf '%s\\n' "${all_remote_backups[@]}" | \\
        sed 's/.*\\([0-9]\\{4\\}-[0-9]\\{2\\}-[0-9]\\{2\\}-[0-9]\\{2\\}h[0-9]\\{2\\}\\).*/\\1 &/' | \\
        sort -r | \\
        cut -d' ' -f2-
    )"""

# NEW: single backslashes - correct bash line-continuation and sed BRE
NEW = r"""mapfile -t sorted_backups < <(
      printf '%s\n' "${all_remote_backups[@]}" | \
        sed 's/.*\([0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}-[0-9]\{2\}h[0-9]\{2\}\).*/\1 &/' | \
        sort -r | \
        cut -d' ' -f2-
    )"""

if not WRAPPER.exists():
    print(f"ERROR: {WRAPPER} not found", file=sys.stderr)
    sys.exit(1)

content = WRAPPER.read_text()

if OLD not in content:
    if NEW in content:
        print("Already patched.")
        sys.exit(0)
    print(f"ERROR: pattern not found in {WRAPPER}", file=sys.stderr)
    print("First 5 chars of OLD repr:", repr(OLD[:80]))
    sys.exit(1)

WRAPPER.write_text(content.replace(OLD, NEW, 1))
print(f"Patched OK: {WRAPPER}")

