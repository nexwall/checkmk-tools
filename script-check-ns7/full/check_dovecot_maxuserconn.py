#!/usr/bin/env python3
"""check_dovecot_maxuserconn.py - CheckMK Local Check for Dovecot max user connections

Extract mail_max_userip_connections setting from doveconf.

NethServer 7.9

Version: 1.0.0"""

import subprocess
import sys
import re

VERSION = "1.0.0"
SERVICE_NAME = "Dovecot-maxuserconn"


def get_max_user_connections() -> str:
    """Get mail_max_userip_connections from doveconf.
    
    Returns:
        Max connections value or empty string if not set"""
    try:
        result = subprocess.run(
            ["doveconf", "-a"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return ""
        
        # Search for mail_max_userip_connections line
        for line in result.stdout.splitlines():
            if line.startswith("mail_max_userip_connections"):
                parts = line.split()
                if len(parts) >= 3:
                    return parts[2]
                break
        
        return ""
        
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    maxconn = get_max_user_connections()
    
    if not maxconn:
        print(f"0 {SERVICE_NAME} - unset")
    else:
        print(f"0 {SERVICE_NAME} - {maxconn}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
