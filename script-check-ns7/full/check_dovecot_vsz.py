#!/usr/bin/env python3
"""check_dovecot_vsz.py - CheckMK Local Check for Dovecot VSZ memory limit

Extract Dovecot VszLimit setting from system configuration.

NethServer 7.9

Version: 1.0.0"""

import subprocess
import sys
import re

VERSION = "1.0.0"
SERVICE_NAME = "Dovecot-vsz-limit"


def get_vsz_limit() -> str:
    """Get Dovecot VszLimit from config.
    
    Returns:
        VSZ limit value or empty string if not set"""
    try:
        result = subprocess.run(
            ["config", "show", "dovecot"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return ""
        
        # Search for VszLimit line
        for line in result.stdout.splitlines():
            if 'VszLimit' in line:
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1]
        
        return ""
        
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    vsz_limit = get_vsz_limit()
    
    if not vsz_limit:
        print(f"0 {SERVICE_NAME} - VSZ limit unset")
    else:
        print(f"0 {SERVICE_NAME} - VSZ limit = {vsz_limit}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
