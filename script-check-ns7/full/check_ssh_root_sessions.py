#!/usr/bin/env python3
"""check_ssh_root_sessions.py - CheckMK Local Check for SSH root session events

Generate notification for every SSH root login and logout, using state file tracking.

NethServer 7.9

Version: 1.0.0"""

import subprocess
import sys
import os
from datetime import datetime
from typing import List, Set

VERSION = "1.0.0"
SERVICE_NAME = "SSH-root-session"
STATE_FILE = "/var/lib/check_mk_agent/ssh_root_sessions.state"


def get_current_root_ips() -> Set[str]:
    """Get set of currently active root SSH session IPs.
    
    Returns:
        Set of IP addresses with active root sessions"""
    try:
        result = subprocess.run(
            ["who"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return set()
        
        ips = set()
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] == "root":
                # Extract IP from (IP) format
                ip = parts[4].strip('()')
                if ip:
                    ips.add(ip)
        
        return ips
        
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return set()


def load_previous_ips() -> Set[str]:
    """Load previous root IPs from state file.
    
    Returns:
        Set of previously active IPs"""
    if not os.path.exists(STATE_FILE):
        return set()
    
    try:
        with open(STATE_FILE, 'r') as f:
            content = f.read().strip()
            if content:
                return set(content.splitlines())
            return set()
    except IOError:
        return set()


def save_current_ips(ips: Set[str]) -> None:
    """Save current IPs to state file.
    
    Args:
        ips: Set of current IPs"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    try:
        with open(STATE_FILE, 'w') as f:
            f.write('\n'.join(sorted(ips)))
    except IOError:
        pass


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    current_ips = get_current_root_ips()
    previous_ips = load_previous_ips()
    
    # Save current state for next run
    save_current_ips(current_ips)
    
    # Find new logins
    new_logins = current_ips - previous_ips
    
    # Find logouts
    logouts = previous_ips - current_ips
    
    # Generate checks for each event
    event_generated = False
    
    for ip in sorted(new_logins):
        # Random state 1 or 2 (WARNING or CRITICAL) like original bash
        import random
        state = 1 if random.randint(0, 1) == 0 else 2
        print(f"{state} {SERVICE_NAME} - {now} root login from {ip}")
        event_generated = True
    
    for ip in sorted(logouts):
        print(f"0 {SERVICE_NAME} - {now} root logout from {ip}")
        event_generated = True
    
    # If no events, show current session count
    if not event_generated:
        count = len(current_ips)
        print(f"0 {SERVICE_NAME} - {count} root session(s) active")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
