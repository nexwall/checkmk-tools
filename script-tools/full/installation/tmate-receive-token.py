#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# tmate-receive-token.py
# Forced command on the server: receives tmate tokens from clients via SSH
#
# Called from /root/.ssh/authorized_keys with:
#   command="/opt/tmate-receive-token.py",no-pty,no-X11-forwarding,...
#
# Stdin: tmate token (e.g. "ssh -p10022 AbCdEf@server")
# SSH_ORIGINAL_COMMAND: client hostname (passed as SSH argument)
# SSH_CONNECTION: client IP in field 1

import os
import sys
import subprocess

TOKENS_DIR = "/opt/tmate-tokens"

## Utils

def clean_name(s):
    return "".join(c for c in s if c.isalnum() or c in "._-")

def logger(msg):
    subprocess.run(["logger", "-t", "tmate-receiver", msg], capture_output=True)

## Receive

def receive():
    client_ip = os.environ.get("SSH_CONNECTION", "").split()[0] if os.environ.get("SSH_CONNECTION") else "unknown"

    # Method 1: client passes hostname as SSH argument
    nodename = clean_name(os.environ.get("SSH_ORIGINAL_COMMAND", ""))

    # Method 2: fallback - journalctl lookup for this IP
    if not nodename:
        try:
            r = subprocess.run(
                ["journalctl", "-u", "tmate-ssh-server", "-n", "1000", "--no-pager"],
                capture_output=True, text=True, timeout=5)
            import re
            matches = re.findall(rf"ip={re.escape(client_ip)}.*?nodename=(\S+)", r.stdout)
            if matches:
                nodename = clean_name(matches[-1])
        except Exception:
            pass

    # Method 3: fallback to IP
    if not nodename:
        nodename = client_ip

    token = sys.stdin.readline().strip()
    if not token:
        return

    os.makedirs(TOKENS_DIR, mode=0o755, exist_ok=True)
    path = os.path.join(TOKENS_DIR, f"{nodename}.txt")
    with open(path, "w") as f:
        f.write(token + "\n")
    os.chmod(path, 0o644)
    logger(f"Token saved for {nodename} (ip={client_ip})")

    # Cleanup: remove stale IP-named file if nodename differs
    if nodename != client_ip:
        stale = os.path.join(TOKENS_DIR, f"{client_ip}.txt")
        if os.path.exists(stale):
            os.remove(stale)
            logger(f"Removed stale {client_ip}.txt (replaced by {nodename}.txt)")

receive()
