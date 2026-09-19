#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Kill orphaned tmate-ssh-server daemon processes whose token no longer matches
# any active token file in /opt/tmate-tokens/.
# Run periodically via systemd timer on the tmate server host.

import os
import re
import glob
import signal
import subprocess
import sys
import time
import datetime

VERSION = "1.0.1"
TOKENS_DIR = "/opt/tmate-tokens"
LOG_FILE = "/var/log/tmate-cleanup.log"
EXCLUDE_IPS = {"127.0.0.1", "::1"}
# Grace period: do not kill daemons younger than this (seconds)
# Allows new sessions to stabilize before being considered stale
MIN_AGE_SECONDS = 300  # 5 minutes

## Utils

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, file=sys.stderr)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except:
        pass

def run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 1, "", str(e)

def get_process_age_seconds(pid):
    try:
        stat = os.stat(f"/proc/{pid}")
        return time.time() - stat.st_mtime
    except:
        return 99999

## Cleanup

def get_active_token_prefixes():
    """Read /opt/tmate-tokens/*.txt and extract the 4-char token prefix."""
    prefixes = set()
    for path in glob.glob(os.path.join(TOKENS_DIR, "*.txt")):
        if "receiver_key" in path:
            continue
        try:
            with open(path) as f:
                token = f.read().strip()
            # Format: ssh -p10022 NhfszGpKS...@monitor01.nethlab.it
            m = re.search(r'ssh -p\d+ (\w{4})', token)
            if m:
                prefixes.add(m.group(1))
        except:
            pass
    return prefixes

def get_daemon_processes():
    """Return list of {pid, prefix, ip} for all tmate daemon processes."""
    daemons = []
    rc, out, _ = run(["ps", "ax", "--no-header", "-o", "pid=,args="])
    if rc != 0:
        return daemons
    for line in out.splitlines():
        m = re.search(r'^\s*(\d+)\s+tmate-ssh-server \[(\w+)\.\.\.\] \(daemon\) (\S+)', line)
        if m:
            pid, prefix, ip = int(m.group(1)), m.group(2), m.group(3)
            if ip not in EXCLUDE_IPS:
                daemons.append({"pid": pid, "prefix": prefix, "ip": ip})
    return daemons

def cleanup():
    active_prefixes = get_active_token_prefixes()
    daemons = get_daemon_processes()

    if not daemons:
        log("No daemon processes found, nothing to do.")
        return

    log(f"Active token prefixes: {active_prefixes}")
    log(f"Daemon processes found: {len(daemons)}")

    killed = 0
    for d in daemons:
        prefix = d["prefix"]
        pid = d["pid"]
        ip = d["ip"]

        if prefix in active_prefixes:
            log(f"  OK   [{prefix}...] pid={pid} ip={ip} - token active, skipping")
            continue

        age = get_process_age_seconds(pid)
        if age < MIN_AGE_SECONDS:
            log(f"  SKIP [{prefix}...] pid={pid} ip={ip} - age={int(age)}s < {MIN_AGE_SECONDS}s grace, skipping")
            continue

        log(f"  KILL [{prefix}...] pid={pid} ip={ip} - stale (no active token), age={int(age)}s")
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(2)
            # Check if still alive, then SIGKILL
            try:
                os.kill(pid, 0)
                os.kill(pid, signal.SIGKILL)
                log(f"  SIGKILL sent to {pid} (did not die after SIGTERM)")
            except ProcessLookupError:
                pass  # already dead
            killed += 1
        except ProcessLookupError:
            log(f"  pid={pid} already gone")
        except Exception as e:
            log(f"  ERROR killing pid={pid}: {e}")

    log(f"Cleanup done: {killed} stale daemon(s) killed out of {len(daemons)} total.")

cleanup()
