#!/usr/bin/env python3
"""check-proxmox_qemu_runtime.py - CheckMK Local Check for QEMU Runtime Metrics

Monitor CPU, memory, and disk usage for running QEMU VMs.

Proxmox VE

Version: 1.0.0"""

import subprocess
import json
import sys
import re
import socket

VERSION = "1.0.0"
PVE_TIMEOUT = 30

# Thresholds (percent)
CPU_WARN = 85
CPU_CRIT = 95
MEM_WARN = 85
MEM_CRIT = 95
DISK_WARN = 85
DISK_CRIT = 95


def sanitize_name(name):
    """Sanitize VM name for CheckMK service name."""
    name = re.sub(r'[ /]', '__', name)
    name = re.sub(r'[^A-Za-z0-9_.:-]', '', name)
    return name


def get_node_name():
    """Get local node name."""
    try:
        return socket.gethostname().split('.')[0]
    except:
        return "localhost"


def get_vms_json(node):
    """Get all VMs on node via pvesh JSON."""
    try:
        result = subprocess.run(
            ["pvesh", "get", f"/nodes/{node}/qemu", "--output-format", "json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=PVE_TIMEOUT
        )
        
        if result.returncode != 0:
            return []
        
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        return []


def get_vm_status_json(node, vmid):
    """Get detailed VM status via pvesh JSON."""
    try:
        result = subprocess.run(
            ["pvesh", "get", f"/nodes/{node}/qemu/{vmid}/status/current", "--output-format", "json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=PVE_TIMEOUT
        )
        
        if result.returncode != 0:
            return {}
        
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        return {}


def main():
    # Check pvesh and jq commands exist
    try:
        subprocess.run(
            ["pvesh", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("3 PVE_QEMU_Runtime - pvesh command not found")
        return 0
    
    node = get_node_name()
    vms = get_vms_json(node)
    
    if not vms:
        print(f"1 PVE_QEMU_Runtime_Summary - WARN - no VMs found on node {node}")
        return 0
    
    # Summary counters
    total = len(vms)
    running = 0
    
    for vm in vms:
        vmid = vm.get("vmid", "")
        name = vm.get("name", f"vm{vmid}")
        status = vm.get("status", "unknown")
        safe_name = sanitize_name(name)
        svc = f"PVE_QEMU_{vmid}_{safe_name}_Runtime"
        
        if status != "running":
            print(f"0 {svc} - OK - status={status}")
            continue
        
        running += 1
        
        # Get detailed status for running VMs
        json_status = get_vm_status_json(node, vmid)
        if not json_status:
            print(f"2 {svc} - CRIT - cannot read status/current")
            continue
        
        # Extract metrics
        cpu_frac = json_status.get("cpu", 0)  # 0..1 or 0..N (N cores)
        maxcpu = json_status.get("cpus", 1)
        cpu_pct = int(round((cpu_frac / maxcpu) * 100)) if maxcpu > 0 else 0
        
        mem_bytes = json_status.get("mem", 0)
        maxmem_bytes = json_status.get("maxmem", 1)
        mem_pct = int(round((mem_bytes / maxmem_bytes) * 100)) if maxmem_bytes > 0 else 0
        
        disk_bytes = json_status.get("disk", 0)
        maxdisk_bytes = json_status.get("maxdisk", 1)
        disk_pct = int(round((disk_bytes / maxdisk_bytes) * 100)) if maxdisk_bytes > 0 else 0
        
        # Determine state
        state = 0
        if cpu_pct >= CPU_CRIT or mem_pct >= MEM_CRIT or disk_pct >= DISK_CRIT:
            state = 2
        elif cpu_pct >= CPU_WARN or mem_pct >= MEM_WARN or disk_pct >= DISK_WARN:
            state = 1
        
        # Outputs
        metrics = f"cpu={cpu_pct}%;{CPU_WARN};{CPU_CRIT} mem={mem_pct}%;{MEM_WARN};{MEM_CRIT} disk={disk_pct}%;{DISK_WARN};{DISK_CRIT}"
        msg = f"CPU {cpu_pct}%, MEM {mem_pct}%, DISK {disk_pct}%"
        print(f"{state} {svc} {metrics} - {msg}")
    
    # Summary
    print(f"0 PVE_QEMU_Runtime_Summary running={running} total={total} - {running}/{total} running")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
