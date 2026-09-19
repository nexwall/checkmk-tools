#!/usr/bin/env python3
"""check_postfix_status.py - CheckMK Local Check for Postfix service status

Check if Postfix mail server is active via systemctl.

NethServer 7.9

Version: 1.0.0"""

import subprocess
import sys

VERSION = "1.0.0"
SERVICE_NAME = "Postfix-status"


def is_service_active(service: str) -> bool:
    """Check if systemd service is active.
    
    Args:
        service: Systemd service name
        
    Returns:
        True if active, False otherwise"""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", service],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    if is_service_active("postfix"):
        print(f"0 {SERVICE_NAME} - Postfix running")
    else:
        print(f"2 {SERVICE_NAME} - Postfix not running")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
