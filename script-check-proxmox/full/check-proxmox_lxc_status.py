#!/usr/bin/env python3
"""check-proxmox_lxc_status.py - CheckMK Local Check for Proxmox LXC Containers

Monitor LXC container status with summary and per-container checks.

Proxmox VE

Version: 1.0.0"""

import subprocess
import sys
import re

VERSION = "1.0.0"
PVE_TIMEOUT = 5


def sanitize_name(name):
    """Sanitize name for CheckMK service."""
    name = re.sub(r'[ /]', '__', name)
    return re.sub(r'[^A-Za-z0-9_.:-]', '', name)


def main():
    try:
        # Get list
        result = subprocess.run(
            ["pct", "list"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=PVE_TIMEOUT
        )
        
        if result.returncode != 0:
            print("3 PVE_LXC - pct command failed")
            return 0
        
        lines = result.stdout.strip().splitlines()[1:]  # Skip header
        total = len(lines)
        running = 0
        
        # Summary
        for line in lines:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "running":
                running += 1
        
        print(f"0 PVE_LXC_Summary running={running} total={total} OK - {running}/{total} running")
        
        # Per-CT status
        for line in lines:
            parts = line.split()
            if len(parts) < 1:
                continue
            
            ctid = parts[0]
            
            # Get hostname from config
            cfg_result = subprocess.run(
                ["pct", "config", ctid],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=PVE_TIMEOUT
            )
            
            name = f"ct{ctid}"
            if cfg_result.returncode == 0:
                for cfg_line in cfg_result.stdout.splitlines():
                    if cfg_line.startswith("hostname:"):
                        hostname = cfg_line.split(":", 1)[1].strip()
                        if hostname:
                            name = hostname
                        break
            
            # Get status
            status_result = subprocess.run(
                ["pct", "status", ctid],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=PVE_TIMEOUT
            )
            
            status = "unknown"
            if status_result.returncode == 0:
                status_parts = status_result.stdout.strip().split()
                if len(status_parts) >= 2:
                    status = status_parts[1]
            
            safe_name = sanitize_name(name)
            svc = f"PVE_LXC_{ctid}_{safe_name}"
            
            if status == "running":
                print(f"0 {svc} - OK - running")
            elif status == "stopped":
                print(f"1 {svc} - WARN - stopped")
            else:
                print(f"2 {svc} - CRIT - status {status}")
        
        return 0
        
    except subprocess.TimeoutExpired:
        print(f"2 PVE_LXC - CRIT - pct timed out after {PVE_TIMEOUT}s")
        return 0
    except FileNotFoundError:
        print("3 PVE_LXC - pct command not found")
        return 0


if __name__ == "__main__":
    sys.exit(main())
