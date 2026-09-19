#!/usr/bin/env python3
"""check-proxmox_services_status.py - CheckMK Local Check for Proxmox Services

Monitor essential Proxmox services (pvedaemon, pveproxy, pve-cluster, etc).

Proxmox VE

Version: 1.0.0"""

import subprocess
import sys

VERSION = "1.0.0"
PVE_TIMEOUT = 5

SERVICES = [
    "pvedaemon",
    "pveproxy",
    "pvestatd",
    "pve-cluster",
    "corosync",
    "pve-ha-lrm",
    "pve-ha-crm"
]


def is_service_installed(service):
    """Check if service unit file exists."""
    try:
        result = subprocess.run(
            ["systemctl", "list-unit-files", "--type=service"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=PVE_TIMEOUT
        )
        
        if result.returncode != 0:
            return False
        
        service_file = f"{service}.service"
        for line in result.stdout.splitlines():
            if line.split()[0] == service_file:
                return True
        
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError, IndexError):
        return False


def get_service_status(service):
    """Get service active and enabled status."""
    try:
        active_result = subprocess.run(
            ["systemctl", "is-active", f"{service}.service"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=PVE_TIMEOUT
        )
        active = active_result.stdout.strip() if active_result.returncode == 0 else "unknown"
        
        enabled_result = subprocess.run(
            ["systemctl", "is-enabled", f"{service}.service"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=PVE_TIMEOUT
        )
        enabled = enabled_result.stdout.strip() if enabled_result.returncode == 0 else "unknown"
        
        return active, enabled
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "unknown", "unknown"


def main():
    try:
        subprocess.run(
            ["systemctl", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=PVE_TIMEOUT
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("3 PVE_Services - systemctl not found")
        return 0
    
    for service in SERVICES:
        if not is_service_installed(service):
            continue
        
        active, enabled = get_service_status(service)
        svc = f"PVE_Service_{service}"
        
        if active == "active":
            print(f"0 {svc} enabled={enabled} OK - active")
        elif active in ["inactive", "failed"]:
            print(f"2 {svc} enabled={enabled} CRIT - {active}")
        else:
            print(f"1 {svc} enabled={enabled} WARN - {active}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
