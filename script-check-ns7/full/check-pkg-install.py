#!/usr/bin/env python3
"""check-pkg-install.py - CheckMK Local Check for YUM package installations

Monitor recent YUM activity (Installed/Updated/Erased/Removed).
Check /var/log/yum.log and track last event timestamp.

NethServer 7.9

Version: 1.0.0"""

import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

VERSION = "1.0.0"
YUM_LOG = Path("/var/log/yum.log")
STATE_FILE = Path("/var/lib/check_pkg_install/last_event")
WARN_TIMEOUT_MINUTES = 5


def parse_yum_date(date_str: str) -> Optional[int]:
    """Parse YUM log date string to Unix timestamp.
    
    Args:
        date_str: Date string from yum.log (e.g., "Jan 15 10:30:45")
        
    Returns:
        Unix timestamp or None if parsing fails"""
    try:
        # Try current year first
        current_year = datetime.now().year
        full_date = f"{current_year} {date_str}"
        
        dt = datetime.strptime(full_date, "%Y %b %d %H:%M:%S")
        return int(dt.timestamp())
    except ValueError:
        pass
    
    try:
        # Try without year
        dt = datetime.strptime(date_str, "%b %d %H:%M:%S")
        # Add current year
        dt = dt.replace(year=datetime.now().year)
        return int(dt.timestamp())
    except ValueError:
        return None


def get_last_yum_event() -> Optional[Tuple[str, str]]:
    """Get last YUM event from log file.
    
    Returns:
        Tuple of (date_string, event_description) or None if no events"""
    if not YUM_LOG.exists() or not YUM_LOG.is_file():
        return None
    
    try:
        with open(YUM_LOG, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        # Find last event line (Installed/Updated/Erased/Removed)
        event_pattern = re.compile(r'(Installed:|Updated:|Erased:|Removed:)')
        
        for line in reversed(lines):
            if event_pattern.search(line):
                # Extract date (first 3 fields: Mon DD HH:MM:SS)
                parts = line.split()
                if len(parts) >= 3:
                    date_str = ' '.join(parts[0:3])
                    
                    # Extract event description (after date)
                    event_desc = ' '.join(parts[3:]).strip()
                    
                    return (date_str, event_desc)
        
        return None
        
    except (IOError, PermissionError):
        return None


def save_timestamp(ts: int) -> None:
    """Save timestamp to state file."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(str(ts), encoding='utf-8')
    except (IOError, PermissionError):
        pass


def load_timestamp() -> int:
    """Load timestamp from state file."""
    try:
        if STATE_FILE.exists():
            return int(STATE_FILE.read_text(encoding='utf-8').strip())
    except (ValueError, IOError):
        pass
    return 0


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    if not YUM_LOG.exists() or not YUM_LOG.is_file():
        print(f"2 PKG_INSTALL - CRITICAL: {YUM_LOG} non leggibile")
        return 0
    
    # Get last event
    event = get_last_yum_event()
    
    if not event:
        print("0 PKG_INSTALL - OK: no package activity")
        return 0
    
    date_str, event_desc = event
    
    # Parse event timestamp
    event_ts = parse_yum_date(date_str)
    
    if event_ts is None:
        print(f"0 PKG_INSTALL - OK: no recent activity (last: {date_str})")
        return 0
    
    # Load last saved timestamp
    last_saved = load_timestamp()
    
    # Update if this is a newer event
    if event_ts > last_saved:
        save_timestamp(event_ts)
    
    # Check elapsed time
    last_event_ts = load_timestamp()
    current_ts = int(datetime.now().timestamp())
    elapsed_min = (current_ts - last_event_ts) // 60
    
    # Clean up event description (remove timestamp prefix if present)
    event_clean = re.sub(r'^[A-Z][a-z]{2}\s+\d+\s+[\d:]+\s+', '', event_desc)
    
    if elapsed_min < WARN_TIMEOUT_MINUTES:
        print(f"1 PKG_INSTALL - WARN: recent activity ({date_str}): {event_clean}")
    else:
        print(f"0 PKG_INSTALL - OK: no new activity in last {WARN_TIMEOUT_MINUTES} min (Last: {date_str})")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
