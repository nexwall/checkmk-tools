#!/usr/bin/env python3
"""
check_webtop_status.py - CheckMK Local Check for WebTop service status

Check if WebTop Tomcat service is active via systemctl.

NethServer 7.9

Version: 1.0.0
"""

import subprocess
import sys

VERSION = "1.0.0"
SERVICE_NAME = "WebTop-status"


def is_webtop_running():
    """
    Check if WebTop tomcat8@webtop service is active.
    
    Returns:
        True if running, False otherwise
    """
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", "tomcat8@webtop"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def main():
    """
    Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)
    """
    if is_webtop_running():
        print(f"0 {SERVICE_NAME} - WebTop running")
    else:
        print(f"2 {SERVICE_NAME} - WebTop not running")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
