#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Install and configure tmate-ssh-server + token receiver infrastructure on a VPS
#
# What it does:
#   1. Install tmate + tmate-ssh-server packages (Ubuntu/Debian)
#   2. Generate server RSA/ED25519 keys (if not already present)
#   3. Configure /etc/default/tmate-ssh-server (port + hostname)
#   4. Create /opt/tmate-tokens/ directory + receiver SSH key pair
#   5. Deploy tmate-receive-token.py (from repo or inline)
#   6. Configure /root/.ssh/authorized_keys with push restriction
#   7. Enable + start tmate-ssh-server service
#   8. Show fingerprints for client .tmate.conf
#   9. Optionally install tmate client (connecting to this server on localhost)
#
# Usage:
#   python3 install-tmate-server.py [--hostname <fqdn>] [--port <port>] [--skip-client]

import os
import sys
import subprocess
import argparse
import stat
import shutil
from datetime import datetime

VERSION = "1.0.0"

TMATE_SERVER_PORT = "10022"
KEYS_DIR = "/etc/tmate-ssh-server/keys"
TOKENS_DIR = "/opt/tmate-tokens"
RECEIVER_KEY = f"{TOKENS_DIR}/receiver_key"
RECEIVE_SCRIPT = "/opt/tmate-receive-token.py"

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
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)
    os.chmod(path, mode)

def get_fingerprint(key_path):
    r = run(["ssh-keygen", "-l", "-f", key_path, "-E", "sha256"], capture=True)
    return r.stdout.strip().split()[1] if r.returncode == 0 and r.stdout.strip() else "?"

## Install

