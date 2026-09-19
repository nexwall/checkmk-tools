#!/usr/bin/env python3
"""
check_webtop_https.py - CheckMK Local Check for WebTop HTTPS reachability

Test WebTop web interface reachability via HTTPS curl request.

NethServer 7.9

Version: 1.0.0
"""

import subprocess
import sys
import socket

VERSION = "1.0.0"
SERVICE_NAME = "WebTop-https"


def get_hostname_fqdn():
    """
    Get fully qualified domain name.
    
    Returns:
        FQDN or empty string
    """
    try:
        result = subprocess.run(
            ["hostname", "-f"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def test_webtop_https():
    """
    Test WebTop HTTPS reachability.
    
    Returns:
        Tuple of (http_code, message)
    """
    fqdn = get_hostname_fqdn()
    if not fqdn:
        return ("000", "Unable to get hostname")
    
    url = f"https://{fqdn}/webtop/"
    
    try:
        result = subprocess.run(
            ["curl", "-L", "-s", "-k", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "5", url],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=10
        )
        
        http_code = result.stdout.strip()
        return (http_code, "")
        
    except subprocess.TimeoutExpired:
        return ("000", "Connection timeout")
    except FileNotFoundError:
        return ("000", "curl not available")


def main():
    """
    Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)
    """
    http_code, error_msg = test_webtop_https()
    
    if http_code == "200":
        print(f"0 {SERVICE_NAME} - WebTop reachable")
    elif http_code == "000":
        msg = f"WebTop not reachable"
        if error_msg:
            msg += f" ({error_msg})"
        print(f"2 {SERVICE_NAME} - {msg}")
    else:
        print(f"2 {SERVICE_NAME} - WebTop not reachable (code {http_code})")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
