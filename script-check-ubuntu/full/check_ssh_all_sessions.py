#!/usr/bin/env python3
"""check_ssh_all_sessions.py - CheckMK Local Check for SSH Sessions

Counts all active SSH sessions from all users and displays connected usernames.
Compatible with CheckMK local check format.

Version: 1.0.0"""

import subprocess
import sys
from typing import Tuple, List, Set

VERSION = "1.0.0"
SERVICE = "SSH.All.Sessions"


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


def get_ssh_sessions() -> Tuple[int, Set[str]]:
    """Get count of active SSH sessions and list of unique users.
    
    Returns:
        Tuple of (session_count, set_of_usernames)"""
    exit_code, stdout, _ = run_command(["who"])
    
    if exit_code != 0 or not stdout:
        return 0, set()
    
    # Parse 'who' output: each line is a session
    lines = stdout.strip().split('\n')
    session_count = len([line for line in lines if line.strip()])
    
    # Extract unique usernames (first column)
    usernames = set()
    for line in lines:
        if line.strip():
            parts = line.split()
            if parts:
                usernames.add(parts[0])
    
    return session_count, usernames


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    session_count, usernames = get_ssh_sessions()
    
    if session_count > 0:
        # Sort usernames for consistent output
        users_str = ",".join(sorted(usernames))
        print(f"0 {SERVICE} - {session_count} SSH session(s) active: {users_str}")
    else:
        print(f"0 {SERVICE} - no SSH sessions")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
