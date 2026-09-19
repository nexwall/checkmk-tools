#!/usr/bin/env python3
"""check_fail2ban_status.py - CheckMK Local Check for Fail2ban Status

Monitors fail2ban service status and counts banned IPs across all jails.
Compatible with CheckMK local check format.

Version: 1.0.0"""

import subprocess
import sys
import re
from typing import Tuple, List, Optional

VERSION = "1.0.0"
SERVICE = "Fail2ban"


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


def is_fail2ban_installed() -> bool:
    """Check if fail2ban-client command is available."""
    exit_code, _, _ = run_command(["which", "fail2ban-client"])
    return exit_code == 0


def is_fail2ban_running() -> bool:
    """Check if fail2ban service is active."""
    # Try systemctl first (systemd systems)
    exit_code, _, _ = run_command(["systemctl", "is-active", "--quiet", "fail2ban"])
    if exit_code == 0:
        return True
    
    # Fallback to service command (non-systemd systems)
    exit_code, _, _ = run_command(["service", "fail2ban", "status"])
    return exit_code == 0


def get_active_jails() -> Optional[List[str]]:
    """Get list of active fail2ban jails.
    
    Returns:
        List of jail names or None if error"""
    exit_code, stdout, _ = run_command(["fail2ban-client", "status"])
    if exit_code != 0:
        return None
    
    # Parse "Jail list: ssh, apache-auth" line
    for line in stdout.split('\n'):
        if "Jail list" in line:
            # Extract jail names after colon, remove commas
            jails_str = line.split(':', 1)[1].strip()
            if jails_str:
                # Split by comma and strip whitespace
                return [jail.strip() for jail in jails_str.split(',')]
            return []
    
    return []


def get_banned_count(jail: str) -> int:
    """Get number of currently banned IPs for a specific jail.
    
    Args:
        jail: Name of the fail2ban jail
        
    Returns:
        Number of banned IPs (0 if error)"""
    exit_code, stdout, _ = run_command(["fail2ban-client", "status", jail])
    if exit_code != 0:
        return 0
    
    # Parse "Currently banned: 5" line
    for line in stdout.split('\n'):
        if "Currently banned" in line:
            # Extract number at end of line
            match = re.search(r'(\d+)$', line.strip())
            if match:
                return int(match.group(1))
    
    return 0


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    # Check if fail2ban is installed
    if not is_fail2ban_installed():
        print(f"3 {SERVICE} - fail2ban not installed")
        return 0
    
    # Check if fail2ban is running
    if not is_fail2ban_running():
        print(f"2 {SERVICE} - fail2ban service is not running")
        return 0
    
    # Get active jails
    jails = get_active_jails()
    
    if jails is None:
        # Error getting jail list
        print(f"2 {SERVICE} - failed to query fail2ban status")
        return 0
    
    if not jails:
        # No jails configured
        print(f"0 {SERVICE} - running, no jails configured")
        return 0
    
    # Count total banned IPs across all jails
    total_banned = 0
    for jail in jails:
        banned = get_banned_count(jail)
        total_banned += banned
    
    # Output result
    if total_banned > 0:
        print(f"1 {SERVICE} - running, {total_banned} IP(s) banned")
    else:
        print(f"0 {SERVICE} - running, no banned IPs")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
