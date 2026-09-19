#!/usr/bin/env python3
"""check_ssh_root_sessions.py - CheckMK Local Check for Root SSH Session Events

Tracks root SSH sessions and generates alerts for login/logout events.
Maintains state file to detect changes between checks.

Version: 1.0.0"""

import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Tuple, Set, List

VERSION = "1.0.0"
SERVICE = "SSH.Root.Session"

# State file configuration
STATE_DIR = Path("/var/lib/check_mk_agent")
STATE_FILE = STATE_DIR / "ssh_root_sessions.state"

# Session count thresholds (when no events)
THRESHOLD_WARNING = 1
THRESHOLD_CRITICAL = 6


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


def get_current_root_ips() -> Set[str]:
    """Get set of IP addresses for currently logged in root users.
    
    Returns:
        Set of IP addresses"""
    exit_code, stdout, _ = run_command(["who"])
    
    if exit_code != 0 or not stdout:
        return set()
    
    ips = set()
    
    for line in stdout.strip().split('\n'):
        if not line.strip():
            continue
        
        parts = line.split()
        if not parts:
            continue
        
        # Check if first column is 'root'
        if parts[0] == "root" and len(parts) >= 5:
            # Extract IP from format: (192.168.1.1)
            ip_field = parts[4]
            ip = ip_field.strip('()')
            if ip:
                ips.add(ip)
    
    return ips


def load_previous_ips() -> Set[str]:
    """Load previous IP addresses from state file.
    
    Returns:
        Set of IP addresses from previous check"""
    try:
        if STATE_FILE.exists():
            content = STATE_FILE.read_text().strip()
            if content:
                return set(content.split('\n'))
        return set()
    except Exception:
        return set()


def save_current_ips(ips: Set[str]) -> None:
    """Save current IP addresses to state file.
    
    Args:
        ips: Set of IP addresses to save"""
    try:
        # Ensure state directory exists
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        
        # Save IPs, one per line
        content = '\n'.join(sorted(ips)) if ips else ''
        STATE_FILE.write_text(content)
    except Exception:
        pass  # Fail silently, state will be empty next time


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Get current and previous IPs
    current_ips = get_current_root_ips()
    previous_ips = load_previous_ips()
    
    # Save current state for next check
    save_current_ips(current_ips)
    
    # Find new logins and logouts
    new_logins = current_ips - previous_ips
    logouts = previous_ips - current_ips
    
    # Generate alerts for new logins
    if new_logins:
        for ip in sorted(new_logins):
            # CRITICAL for root logins (security sensitive)
            print(f"2 {SERVICE} - {current_time} root login from {ip}")
    
    # Generate OK messages for logouts
    if logouts:
        for ip in sorted(logouts):
            print(f"0 {SERVICE} - {current_time} root logout from {ip}")
    
    # If no events, report current session count with thresholds
    if not new_logins and not logouts:
        count = len(current_ips)
        
        if count == 0:
            print(f"0 {SERVICE} - no root sessions")
        elif count < THRESHOLD_CRITICAL:
            print(f"1 {SERVICE} - {count} root session(s) active")
        else:
            print(f"2 {SERVICE} - {count} root session(s) active")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
