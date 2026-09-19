#!/usr/bin/env python3
"""check_fail2ban_status.py - CheckMK Local Check for fail2ban service

Check fail2ban service status and count banned IPs across all jails.

NethServer 7.9

Version: 1.0.0"""

import subprocess
import sys
import re

VERSION = "1.0.0"
SERVICE_NAME = "Fail2ban"


def is_fail2ban_installed() -> bool:
    """Check if fail2ban-client is installed.
    
    Returns:
        True if installed, False otherwise"""
    try:
        result = subprocess.run(
            ["command", "-v", "fail2ban-client"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def is_fail2ban_running() -> bool:
    """Check if fail2ban service is running.
    
    Returns:
        True if running, False otherwise"""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", "fail2ban"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def get_jails_and_banned() -> tuple:
    """Get list of jails and total banned IPs.
    
    Returns:
        Tuple of (jails list, total_banned count)"""
    try:
        result = subprocess.run(
            ["fail2ban-client", "status"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return ([], 0)
        
        jails = []
        for line in result.stdout.splitlines():
            if "Jail list:" in line:
                # Extract jails after "Jail list:"
                jail_part = line.split(":", 1)[1].strip()
                jails = [j.strip() for j in jail_part.split(',') if j.strip()]
                break
        
        total_banned = 0
        for jail in jails:
            result = subprocess.run(
                ["fail2ban-client", "status", jail],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=10
            )
            
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if "Currently banned:" in line:
                        parts = line.split()
                        if len(parts) >= 3:
                            try:
                                banned = int(parts[-1])
                                total_banned += banned
                            except ValueError:
                                pass
                        break
        
        return (jails, total_banned)
        
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ([], 0)


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    if not is_fail2ban_installed():
        print(f"3 {SERVICE_NAME} - fail2ban not installed")
        return 0
    
    if not is_fail2ban_running():
        print(f"2 {SERVICE_NAME} - fail2ban service is not running")
        return 0
    
    jails, total_banned = get_jails_and_banned()
    
    if not jails:
        print(f"0 {SERVICE_NAME} - running, no jails configured")
    elif total_banned > 0:
        print(f"1 {SERVICE_NAME} - running, {total_banned} IP(s) banned")
    else:
        print(f"0 {SERVICE_NAME} - running, no banned IPs")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
