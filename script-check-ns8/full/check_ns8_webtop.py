#!/usr/bin/env python3
"""check_ns8_webtop.py - CheckMK Local Check for WebTop NS8

Monitor WebTop availability on NethServer 8.
Check presence of WebTop instances and HTTP interface reachability.

Version: 1.0.1"""

import subprocess
import sys
import socket
import urllib.request
import urllib.error
import ssl
from typing import Tuple, Optional

VERSION = "1.0.1"
SERVICE = "Webtop5"


def run_command(cmd: list) -> Tuple[int, str, str]:
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
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", "Command timeout"
    except FileNotFoundError:
        return 127, "", "Command not found"
    except Exception as e:
        return 1, "", str(e)


def get_domain_from_fqdn() -> Optional[str]:
    """Extract domain from host FQDN (everything after first dot).
    
    Returns:
        Domain string or None if cannot determine"""
    try:
        fqdn = socket.getfqdn()
        parts = fqdn.split('.', 1)
        
        if len(parts) > 1:
            return parts[1]
        
        return None
    except Exception:
        return None


def check_webtop_instances() -> bool:
    """Check if WebTop instances exist via runagent.
    
    Returns:
        True if WebTop instances found, False otherwise"""
    exit_code, stdout, stderr = run_command(['runagent', '-l'])
    
    if exit_code != 0:
        return False
    
    # Search for webtop instances
    for line in stdout.split('\n'):
        if line.startswith('webtop'):
            return True
    
    return False


def check_webtop_http(domain: str) -> Tuple[int, int]:
    """Check WebTop HTTP availability with SSL verification disabled.
    
    Args:
        domain: Domain name for constructing URL
        
    Returns:
        Tuple of (state, http_code)
        state: 0=OK, 2=CRITICAL
        http_code: HTTP response code or 0 if error"""
    url = f"https://webtop.{domain}/webtop/"
    
    try:
        # Create SSL context that doesn't verify certificates (like curl -k)
        ssl_context = ssl._create_unverified_context()
        
        req = urllib.request.Request(url, method='GET')
        
        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
            code = response.getcode()
            
            if code == 200:
                return 0, code
            else:
                return 2, code
            
    except urllib.error.HTTPError as e:
        # HTTP error code returned (not 200)
        return 2, e.code
    except Exception:
        # Connection error or timeout
        return 2, 0


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    # Get domain from FQDN
    domain = get_domain_from_fqdn()
    
    if not domain:
        print(f"1 {SERVICE} - No domain detected from hostname -f")
        return 0
    
    # Check WebTop instances
    if not check_webtop_instances():
        print(f"1 {SERVICE} - No WebTop instance found (module not installed)")
        return 0
    
    # Check HTTP availability
    state, http_code = check_webtop_http(domain)
    url = f"https://webtop.{domain}/webtop/"
    
    if state == 0:
        print(f"0 {SERVICE} - WebTop responding at {url} (HTTP {http_code})")
    else:
        if http_code == 0:
            print(f"2 {SERVICE} - WebTop NOT responding at {url} (Connection Error)")
        else:
            print(f"2 {SERVICE} - WebTop NOT responding at {url} (HTTP {http_code})")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