def install(hostname, port, skip_client):
    log(f"=== install-tmate-server.py v{VERSION} ===")

    if os.geteuid() != 0:
        die("Must run as root")

    if not hostname:
        while True:
            hostname = input("Enter FQDN or public IP for this tmate server (e.g. monitor01.example.com): ").strip()
            if hostname:
                break
            print("ERROR: value cannot be empty.")

    log(f"Server: {hostname}:{port}")

    # 1. Install packages
    log("Installing tmate and tmate-ssh-server...")
    run(["apt-get", "update", "-qq"])
    run(["apt-get", "install", "-y", "tmate", "tmate-ssh-server"])
    r = run(["tmate", "-V"], capture=True, check=False)
    log(f"Installed: tmate {r.stdout.strip().splitlines()[0] if r.stdout else '?'}")

    # 2. Keys directory
    log(f"Creating keys directory {KEYS_DIR}...")
    os.makedirs(KEYS_DIR, mode=0o700, exist_ok=True)

    # 3. Generate server keys
    rsa_key = f"{KEYS_DIR}/ssh_host_rsa_key"
    ed25519_key = f"{KEYS_DIR}/ssh_host_ed25519_key"

    if not os.path.exists(rsa_key):
        log("Generating RSA server key...")
        run(["ssh-keygen", "-t", "rsa", "-b", "4096", "-f", rsa_key, "-N", "", "-q"])
    else:
        log("RSA key already present, skipping.")

    if not os.path.exists(ed25519_key):
        log("Generating ED25519 server key...")
        run(["ssh-keygen", "-t", "ed25519", "-f", ed25519_key, "-N", "", "-q"])
    else:
        log("ED25519 key already present, skipping.")

    for k in [rsa_key, ed25519_key]:
        os.chmod(k, 0o600)

    # 4. Configure tmate-ssh-server
    log("Writing /etc/default/tmate-ssh-server...")
    write_file("/etc/default/tmate-ssh-server",
        f"# tmate-ssh-server configuration\n"
        f"# Managed by install-tmate-server.py\n"
        f'OPTS="-k {KEYS_DIR} -p {port} -h {hostname}"\n')

    # 5. Create tokens dir + receiver key
    log(f"Creating {TOKENS_DIR}...")
    os.makedirs(TOKENS_DIR, mode=0o755, exist_ok=True)

    if not os.path.exists(RECEIVER_KEY):
        log("Generating receiver SSH key pair...")
        run(["ssh-keygen", "-t", "ed25519", "-f", RECEIVER_KEY, "-N", "", "-C", "tmate-token-receiver-v2", "-q"])
        os.chmod(RECEIVER_KEY, 0o600)
        os.chmod(f"{RECEIVER_KEY}.pub", 0o644)
    else:
        log("Receiver key already present, skipping.")

    # 6. Deploy receive script
    log(f"Deploying {RECEIVE_SCRIPT}...")
    # Try to copy from repo first
    repo_candidates = [
        "/opt/checkmk-tools/script-tools/full/installation/tmate-receive-token.py",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmate-receive-token.py"),
    ]
    deployed = False
    for src in repo_candidates:
        if os.path.exists(src):
            shutil.copy2(src, RECEIVE_SCRIPT)
            os.chmod(RECEIVE_SCRIPT, 0o755)
            log(f"Deployed from repo: {src}")
            deployed = True
            break

    if not deployed:
        log("Repo script not found, creating inline...")
        write_file(RECEIVE_SCRIPT, RECEIVE_TOKEN_SCRIPT_INLINE, mode=0o755)

    # 7. Configure authorized_keys
    with open(f"{RECEIVER_KEY}.pub") as f:
        pubkey = f.read().strip()
    key_id = pubkey.split()[1] if len(pubkey.split()) >= 2 else pubkey
    push_entry = f'command="{RECEIVE_SCRIPT}",no-pty,no-X11-forwarding,no-agent-forwarding,no-port-forwarding {pubkey}\n'

    auth_keys = "/root/.ssh/authorized_keys"
    os.makedirs("/root/.ssh", mode=0o700, exist_ok=True)
    if not os.path.exists(auth_keys):
        open(auth_keys, 'w').close()
    os.chmod(auth_keys, 0o600)

    with open(auth_keys) as f:
        existing = f.read()

    if key_id in existing:
        log(f"Push key already present in {auth_keys}, skipping.")
    else:
        with open(auth_keys, 'a') as f:
            f.write(push_entry)
        log(f"Push key added to {auth_keys}")

    # 8. Enable tmate-ssh-server
    log("Enabling tmate-ssh-server...")
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", "tmate-ssh-server"])
    r = run(["systemctl", "is-active", "tmate-ssh-server"], capture=True, check=False)
    if r.stdout.strip() == "active":
        log(f"tmate-ssh-server is running on port {port}")
    else:
        log("WARNING: tmate-ssh-server may not be running - check: systemctl status tmate-ssh-server")

    # 9. Show fingerprints
    rsa_fp = get_fingerprint(f"{rsa_key}.pub")
    ed25519_fp = get_fingerprint(f"{ed25519_key}.pub")
    log("")
    log("=== SERVER FINGERPRINTS (use in client .tmate.conf) ===")
    print(f"\n  set -g tmate-server-host {hostname}")
    print(f"  set -g tmate-server-port {port}")
    print(f"  set -g tmate-server-rsa-fingerprint {rsa_fp}")
    print(f"  set -g tmate-server-ed25519-fingerprint {ed25519_fp}\n")
    log(f"Receiver private key (copy to clients): {RECEIVER_KEY}")
    log(f"  scp {hostname}:{RECEIVER_KEY} /tmp/tmate_token_pusher.key")
    log(f"  Then on each client: python3 setup-tmate-token-push.py {hostname} 22")

    # 10. Optionally configure tmate client on this server
    if not skip_client:
        ans = input("Also configure tmate CLIENT on this server (connects to localhost)? [Y/n]: ").strip() or "Y"
        if ans.upper() == "Y":
            configure_local_client(hostname, port, rsa_fp, ed25519_fp)
            return
        else:
            log("Client setup skipped. Use install-tmate-client.py to configure it later.")

    log("=== install-tmate-server.py DONE ===")


