#!/usr/bin/env python3
"""check-sosid-ns7.py - CheckMK Local Check for SOS session ID

Show SOS session ID if active on NethServer 7.
Check systemd services and query 'don status' for ID.

NethServer 7.9

Version: 1.0.0"""

import subprocess
import sys
import re
from typing import Tuple, Optional

VERSION = "1.0.0"
SERVICE_NAME = "SOS-Session-ID"
VPN_UNIT = "don-openvpn"
SSH_UNIT = "don-sshd"


def is_active(unit: str) -> int:
    """Check if systemd unit is active.
    
    Args:
        unit: Systemd unit name
        
    Returns:
        1 if active, 0 if not active"""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", unit],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5
        )
        return 1 if result.returncode == 0 else 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0


def get_session_id() -> Optional[str]:
    """Get SOS session ID from 'don status' command.
    
    Returns:
        Session ID string or None if not found"""
    try:
        result = subprocess.run(
            ["don", "status"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return None
        
        # Parse output for Session ID line
        for line in result.stdout.splitlines():
            if "Session ID" in line:
                # Extract third word (ID value)
                parts = line.split()
                if len(parts) >= 3:
                    return parts[2]
        
        return None
        
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    vpn_status = is_active(VPN_UNIT)
    ssh_status = is_active(SSH_UNIT)
    
    if vpn_status == 1 and ssh_status == 1:
        # SOS active, try to get session ID
        session_id = get_session_id()
        
        if session_id:
            state = 1
            msg = f"SOS active - ID {session_id}"
        else:
            state = 2
            msg = "SOS active but ID not found"
    else:
        state = 0
        msg = "SOS not active"
    
    print(f"{state} {SERVICE_NAME} - {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
