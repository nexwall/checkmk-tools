#!/usr/bin/env python3
"""check_postfix_process.py - CheckMK Local Check for Postfix process count

Count running Postfix processes via pgrep.

NethServer 7.9

Version: 1.0.0"""

import subprocess
import sys

VERSION = "1.0.0"
SERVICE_NAME = "Postfix-processes"


def count_postfix_processes() -> int:
    """Count running Postfix processes.
    
    Returns:
        Number of Postfix processes"""
    try:
        result = subprocess.run(
            ["pgrep", "-c", "-f", "postfix"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=5
        )
        
        # pgrep -c returns count in stdout, exit 0 if found, 1 if not found
        if result.returncode == 0:
            return int(result.stdout.strip())
        else:
            return 0
        
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return 0


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    proc_count = count_postfix_processes()
    
    if proc_count > 0:
        print(f"0 {SERVICE_NAME} - {proc_count} Postfix process(es) running")
    else:
        print(f"2 {SERVICE_NAME} - No Postfix processes found")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
