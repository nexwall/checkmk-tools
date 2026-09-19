#!/usr/bin/env python3
"""check-proxmox_qemu_guest_agent_status.py - CheckMK Local Check for QEMU Guest Agent

Verify QEMU Guest Agent status for all running VMs (pvesh JSON API).

Proxmox VE

Version: 1.0.2"""

import subprocess
import json
import sys
import re
import time

VERSION = "1.0.2"
PVE_TIMEOUT = 10
PER_VM_CONFIG_TIMEOUT = 1
PER_VM_PING_TIMEOUT = 1
TOTAL_BUDGET_SECONDS = 30


def sanitize_name(name):
    """Sanitize VM name for CheckMK service name."""
    name = re.sub(r'[ /]', '__', name)
    name = re.sub(r'[^A-Za-z0-9_.:-]', '', name)
    return name


def get_all_vms():
    """Get all VMs using pvesh JSON API."""
    try:
        result = subprocess.run(
            ["pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json"],
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


def get_vm_config(vmid):
    """Get VM configuration."""
    try:
        result = subprocess.run(
            ["pvesh", "get", f"/nodes/localhost/qemu/{vmid}/config", "--output-format", "json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return {}
        
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        return {}


def test_qemu_agent(vmid):
    """Test QEMU guest agent connectivity."""
    try:
        result = subprocess.run(
            ["pvesh", "get", f"/nodes/localhost/qemu/{vmid}/agent/ping"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=10
        )
        
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def main():
    started = time.monotonic()

    # Verify pvesh command exists
    try:
        subprocess.run(
            ["pvesh", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("3 PVE_QGA - pvesh command not found")
        return 0
    
    vms = get_all_vms()
    if not vms:
        print("3 PVE_QGA - Failed to get VM list")
        return 0
    
    for vm in vms:
        vm_type = vm.get("type", "")
        if vm_type != "qemu":
            continue
        
        vmid = vm.get("vmid", "")
        name = vm.get("name", f"VM{vmid}")
        status = vm.get("status", "")
        
        if status != "running":
            continue  # Only check running VMs

        if (time.monotonic() - started) >= TOTAL_BUDGET_SECONDS:
            print("1 QGA_Runtime runtime_seconds=%.1f WARN - execution budget reached, partial results" % (time.monotonic() - started))
            break
        
        svc = f"QGA_{sanitize_name(name)}"
        
        # Get VM config and check if agent is enabled
        config = {}
        try:
            result_cfg = subprocess.run(
                ["pvesh", "get", f"/nodes/localhost/qemu/{vmid}/config", "--output-format", "json"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=PER_VM_CONFIG_TIMEOUT
            )
            if result_cfg.returncode == 0:
                config = json.loads(result_cfg.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            config = {}

        agent_cfg = config.get("agent", "0")
        
        # Parse agent config: "1" or "enabled=1" or "enabled=1,fstrim_cloned_disks=1"
        agent_enabled = "1" in agent_cfg
        
        if not agent_enabled:
            print(f"0 {svc} vmid={vmid} OK - agent disabled in config")
            continue
        
        # Test agent connectivity
        try:
            result_ping = subprocess.run(
                ["pvesh", "get", f"/nodes/localhost/qemu/{vmid}/agent/ping"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=PER_VM_PING_TIMEOUT
            )
            qga_ok = result_ping.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            qga_ok = False

        if qga_ok:
            print(f"0 {svc} vmid={vmid} OK - responding")
        else:
            print(f"2 {svc} vmid={vmid} CRIT - not responding")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
