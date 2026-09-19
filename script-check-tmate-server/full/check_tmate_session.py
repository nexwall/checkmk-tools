#!/usr/bin/env python3
"""check_tmate_session.py - CheckMK Local Check for active tmate sessions

Outputs:
  OK = session active, no viewer connected
  WARNING = someone is connected as a viewer (shows their IP)

Version: 1.4.0"""

import sys
import os
import subprocess
import glob
import re

VERSION = "1.4.0"
SERVICE = "Tmate.Session"
TOKEN_FILE = "/run/tmate-ssh.txt"


def get_tmate_sockets() -> list:
    """Find all active tmate sockets from running processes."""
    sockets = []
    try:
        result = subprocess.run(
            ["ps", "aux"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "tmate" in line and "-S" in line and "grep" not in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "-S" and i + 1 < len(parts):
                        sock = parts[i + 1]
                        if os.path.exists(sock):
                            sockets.append(sock)
    except Exception:
        pass

    if not sockets:
        for pattern in ["/run/tmate/*.sock", "/tmp/tmate-*.sock"]:
            sockets.extend(glob.glob(pattern))

    return list(set(sockets))


def get_token_from_socket(sock: str) -> str:
    try:
        result = subprocess.run(
            ["tmate", "-S", sock, "display", "-p", "#{tmate_ssh}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=5
        )
        token = result.stdout.strip()
        if token and result.returncode == 0:
            return token
    except Exception:
        pass
    return ""


def get_client_ttys_from_socket(sock: str) -> list:
    """Returns list of TTYs of connected viewers (e.g. /dev/pts/1)."""
    ttys = []
    try:
        result = subprocess.run(
            ["tmate", "-S", sock, "list-clients", "-F", "#{client_name}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if line:
                    ttys.append(line)
    except Exception:
        pass
    return ttys


def get_viewer_ip(tty: str) -> str:
    """Get the viewer IP from 'who' using the TTY (e.g. /dev/pts/1 -> pts/1)."""
    pts = tty.replace("/dev/", "")  # /dev/pts/1 -> pts/1
    try:
        result = subprocess.run(
            ["who"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if pts in line:
                m = re.search(r'\(([^)]+)\)', line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return tty  # fallback: mostra la TTY grezza


def main() -> int:
    # Check that tmate is running
    try:
        result = subprocess.run(["pgrep", "-x", "tmate"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        tmate_running = result.returncode == 0
    except Exception:
        tmate_running = False

    if not tmate_running:
        print(f"2 {SERVICE} - CRITICAL: tmate not running")
        return 0

    sockets = get_tmate_sockets()

    sessions = []
    for sock in sockets:
        token = get_token_from_socket(sock)
        if not token:
            continue
        ttys = get_client_ttys_from_socket(sock)
        viewer_ips = [get_viewer_ip(tty) for tty in ttys]
        sessions.append((token, viewer_ips))

    # Fallback to the token
    if not sessions and os.path.exists(TOKEN_FILE):
        try:
            token = open(TOKEN_FILE).read().strip()
            if token:
                sessions.append((token, []))
        except Exception:
            pass

    if not sessions:
        print(f"1 {SERVICE} - WARNING: tmate active but no token available")
        return 0

    all_viewers = [ip for _, viewers in sessions for ip in viewers]

    parts = []
    for token, viewers in sessions:
        if viewers:
            parts.append(f"{token} [viewer: {', '.join(viewers)}]")
        else:
            parts.append(token)

    msg = " | ".join(parts)

    if all_viewers:
        print(f"1 {SERVICE} - WARNING: connected from {', '.join(all_viewers)} - {msg}")
    else:
        print(f"0 {SERVICE} - OK: {msg}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
