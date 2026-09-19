#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Periodic git pull loop for /opt/checkmk-tools (or TARGET_DIR env var).
# Runs forever, sleeping SYNC_INTERVAL seconds between each pull.
# Usage: auto_git_sync.py [interval_seconds]

import os
import subprocess
import sys
import time

VERSION = "1.0.0"

## Utils

def git_pull(target_dir):
    try:
        r = subprocess.run(
            ["git", "-C", target_dir, "pull", "--quiet"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return 1, "", str(e)

## Main

def main():
    target_dir = os.environ.get("TARGET_DIR", "/opt/checkmk-tools")
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("SYNC_INTERVAL", "60"))

    print(f"auto_git_sync v{VERSION} — target={target_dir} interval={interval}s", flush=True)

    while True:
        rc, out, err = git_pull(target_dir)
        if rc != 0 and err:
            print(f"[WARN] git pull failed: {err}", flush=True)
        elif out and out != "Already up to date.":
            print(f"[INFO] {out}", flush=True)
        time.sleep(interval)

main()
