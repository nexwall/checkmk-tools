#!/usr/bin/env python3
"""check-proxmox-vm-status.py - CheckMK Local Check for Proxmox VM/CT Status

Monitor runtime status of QEMU VMs and LXC containers with uptime.

Proxmox VE

Version: 1.0.0"""

import subprocess
import sys

VERSION = "1.0.0"
PVE_TIMEOUT = 15


def format_uptime(seconds):
    """Format uptime in human-readable format."""
    try:
        seconds = int(seconds)
    except (ValueError, TypeError):
        return "0s"
    
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    output = []
    if days > 0:
        output.append(f"{days}d")
    if hours > 0:
        output.append(f"{hours}h")
    if minutes > 0:
        output.append(f"{minutes}m")
    if secs > 0 or not output:
        output.append(f"{secs}s")
    
    return " ".join(output)


def check_vm_status():
    """Check QEMU VM status."""
    try:
        result = subprocess.run(
            ["qm", "list"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=PVE_TIMEOUT
        )
        
        if result.returncode != 0:
            return
        
        for line in result.stdout.splitlines()[1:]:  # Skip header
            parts = line.split()
            if len(parts) < 3:
                continue
            
            vmid, name, status = parts[0], parts[1], parts[2]
            vm_name_upper = f"STATUS_VM_{vmid}_{name.upper()}"
            
            if status == "running":
                # Get uptime
                uptime_result = subprocess.run(
                    ["qm", "status", vmid, "--verbose"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    timeout=PVE_TIMEOUT
                )
                
                uptime_seconds = 0
                if uptime_result.returncode == 0:
                    for uline in uptime_result.stdout.splitlines():
                        if uline.startswith("uptime:"):
                            try:
                                uptime_seconds = int(uline.split()[1])
                            except (ValueError, IndexError):
                                pass
                            break
                
                uptime_formatted = format_uptime(uptime_seconds)
                print(f"0 {vm_name_upper} - Running (Uptime: {uptime_formatted})")
            elif status == "stopped":
                print(f"2 {vm_name_upper} - Stopped")
            else:
                print(f"2 {vm_name_upper} - Status: {status}")
                
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


def check_lxc_status():
    """Check LXC container status."""
    try:
        result = subprocess.run(
            ["pct", "list"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=PVE_TIMEOUT
        )
        
        if result.returncode != 0:
            return
        
        for line in result.stdout.splitlines()[1:]:  # Skip header
            parts = line.split()
            if len(parts) < 3:
                continue
            
            ctid, status, name = parts[0], parts[1], parts[2]
            lxc_name_upper = f"STATUS_CT_{ctid}_{name.upper()}"
            
            if status == "running":
                # Get uptime
                uptime_result = subprocess.run(
                    ["pct", "status", ctid, "--verbose"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    timeout=PVE_TIMEOUT
                )
                
                uptime_seconds = 0
                if uptime_result.returncode == 0:
                    for uline in uptime_result.stdout.splitlines():
                        if uline.startswith("uptime:"):
                            try:
                                uptime_seconds = int(uline.split()[1])
                            except (ValueError, IndexError):
                                pass
                            break
                
                uptime_formatted = format_uptime(uptime_seconds)
                print(f"0 {lxc_name_upper} - Running (Uptime: {uptime_formatted})")
            elif status == "stopped":
                print(f"2 {lxc_name_upper} - Stopped")
            else:
                print(f"2 {lxc_name_upper} - Status: {status}")
                
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


def main():
    check_vm_status()
    check_lxc_status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
