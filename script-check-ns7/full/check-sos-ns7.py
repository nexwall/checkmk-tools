#!/usr/bin/env python3
"""check-sos-ns7.py - CheckMK Local Check for SOS session status

Check SOS session status (WindMill VPN + SSH) on NethServer 7.
Monitor systemd services don-openvpn and don-sshd.

NethServer 7.9

Version: 1.0.0"""

import subprocess
import sys
from typing import Tuple

VERSION = "1.0.0"
SERVICE_NAME = "SOS-Session"
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


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    vpn_status = is_active(VPN_UNIT)
    ssh_status = is_active(SSH_UNIT)
    
    if vpn_status == 1 and ssh_status == 1:
        state = 1
        msg = "SOS active"
    elif vpn_status == 0 and ssh_status == 0:
        state = 0
        msg = "SOS inactive"
    else:
        state = 2
        msg = f"SOS PARTIAL: VPN={vpn_status} SSH={ssh_status}"
    
    print(f"{state} {SERVICE_NAME} - {msg} | vpn={vpn_status} ssh={ssh_status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
