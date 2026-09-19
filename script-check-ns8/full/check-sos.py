#!/usr/bin/env python3
"""check-sos.py - CheckMK Local Check for SOS session

Check if a remote support (SOS) session is active
reading system logs in /var/log/messages.

Version: 1.0.0"""

import sys
import re
from datetime import datetime
from typing import Tuple, Optional
from pathlib import Path

VERSION = "1.0.0"
SERVICE = "SOS.Session"
LOGFILE = Path("/var/log/messages")


def parse_log_timestamp(log_line: str) -> Optional[int]:
    """Extract timestamp from syslog line and convert to epoch.
    
    Args:
        log_line: Syslog line (format: "Mon DD HH:MM:SS ...")
        
    Returns:
        Unix epoch timestamp or None if parsing fails"""
    try:
        # Extract date/time from syslog format (first 15 chars: "Jan  1 12:34:56")
        date_str = ' '.join(log_line.split()[:3])
        current_year = datetime.now().year
        date_str_with_year = f"{date_str} {current_year}"
        
        dt = datetime.strptime(date_str_with_year, "%b %d %H:%M:%S %Y")
        return int(dt.timestamp())
    except (ValueError, IndexError):
        return None


def get_session_status() -> Tuple[str, str, int]:
    """Check SOS session status from system logs.
    
    Returns:
        Tuple of (status, session_id, state)
        status: "ACTIVE" or "INACTIVE"
        session_id: Session ID string or "N/A"
        state: 0=OK (inactive), 1=WARNING (active)"""
    if not LOGFILE.exists():
        return "INACTIVE", "N/A", 0
    
    try:
        with open(LOGFILE, 'r', encoding='utf-8', errors='ignore') as f:
            log_content = f.read()
    except (IOError, PermissionError):
        return "INACTIVE", "N/A", 0
    
    # Find last occurrences of start/stop/ID
    start_lines = [line for line in log_content.splitlines() if "start-support-session" in line]
    stop_lines = [line for line in log_content.splitlines() if "stop-support-session" in line]
    id_lines = [line for line in log_content.splitlines() if "Transmit the following session ID" in line]
    
    session_id = "N/A"
    status = "INACTIVE"
    state = 0
    
    # Extract session ID if available
    if id_lines:
        last_id_line = id_lines[-1]
        # Session ID is the last word in the line
        words = last_id_line.split()
        if words:
            session_id = words[-1]
    
    # Check if session is active
    if start_lines:
        last_start = start_lines[-1]
        
        if not stop_lines:
            # No stop found, session is active
            status = "ACTIVE"
            state = 1
        else:
            # Timestamps of last start and last stop appear
            last_stop = stop_lines[-1]
            
            start_epoch = parse_log_timestamp(last_start)
            stop_epoch = parse_log_timestamp(last_stop)
            
            if start_epoch and stop_epoch and start_epoch > stop_epoch:
                # Last start is after last stop, session is active
                status = "ACTIVE"
                state = 1
    
    return status, session_id, state


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    status, session_id, state = get_session_status()
    
    print(f"{state} {SERVICE} - SOS Session: {status} (ID: {session_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
