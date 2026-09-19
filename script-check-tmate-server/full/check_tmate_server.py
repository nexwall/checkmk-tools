#!/usr/bin/env python3
"""check_tmate_server.py - CheckMK Local Check for the tmate SERVER

Runs ONLY on the tmate server (checkmk-vps-02 / monitor01).
Shows ALL connected client hosts with their full SSH token,
reading files in /opt/tmate-tokens/<hostname>.txt (written by clients
via SSH push upon connection).
For each client it also shows if a viewer is currently connected.

Prerequisites:
  - /opt/tmate-tokens/ with token files for each client (setup-tmate-token-push.sh)
  - tmate-token.service on each client configured to push the token

Outputs:
  OK = hosts connected, no viewer
  WARNING = someone is viewing a session (viewer connected)
  CRITICAL = no hosts connected

Version: 1.4.0"""

import sys
import os
import subprocess
import glob
import re
import time
from typing import Optional

VERSION = "1.4.0"
EXCLUDE_IPS = {"127.0.0.1", "::1"}  # esclude il server stesso
SERVICE = "Tmate.Clients"
TOKENS_DIR = "/opt/tmate-tokens"
TOKEN_MAX_AGE = 7200  # 2 ore - token piu' vecchi considerati stale


def get_active_sessions() -> dict:
    """Reads active tmate-ssh-server processes and logs to get
    { token_prefix -> {nodename, ip, pid, viewers} }"""
    sessions = {}

    # Reads active processes: tmate-ssh-server [XXXX...] (daemon) IP
    try:
        result = subprocess.run(
            ["ps", "ax", "--no-header", "-o", "pid=,args="],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            m = re.search(r'^\s*(\d+)\s+tmate-ssh-server \[(\w+)\.\.\.\] \(daemon\) (\S+)', line)
            if m:
                pid, prefix, ip = m.group(1), m.group(2), m.group(3)
                if ip in EXCLUDE_IPS:
                    continue  # salta il server stesso (127.0.0.1)
                sessions[prefix] = {'pid': pid, 'ip': ip, 'nodename': None, 'viewers': 0}
    except Exception:
        pass

    if not sessions:
        return sessions

    # From journal: Get nodename and viewer count for each active session
    try:
        result = subprocess.run(
            ["journalctl", "-u", "tmate-ssh-server", "--no-pager", "--since", "3 hours ago"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=10
        )
        # Track viewer state per prefix - only counts AFTER "Spawning daemon" of the current session
        viewer_state = {p: 0 for p in sessions}
        spawn_seen = {p: False for p in sessions}
        for line in result.stdout.splitlines():
            # Spawning daemon: marks start of current session and takes nodename
            m = re.search(r'\[(\w+)\.\.\.\].*nodename=(\S+)', line)
            if m and m.group(1) in sessions:
                sessions[m.group(1)]['nodename'] = m.group(2)
                # Reset counter at spawn time (ignore events from previous sessions)
                spawn_seen[m.group(1)] = True
                viewer_state[m.group(1)] = 0
                continue
            # Client joined - only if the current session has already been viewed
            m = re.search(r'\[(\w+)\.\.\.\] Client joined', line)
            if m and m.group(1) in viewer_state and spawn_seen.get(m.group(1)):
                viewer_state[m.group(1)] += 1
            # Client left - only if the current session has already been viewed
            m = re.search(r'\[(\w+)\.\.\.\] Client left', line)
            if m and m.group(1) in viewer_state and spawn_seen.get(m.group(1)):
                viewer_state[m.group(1)] = max(0, viewer_state[m.group(1)] - 1)
        for prefix in sessions:
            sessions[prefix]['viewers'] = viewer_state.get(prefix, 0)
    except Exception:
        pass

    return sessions


def read_token_files(active_hosts: set = None) -> dict:
    """Reads /opt/tmate-tokens/<hostname>.txt written by clients.
    For files whose name or IP matches an active host (in active_hosts) ignore TOKEN_MAX_AGE.
    active_hosts can contain both IP and nodename/hostname.
    For others (hosts recently offline), the age limit applies.
    Return { hostname -> token_ssh_string }"""
    tokens = {}
    now = time.time()
    if active_hosts is None:
        active_hosts = set()
    for path in glob.glob(os.path.join(TOKENS_DIR, "*.txt")):
        # Salta chiavi SSH (receiver_key.pub etc.)
        if "receiver_key" in path:
            continue
        try:
            hostname = os.path.basename(path).replace('.txt', '')
            mtime = os.path.getmtime(path)
            # If the host is active in ps (by IP or by nodename), ignore the age of the file
            if hostname not in active_hosts and now - mtime > TOKEN_MAX_AGE:
                continue
            token = open(path).read().strip()
            if token and token.startswith("ssh "):
                tokens[hostname] = token
        except Exception:
            pass
    return tokens


def get_local_token() -> Optional[str]:
    """Reads the local tmate session token (the server itself)."""
    sock = "/run/tmate/tmate.sock"
    if not os.path.exists(sock):
        return None
    try:
        result = subprocess.run(
            ["tmate", "-S", sock, "display", "-p", "#{tmate_ssh}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=5
        )
        token = result.stdout.strip()
        return token if token.startswith("ssh ") else None
    except Exception:
        return None


def main() -> int:
    sessions = get_active_sessions()
    active_ips = {sess['ip'] for sess in sessions.values() if sess.get('ip')}
    active_nodenames = {sess['nodename'] for sess in sessions.values() if sess.get('nodename')}
    # Pass both IPs and nodename: avoid discarding token files for active hosts
    # whose file is named with hostname instead of IP
    token_files = read_token_files(active_ips | active_nodenames)

    # Normalize: Resolve IP -> hostname keys using session data
    ip_to_hostname = {
        sess['ip']: (sess.get('nodename') or sess['ip'])
        for sess in sessions.values() if sess.get('ip')
    }
    normalized_tokens = {}
    for key, token in token_files.items():
        resolved = ip_to_hostname.get(key, key)
        normalized_tokens[resolved] = token
    token_files = normalized_tokens

    if not sessions and not token_files:
        print(f"2 {SERVICE} - CRITICAL: no host connected to the tmate server")
        return 0

    # One line per active host
    active_nodenames = set()
    claimed_file_keys = set()
    for prefix, sess in sorted(sessions.items(), key=lambda x: x[1].get('nodename') or x[1]['ip']):
        nodename = sess.get('nodename') or sess['ip']
        active_nodenames.add(nodename)
        svc = f"Tmate.{nodename}"
        token = token_files.get(nodename) or token_files.get(sess['ip'])

        # Fallback: Search by prefix in file contents
        if not token:
            for file_key, t in token_files.items():
                m = re.search(r'ssh -p\d+ (\w+)@', t)
                if m and m.group(1).startswith(prefix):
                    token = t
                    # Prefer the token file hostname over the IP-based nodename
                    active_nodenames.discard(nodename)
                    nodename = file_key
                    svc = f"Tmate.{nodename}"
                    active_nodenames.add(nodename)
                    claimed_file_keys.add(file_key)
                    break

        viewers = sess.get('viewers', 0)

        # Check if the saved token matches the current session
        token_stale = False
        if token:
            m = re.search(r'ssh -p\d+ (\w{4})', token)
            if m and not m.group(1) == prefix:
                token_stale = True

        if viewers > 0:
            msg = f"{token} [VIEWER CONNECTED]" if token else "expected token [VIEWER CONNECTED]"
            print(f"1 {svc} - WARNING: {msg}")
        elif not token:
            print(f"1 {svc} - WARNING: [{prefix}...] expected token (systemctl restart tmate-token-push.service)")
        elif token_stale:
            print(f"1 {svc} - WARNING: {token} (restart push service)")
        else:
            print(f"0 {svc} - OK: {token}")

    # Host offline (token saved but no longer in ps)
    for hostname, token in sorted(token_files.items()):
        if hostname not in active_nodenames and hostname not in claimed_file_keys:
            svc = f"Tmate.{hostname}"
            print(f"1 {svc} - WARNING: [offline] {token}")

    # Local session of the server itself
    local_token = get_local_token()
    local_hostname = subprocess.run(
        ["hostname", "-s"], stdout=subprocess.PIPE, text=True
    ).stdout.strip() or "localhost"
    svc = f"Tmate.{local_hostname}"
    if local_token:
        # Replaces IP with FQDN in token
        local_token_display = re.sub(r'@[\d.]+', '@' + os.environ.get('TMATE_SERVER_HOST', '<tmate-server>'), local_token)
        print(f"0 {svc} - OK: {local_token_display}")
    else:
        print(f"1 {svc} - WARNING: local session not active")

    return 0


if __name__ == "__main__":
    sys.exit(main())
