#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Configure tmate token push on a CLIENT HOST
#
# Installs the private key and configures the systemd service to push
# the tmate token to the receiver server after each tmate (re)connect.
#
# Private key source (in priority order):
#   1. /tmp/tmate_token_pusher.key  (scp from server:/opt/tmate-tokens/receiver_key)
#   2. env TMATE_PUSHER_KEY
#   3. /etc/ssh/tmate_token_pusher  (already present = reinstall)
#
# Usage:
#   python3 setup-tmate-token-push.py [SERVER_IP] [SERVER_PORT]
#   python3 setup-tmate-token-push.py monitor01.example.com 22

import os
import sys
import subprocess
import time
from datetime import datetime

VERSION = "1.0.0"

KEY_FILE = "/etc/ssh/tmate_token_pusher"
SOCK = "/run/tmate/tmate.sock"

## Utils

def log(msg):
    print(f"[{datetime.now().strftime('%F %T')}] {msg}")

def die(msg):
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(1)

def run(cmd, check=True, capture=False):
    r = subprocess.run(cmd, capture_output=capture, text=True)
    if check and r.returncode != 0:
        die(f"Command failed: {' '.join(str(c) for c in cmd)}\n{r.stderr}")
    return r

def write_file(path, content, mode=0o644):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, mode)

def get_token():
    r = subprocess.run(
        ["tmate", "-S", SOCK, "display", "-p", "#{tmate_ssh}"],
        capture_output=True, text=True)
    t = r.stdout.strip()
    if t and r.returncode == 0:
        return t
    # fallback: /run/tmate/token.txt style
    if os.path.exists("/run/tmate/token.txt"):
        for line in open("/run/tmate/token.txt"):
            if line.startswith("RW="):
                return line[3:].strip()
    return ""

## Setup

