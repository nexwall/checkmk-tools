#!/usr/bin/env python3
"""check-proxmox_qemu_status.py - CheckMK Local Check for Proxmox QEMU VMs

Monitor QEMU VM status with summary and per-VM checks.

Proxmox VE

Version: 1.0.0"""

import subprocess
import sys
import re

VERSION = "1.0.0"
PVE_TIMEOUT = 8


def sanitize_name(name):
    """Sanitize name for CheckMK service."""
    name = re.sub(r'[ /]', '__', name)
    return re.sub(r'[^A-Za-z0-9_.:-]', '', name)


def main():
    try:
        result = subprocess.run(
            ["qm", "list"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=PVE_TIMEOUT
        )
        
        if result.returncode == 124:
            print(f"2 PVE_QEMU - CRIT - qm list timed out after {PVE_TIMEOUT}s")
            return 0
        elif result.returncode != 0 or not result.stdout.strip():
            print(f"2 PVE_QEMU - CRIT - qm list failed (rc={result.returncode})")
            return 0
        
        lines = result.stdout.strip().splitlines()[1:]  # Skip header
        total = len(lines)
        running = 0
        
        vm_data = []
        for line in lines:
            parts = line.split()
            if len(parts) < 3:
                continue
            
            vmid, name, status = parts[0], parts[1], parts[2]
            vm_data.append((vmid, name, status))
            
            if status == "running":
                running += 1
        
        stopped = total - running
        
        print(f"0 PVE_QEMU_Summary running={running} total={total} OK - {running}/{total} running")
        print(f"0 PVE_QEMU_Stopped_Count stopped={stopped} OK - {stopped} stopped")
        
        # Per-VM status
        for vmid, name, status in vm_data:
            if not name or name == "null":
                name = f"vm{vmid}"
            
            safe_name = sanitize_name(name)
            svc = f"PVE_QEMU_{vmid}_{safe_name}"
            
            if status == "running":
                print(f"0 {svc} - OK - running")
            elif status == "stopped":
                print(f"0 {svc} - OK - stopped")
            else:
                print(f"2 {svc} - CRIT - status {status}")
        
        return 0
        
    except subprocess.TimeoutExpired:
        print(f"2 PVE_QEMU - CRIT - qm list timed out after {PVE_TIMEOUT}s")
        return 0
    except FileNotFoundError:
        print("3 PVE_QEMU - qm command not found")
        return 0


if __name__ == "__main__":
    sys.exit(main())
