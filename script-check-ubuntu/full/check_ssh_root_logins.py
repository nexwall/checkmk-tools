#!/usr/bin/env python3
"""check_ssh_root_logins.py - CheckMK Local Check for Root SSH Sessions

Monitors active root SSH sessions and reports IP addresses.
Alerts based on configurable thresholds.

Version: 1.0.0"""

import subprocess
import sys
import re
from typing import Tuple, List

VERSION = "1.0.0"
SERVICE = "SSH.Sessions.Count"

# Configurable thresholds
THRESHOLD_WARNING = 1  # WARNING if >= 1 root session
THRESHOLD_CRITICAL = 6  # CRITICAL if >= 6 root sessions


def run_command(cmd: List[str]) -> Tuple[int, str, str]:
    """Execute a shell command and return exit code, stdout, stderr.
    
    Args:
        cmd: Command as list of strings
        
    Returns:
        Tuple of (exit_code, stdout, stderr)"""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Command timeout"
    except FileNotFoundError:
        return 127, "", "Command not found"
    except Exception as e:
        return 1, "", str(e)


def get_root_sessions() -> Tuple[int, List[str]]:
    """Get count of root SSH sessions and list of IP addresses.
    
    Returns:
        Tuple of (session_count, list_of_ips)"""
    exit_code, stdout, _ = run_command(["who"])
    
    if exit_code != 0 or not stdout:
        return 0, []
    
    root_count = 0
    ips = []
    
    # Parse 'who' output, filter for root user
    for line in stdout.strip().split('\n'):
        if not line.strip():
            continue
        
        parts = line.split()
        if not parts:
            continue
        
        # First column is username
        if parts[0] == "root":
            root_count += 1
            
            # Extract IP from format: (192.168.1.1) or similar
            # IP is typically in 5th column
            if len(parts) >= 5:
                ip_field = parts[4]
                # Remove parentheses
                ip = ip_field.strip('()')
                if ip:
                    ips.append(ip)
    
    return root_count, ips


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    session_count, ips = get_root_sessions()
    
    if session_count == 0:
        print(f"0 {SERVICE} - no root sessions")
    elif session_count < THRESHOLD_CRITICAL:
        # WARNING state (1-5 sessions)
        ips_str = ",".join(ips) if ips else "unknown"
        print(f"1 {SERVICE} - {session_count} root session(s) from {ips_str}")
    else:
        # CRITICAL state (>= 6 sessions)
        ips_str = ",".join(ips) if ips else "unknown"
        print(f"2 {SERVICE} - {session_count} root session(s) from {ips_str}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