def setup(server_ip, server_port):
    log(f"=== setup-tmate-token-push.py v{VERSION} ===")
    log(f"Server: {server_ip}:{server_port}")

    if os.geteuid() != 0:
        die("Must run as root")

    # 1. Install private key
    if os.path.exists("/tmp/tmate_token_pusher.key"):
        import shutil
        shutil.copy2("/tmp/tmate_token_pusher.key", KEY_FILE)
        os.chmod(KEY_FILE, 0o600)
        os.remove("/tmp/tmate_token_pusher.key")
        log(f"Key installed from /tmp/tmate_token_pusher.key")
    elif os.environ.get("TMATE_PUSHER_KEY"):
        write_file(KEY_FILE, os.environ["TMATE_PUSHER_KEY"] + "\n", mode=0o600)
        log("Key installed from TMATE_PUSHER_KEY env variable")
    elif os.path.exists(KEY_FILE):
        log(f"Key already present at {KEY_FILE} (reinstall)")
    else:
        die(
            "Private key not found.\n"
            "Run first:\n"
            f"  scp <server>:/opt/tmate-tokens/receiver_key /tmp/tmate_token_pusher.key\n"
            f"  scp /tmp/tmate_token_pusher.key <this-host>:/tmp/tmate_token_pusher.key\n"
            f"Then re-run this script."
        )

    # 2. Detect which service format this host uses
    # Format A: tmate-token.service (Ubuntu hosts with token-writer)
    # Format B: tmate.service / tmate-token-push.service
    svc_a = "/etc/systemd/system/tmate-token.service"
    svc_b_push = "/etc/systemd/system/tmate-token-push.service"

    hostname = subprocess.run(["hostname", "-s"], capture_output=True, text=True).stdout.strip()

    exec_push = (
        f'TOKEN=$(tmate -S {SOCK} display -p "#{{tmate_ssh}}" 2>/dev/null); '
        f'if [ -n "$TOKEN" ]; then '
        f'echo "$TOKEN" > /run/tmate-ssh.txt; '
        f'echo "$TOKEN" | ssh -i {KEY_FILE} -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes -p {server_port} root@{server_ip} "{hostname}" 2>/dev/null && '
        f'echo "Pushed token: $TOKEN" || echo "Push failed"; '
        f'fi'
    )

    if os.path.exists(svc_a):
        log("Detected tmate-token.service format (Ubuntu/token-writer) — updating with push")

        # Rewrite tmate-token.service to include push
        write_file(svc_a,
            "[Unit]\n"
            "Description=Write and push tmate SSH session token\n"
            "After=tmate.service\n"
            "Requires=tmate.service\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"ExecStart=/bin/bash -c '{exec_push}'\n")

        run(["systemctl", "daemon-reload"])
        log("tmate-token.service updated with push")

        # Ensure timer exists
        timer = "/etc/systemd/system/tmate-token.timer"
        if not os.path.exists(timer):
            write_file(timer,
                "[Unit]\n"
                "Description=Periodic push of tmate token\n"
                "After=tmate.service\n\n"
                "[Timer]\n"
                "OnBootSec=30\n"
                "OnUnitActiveSec=5min\n"
                "Unit=tmate-token.service\n\n"
                "[Install]\n"
                "WantedBy=timers.target\n")
            run(["systemctl", "daemon-reload"])
            run(["systemctl", "enable", "--now", "tmate-token.timer"])
            log("tmate-token.timer created and started")
        else:
            run(["systemctl", "start", "tmate-token.service"], check=False)

    elif run(["systemctl", "is-active", "tmate.service"], capture=True, check=False).stdout.strip() == "active" \
            or os.path.exists("/run/tmate/token.txt"):
        log("Detected tmate.service format — creating tmate-token-push.service")

        write_file(svc_b_push,
            "[Unit]\n"
            "Description=Push tmate token to receiver server\n"
            "After=tmate.service\n"
            "Requires=tmate.service\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            "ExecStartPre=/bin/sleep 3\n"
            f"ExecStart=/bin/bash -c 'TOKEN=$(tmate -S {SOCK} display -p \"#{{tmate_ssh}}\" 2>/dev/null); "
            f"if [ -z \"$TOKEN\" ] && [ -f /run/tmate/token.txt ]; then TOKEN=$(grep \"^RW=\" /run/tmate/token.txt | cut -d= -f2-); fi; "
            f"if [ -n \"$TOKEN\" ]; then "
            f"echo \"$TOKEN\" | ssh -i {KEY_FILE} -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes -p {server_port} root@{server_ip} \"{hostname}\" 2>/dev/null && "
            f"echo \"Pushed token: $TOKEN\" || echo \"Push failed\"; fi'\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n")

        write_file("/etc/systemd/system/tmate-token-push.timer",
            "[Unit]\n"
            "Description=Periodic push of tmate token to receiver server\n"
            "After=tmate.service\n\n"
            "[Timer]\n"
            "OnBootSec=30\n"
            "OnUnitActiveSec=5min\n"
            "Unit=tmate-token-push.service\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n")

        run(["systemctl", "daemon-reload"])
        run(["systemctl", "enable", "--now", "tmate-token-push.timer"])
        log("tmate-token-push.service + timer created and enabled")
    else:
        die("No tmate service found. Run install-tmate-client.py first.")

    # 3. Immediate push test
    log("Testing push now...")
    token = get_token()
    if not token:
        log("WARN: Token not available now. Push will happen automatically on next timer.")
        return

    r = subprocess.run(
        ["ssh", "-i", KEY_FILE, "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
         "-p", str(server_port), f"root@{server_ip}", hostname],
        input=token + "\n", capture_output=True, text=True)
    if r.returncode == 0:
        log(f"[OK] Pushed token: {token}")
    else:
        log(f"[WARN] Push failed (check connectivity to {server_ip}:{server_port})")

    log("=== Setup complete ===")


if __name__ == "__main__":
    server_ip = sys.argv[1] if len(sys.argv) > 1 else ""
    server_port = sys.argv[2] if len(sys.argv) > 2 else "22"

    if not server_ip:
        while True:
            server_ip = input("Enter IP or FQDN of the receiver server: ").strip()
            if server_ip:
                break

    setup(server_ip, server_port)
