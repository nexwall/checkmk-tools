#!/usr/bin/python3 -u
"""check_cockpit_sessions.py - CheckMK Local Check for Cockpit session events

Monitor Cockpit login/logout events from /var/log/messages and report active sessions.

NethServer 7.9

Version: 1.0.0"""

import subprocess
import sys
import os
import re
import traceback
from datetime import datetime

VERSION = "1.0.1"
SERVICE_NAME = "Cockpit-Sessions"
STATE_FILE = "/var/lib/check_mk_agent/cockpit_sessions.state"
LOG_FILE = "/var/log/messages"


def get_last_line_processed():
    """Get last log line number processed.
    
    Returns:
        Last line number processed, 0 if no state file"""
    if not os.path.exists(STATE_FILE):
        return 0
    
    try:
        with open(STATE_FILE, 'r') as f:
            return int(f.read().strip())
    except (IOError, ValueError):
        return 0


def save_last_line_processed(line_num):
    """Save last log line number processed.
    
    Args:
        line_num: Line number to save"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    try:
        with open(STATE_FILE, 'w') as f:
            f.write(str(line_num))
    except IOError:
        pass


def extract_ip(line):
    """Extract IP address from log line.
    
    Args:
        line: Log line
        
    Returns:
        IP address or empty string"""
    match = re.search(r'from (\d+\.\d+\.\d+\.\d+)', line)
    if match:
        return match.group(1)
    return ""


def get_new_cockpit_events(last_line):
    """Get new Cockpit events from log file.
    
    Args:
        last_line: Last line processed
        
    Returns:
        List of tuples (line_number, log_line)"""
    if not os.path.exists(LOG_FILE):
        return []
    
    events = []
    try:
        # Explicitly use UTF-8 and replace invalid characters to avoid UnicodeDecodeError
        with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
            for i, line in enumerate(f, start=1):
                if i > last_line and 'cockpit-ws:' in line:
                    events.append((i, line.strip()))
    except IOError:
        return []
    
    return events


def count_active_sessions():
    """Count active Cockpit sessions via ss command.

    Returns:
        Number of active sessions"""
    try:
        # Use absolute path if available, otherwise fallback to "ss" in the PATH
        ss_cmd = "/usr/sbin/ss" if os.path.exists("/usr/sbin/ss") else "ss"

        result = subprocess.run(
            [ss_cmd, "-tnp"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=10,
        )

        if result.returncode != 0:
            return 0

        count = 0
        for line in result.stdout.splitlines():
            if "cockpit-ws" in line:
                count += 1

        return count

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0


def main():
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    last_line = get_last_line_processed()
    new_events = get_new_cockpit_events(last_line)
    
    if new_events:
        # Update state file with last processed line
        save_last_line_processed(new_events[-1][0])
        
        # Process and report events
        import random
        for line_num, line in new_events:
            if "New connection to session from" in line:
                ip = extract_ip(line)
                if ip:
                    # Random state 1 or 2 (WARNING or CRITICAL) to force notification
                    state = 1 if random.randint(0, 1) == 0 else 2
                    print(f"{state} {SERVICE_NAME} - {now} cockpit login from {ip}")
            elif "for session closed" in line:
                ip = extract_ip(line)
                if ip:
                    print(f"0 {SERVICE_NAME} - {now} cockpit logout from {ip}")
    else:
        # No new events, report current session count
        active = count_active_sessions()
        print(f"0 {SERVICE_NAME} - {active} cockpit session(s) active")
    
    return 0


if __name__ == "__main__":
    try:
        main()
        sys.stdout.flush()
    except Exception:
        # Fallback output in case of catastrophe
        err_msg = traceback.format_exc().replace('\n', ' || ')
        print(f"2 Cockpit-Sessions - OVERALL-CRASH: {err_msg}")
        sys.exit(0)
