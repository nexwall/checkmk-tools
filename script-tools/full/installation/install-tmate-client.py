#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Install and configure tmate client to connect to a self-hosted tmate server
#
# After installation the SSH token is available in: /run/tmate-ssh.txt
# Read token with: cat /run/tmate-ssh.txt
#
# Usage:
#   python3 install-tmate-client.py [--server <host>] [--port <port>] [--authorized-keys /path/to/authorized_keys]

import os
import sys
import subprocess
import argparse
import time
from datetime import datetime

VERSION = "1.2.0"

TMATE_SERVER_PORT = "10022"
TMATE_SERVER_RSA_FP = "SHA256:J71q24ldCtHKvDsVrShV3WAIWVy/73KdgbcqcUo0T80"
TMATE_SERVER_ED25519_FP = "SHA256:sfN9/q+YFgewu0TCSJZZAKFjSXSRwhMADw6P1wHpQjo"

## Utils

def log(msg):
    print(f"[{datetime.now().strftime('%F %T')}] {msg}")

def die(msg):
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(1)

def run(cmd, check=True, capture=False):
    r = subprocess.run(cmd, capture_output=capture, text=True)
    if check and r.returncode != 0:
        die(f"Command failed: {' '.join(cmd)}\n{r.stderr}")
    return r

def write_file(path, content, mode=0o644):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, mode)

## Install

def install(server_host, server_port):
    log(f"=== install-tmate-client.py v{VERSION} ===")

    if os.geteuid() != 0:
        die("Must run as root")

    if not server_host:
        while True:
            server_host = input("Enter IP or FQDN of the tmate server (e.g. 143.110.148.110): ").strip()
            if server_host:
                break
            print("ERROR: value cannot be empty.")
    log(f"Server: {server_host}:{server_port}")

    # 1. Install tmate
    r = run(["which", "tmate"], capture=True, check=False)
    if r.returncode == 0:
        rv = run(["tmate", "-V"], capture=True, check=False)
        log(f"tmate already installed: {rv.stdout.strip().splitlines()[0] if rv.stdout else '?'}")
    else:
        log("Installing tmate...")
        run(["apt-get", "install", "-y", "tmate"])

    # 2. /etc/tmate.conf - disable web share
    log("Writing /etc/tmate.conf...")
    write_file("/etc/tmate.conf", "set -g tmate-web-share off\n")

    # 3. /root/.tmate.conf - point to self-hosted server
    log("Writing /root/.tmate.conf...")
    write_file("/root/.tmate.conf",
        f"set -g tmate-server-host {server_host}\n"
        f"set -g tmate-server-port {server_port}\n"
        f"set -g tmate-server-rsa-fingerprint {TMATE_SERVER_RSA_FP}\n"
        f"set -g tmate-server-ed25519-fingerprint {TMATE_SERVER_ED25519_FP}\n")

    # 4. tmate-token-writer.sh helper
    log("Installing tmate-token-writer.sh...")
    write_file("/usr/local/bin/tmate-token-writer.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "SOCK=/run/tmate/tmate.sock\n"
        "OUT=/run/tmate-ssh.txt\n"
        "pgrep -x tmate >/dev/null || exit 0\n"
        "for _ in $(seq 1 30); do [[ -S $SOCK ]] && break; sleep 1; done\n"
        "[[ -S $SOCK ]] || exit 0\n"
        "TMP=$(mktemp)\n"
        'tmate -S "$SOCK" display -p \'#{tmate_ssh}\' > "$TMP" 2>/dev/null || { rm -f "$TMP"; exit 0; }\n'
        "chmod 0600 \"$TMP\"\n"
        'mv -f "$TMP" "$OUT"\n',
        mode=0o755)

    # 5. tmate.service
    log("Installing tmate.service...")
    write_file("/etc/systemd/system/tmate.service",
        "[Unit]\n"
        "Description=Persistent tmate session (public servers)\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        "RuntimeDirectory=tmate\n"
        "RuntimeDirectoryMode=0755\n"
        "ExecStartPre=/bin/rm -f /run/tmate/tmate.sock\n"
        "ExecStart=/usr/bin/tmate -S /run/tmate/tmate.sock -F\n"
        "Restart=always\n"
        "RestartSec=10\n"
        "NoNewPrivileges=true\n"
        "PrivateTmp=true\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n")

    # 6. tmate-token.service
    write_file("/etc/systemd/system/tmate-token.service",
        "[Unit]\n"
        "Description=Write current tmate SSH session string to /run/tmate-ssh.txt\n"
        "After=tmate.service\n"
        "Requires=tmate.service\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        "ExecStart=/usr/local/bin/tmate-token-writer.sh\n")

    # 7. tmate-token.timer (refresh every 15 seconds)
    write_file("/etc/systemd/system/tmate-token.timer",
        "[Unit]\n"
        "Description=Periodically refresh tmate token file\n\n"
        "[Timer]\n"
        "OnBootSec=10\n"
        "OnUnitActiveSec=15\n"
        "AccuracySec=1s\n"
        "Unit=tmate-token.service\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n")

    # 8. Enable and start
    log("Enabling and starting services...")
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", "tmate.service", "tmate-token.timer"])

    # 9. Wait for token
    log("Waiting for token (max 45s)...")
    for _ in range(45):
        r = subprocess.run(
            ["tmate", "-S", "/run/tmate/tmate.sock", "display", "-p", "#{tmate_ssh}"],
            capture_output=True, text=True)
        t = r.stdout.strip()
        if t and r.returncode == 0:
            log("=== TMATE TOKEN ===")
            print(f"\n{t}\n")
            log("=== Done ===")
            return
        time.sleep(1)

    log("WARN: Token not yet available. Retry with: cat /run/tmate-ssh.txt")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=f"install-tmate-client.py v{VERSION}")
    p.add_argument("--server", default="", help="IP or FQDN of the tmate server")
    p.add_argument("--port", default=TMATE_SERVER_PORT, help=f"tmate server port (default: {TMATE_SERVER_PORT})")
    args = p.parse_args()
    install(args.server, args.port)
