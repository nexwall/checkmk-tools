#!/usr/bin/env python3
"""check-ssh-failures.py - CheckMK Local Check for SSH banned IPs

Count currently banned IPs by fail2ban SSH jail.

NethServer 7.9

Version: 1.0.0"""

import subprocess
import sys
import re

VERSION = "1.0.0"
SERVICE_NAME = "SSH-Failures"


def get_banned_count() -> int:
    """Get number of currently banned IPs in sshd jail.
    
    Returns:
        Number of banned IPs, -1 if fail2ban not active or jail not found"""
    try:
        result = subprocess.run(
            ["fail2ban-client", "status", "sshd"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return -1
        
        # Parse "Currently banned: N" line
        for line in result.stdout.splitlines():
            if "Currently banned:" in line:
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        return int(parts[3])
                    except ValueError:
                        return 0
        
        return 0
        
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return -1


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    banned = get_banned_count()
    
    if banned < 0:
        print(f"0 {SERVICE_NAME} - Fail2ban not active or jail sshd not found")
        return 0
    
    if banned > 0:
        print(f"1 {SERVICE_NAME} - SSH failed logins blocked (banned IPs) = {banned}")
    else:
        print(f"0 {SERVICE_NAME} - No SSH failed logins currently blocked")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