def configure_local_client(hostname, port, rsa_fp, ed25519_fp):
    log("Configuring tmate client (localhost connection)...")

    self_hostname = subprocess.run(["hostname", "-s"], capture_output=True, text=True).stdout.strip()

    write_file("/root/.tmate.conf",
        f"set -g tmate-server-host 127.0.0.1\n"
        f"set -g tmate-server-port {port}\n"
        f"set -g tmate-server-rsa-fingerprint {rsa_fp}\n"
        f"set -g tmate-server-ed25519-fingerprint {ed25519_fp}\n")
    log("~/.tmate.conf written (localhost)")

    write_file("/etc/tmate.conf", "set -g tmate-web-share off\n")

    write_file("/etc/systemd/system/tmate.service",
        "[Unit]\n"
        "Description=Persistent tmate session (self-hosted)\n"
        "After=tmate-ssh-server.service\n"
        "Wants=tmate-ssh-server.service\n\n"
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

    write_file("/etc/systemd/system/tmate-token-push.service",
        "[Unit]\n"
        "Description=Push tmate token to receiver\n"
        "After=tmate.service\n"
        "Requires=tmate.service\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        "ExecStartPre=/bin/sleep 5\n"
        f"ExecStart=/bin/bash -c '"
        f'TOKEN=$(tmate -S /run/tmate/tmate.sock display -p "#{{tmate_ssh}}" 2>/dev/null); '
        f'if [ -n "$TOKEN" ]; then '
        f'echo "$TOKEN" > /run/tmate-ssh.txt; '
        f'echo "$TOKEN" | ssh -i {RECEIVER_KEY} -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes -p 22 root@127.0.0.1 "{self_hostname}" 2>/dev/null && '
        f'echo "Token pushed: $TOKEN" || echo "Push failed (will retry on next timer)"; '
        f"fi'\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n")

    write_file("/etc/systemd/system/tmate-token-push.timer",
        "[Unit]\n"
        "Description=Periodically push tmate token\n"
        "After=tmate.service\n\n"
        "[Timer]\n"
        "OnBootSec=30\n"
        "OnUnitActiveSec=5min\n"
        "Unit=tmate-token-push.service\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n")

    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", "tmate.service", "tmate-token-push.timer"])
    log("tmate client services enabled and started")

    log("Waiting for tmate token (max 45s)...")
    import time
    for _ in range(45):
        r = subprocess.run(
            ["tmate", "-S", "/run/tmate/tmate.sock", "display", "-p", "#{tmate_ssh}"],
            capture_output=True, text=True)
        t = r.stdout.strip()
        if t and r.returncode == 0:
            log("=== TMATE TOKEN ===")
            print(f"\n{t}\n")
            break
        time.sleep(1)
    else:
        log("WARN: Token not yet available. Check with: tmate -S /run/tmate/tmate.sock display -p '#{tmate_ssh}'")

    log("=== install-tmate-server.py DONE ===")


# Inline fallback for tmate-receive-token.py (used if repo not found)
RECEIVE_TOKEN_SCRIPT_INLINE = '''#!/usr/bin/python3
# tmate-receive-token.py - forced command in authorized_keys
import os, sys
client_ip = os.environ.get("SSH_CONNECTION", "").split()[0] if os.environ.get("SSH_CONNECTION") else "unknown"
nodename = "".join(c for c in os.environ.get("SSH_ORIGINAL_COMMAND", "") if c.isalnum() or c in "._-") or client_ip
token = sys.stdin.readline().strip()
tokens_dir = "/opt/tmate-tokens"
if token:
    path = f"{tokens_dir}/{nodename}.txt"
    with open(path, "w") as f:
        f.write(token + "\\n")
    os.chmod(path, 0o644)
    os.system(f"logger -t tmate-receiver 'Token saved for {nodename} (ip={client_ip})'")
    stale = f"{tokens_dir}/{client_ip}.txt"
    if nodename != client_ip and os.path.exists(stale):
        os.remove(stale)
        os.system(f"logger -t tmate-receiver 'Removed stale {client_ip}.txt'")
'''


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=f"install-tmate-server.py v{VERSION}")
    p.add_argument("--hostname", default="", help="FQDN or IP of this server")
    p.add_argument("--port", default=TMATE_SERVER_PORT, help=f"tmate server port (default: {TMATE_SERVER_PORT})")
    p.add_argument("--skip-client", action="store_true", help="Skip local tmate client setup")
    args = p.parse_args()
    install(args.hostname, args.port, args.skip_client)
