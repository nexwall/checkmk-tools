#!/usr/bin/env python3
"""check_ssh_all_sessions.py - CheckMK Local Check for all SSH sessions

Count all active SSH sessions (all users).

NethServer 7.9

Version: 1.0.0"""

import subprocess
import sys

VERSION = "1.0.0"
SERVICE_NAME = "SSH-all-sessions"


def get_all_sessions() -> tuple:
    """Get count and unique users of all SSH sessions.
    
    Returns:
        Tuple of (session_count, comma-separated unique users)"""
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
        
        lines = result.stdout.strip().splitlines()
        session_count = len(lines)
        
        users = set()
        for line in lines:
            parts = line.split()
            if len(parts) >= 1:
                users.add(parts[0])
        
        return (session_count, ','.join(sorted(users)))
        
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return (0, "")


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    count, users = get_all_sessions()
    
    if count > 0:
        print(f"0 {SERVICE_NAME} - {count} SSH session(s) active: {users}")
    else:
        print(f"0 {SERVICE_NAME} - no SSH sessions")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
