#!/usr/bin/env python3
"""check-proxmox_vm_monitor.py - CheckMK Local Check for Proxmox VM Monitor

General VM and container health check with summary metrics.

Proxmox VE

Version: 1.0.0"""

import subprocess
import sys

VERSION = "1.0.0"
PVE_TIMEOUT = 15


def run_cmd(cmd, timeout=PVE_TIMEOUT):
    """Run command with timeout."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout
        )
        return result.returncode, result.stdout
    except subprocess.TimeoutExpired:
        return 124, ""
    except FileNotFoundError:
        return 127, ""


def sanitize_name(name):
    """Sanitize name for CheckMK service."""
    import re
    return re.sub(r'[^A-Za-z0-9_-]', '', name.replace(' ', '_'))


def main():
    # Check qm and pct commands exist (use 'list' as validation)
    rc_qm, _ = run_cmd(["/usr/sbin/qm", "list"], timeout=5)
    rc_pct, _ = run_cmd(["/usr/sbin/pct", "list"], timeout=5)
    
    if rc_qm != 0 and rc_pct != 0:
        print("3 Proxmox_VM_Summary - qm/pct commands failed")
        return 0
    
    # VMs
    total_vms = 0
    running_vms = 0
    rc, out = run_cmd(["/usr/sbin/qm", "list"])
    if rc == 0:
        for line in out.splitlines()[1:]:  # Skip header
            parts = line.split()
            if len(parts) >= 3:
                total_vms += 1
                if parts[2] == "running":
                    running_vms += 1
    
    stopped_vms = total_vms - running_vms
    
    # LXC
    total_lxc = 0
    running_lxc = 0
    rc, out = run_cmd(["/usr/sbin/pct", "list"])
    if rc == 0:
        for line in out.splitlines()[1:]:  # Skip header
            parts = line.split()
            if len(parts) >= 3:
                total_lxc += 1
                if parts[2] == "running":
                    running_lxc += 1
    
    stopped_lxc = total_lxc - running_lxc
    
    # Determine summary status
    if stopped_vms > 0 or stopped_lxc > 0:
        status = 1
        status_text = "WARNING"
    else:
        status = 0
        status_text = "OK"
    
    metrics = f"total_vms={total_vms} running_vms={running_vms} stopped_vms={stopped_vms} total_lxc={total_lxc} running_lxc={running_lxc} stopped_lxc={stopped_lxc}"
    msg = f"VMs: {running_vms}/{total_vms} running, LXC: {running_lxc}/{total_lxc} running"
    print(f"{status} Proxmox_VM_Summary {metrics} {status_text} - {msg}")
    
    # Individual VM checks
    rc, out = run_cmd(["/usr/sbin/qm", "list"])
    if rc == 0:
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 3:
                continue
            
            vmid, name, status_vm = parts[0], parts[1], parts[2]
            safe_name = sanitize_name(name)
            svc = f"VM_{vmid}_{safe_name}"
            
            if status_vm == "running":
                print(f"0 {svc} - Running")
            else:
                print(f"1 {svc} - {status_vm}")
    
    # Individual LXC checks
    rc, out = run_cmd(["/usr/sbin/pct", "list"])
    if rc == 0:
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 3:
                continue
            
            ctid, name, status_ct = parts[0], parts[1], parts[2]
            safe_name = sanitize_name(name)
            svc = f"CT_{ctid}_{safe_name}"
            
            if status_ct == "running":
                print(f"0 {svc} - Running")
            else:
                print(f"1 {svc} - {status_ct}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
