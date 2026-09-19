#!/usr/bin/env python3
"""
check_dovecot_sessions.py - CheckMK Local Check for Dovecot active sessions

Count active Dovecot sessions via doveadm who command.

NethServer 7.9

Version: 1.0.0
"""

import subprocess
import sys

VERSION = "1.0.0"
SERVICE_NAME = "Dovecot-sessions"


def get_active_sessions() -> int:
    """
    Get number of active Dovecot sessions.
    
    Returns:
        Number of active sessions
    """
    try:
        result = subprocess.run(
            ["doveadm", "who"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return 0
        
        # Count lines (each line = one session)
        return len(result.stdout.splitlines())
        
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0


def main() -> int:
    """
    Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)
    """
    sessions = get_active_sessions()
    
    print(f"0 {SERVICE_NAME} - {sessions} active session(s)")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
