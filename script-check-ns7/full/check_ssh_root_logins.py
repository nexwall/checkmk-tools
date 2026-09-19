#!/usr/bin/env python3
"""check_ssh_root_logins.py - CheckMK Local Check for root SSH sessions

Notify if there are SSH sessions opened as root (CRITICAL alert).

NethServer 7.9

Version: 1.0.0"""

import subprocess
import sys

VERSION = "1.0.0"
SERVICE_NAME = "SSH-sessions-count"


def get_root_sessions() -> tuple:
    """Get count and IPs of root SSH sessions.
    
    Returns:
        Tuple of (count, comma-separated IPs)"""
    try:
        result = subprocess.run(
            ["who"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return (0, "")
        
        ips = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] == "root":
                ip = parts[4].strip('()')
                if ip:
                    ips.append(ip)
        
        return (len(ips), ','.join(ips))
        
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return (0, "")


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    count, ips = get_root_sessions()
    
    if count > 0:
        print(f"2 {SERVICE_NAME} - {count} root session(s) from {ips}")
    else:
        print(f"0 {SERVICE_NAME} - no root sessions")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
