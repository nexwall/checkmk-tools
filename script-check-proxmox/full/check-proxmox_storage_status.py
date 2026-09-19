#!/usr/bin/env python3
"""check-proxmox_storage_status.py - CheckMK Local Check for Proxmox Storage

Monitor storage usage with thresholds (WARN 80%, CRIT 90%).

Proxmox VE

Version: 1.0.0"""

import subprocess
import sys

VERSION = "1.0.0"
PVE_TIMEOUT = 5
WARN = 80
CRIT = 90


def main():
    try:
        result = subprocess.run(
            ["pvesm", "status"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=PVE_TIMEOUT
        )
        
        if result.returncode != 0:
            print("3 PVE_Storage - pvesm command failed")
            return 0
        
        for line in result.stdout.splitlines()[1:]:  # Skip header
            parts = line.split()
            if len(parts) < 7:
                continue
            
            name, storage_type, status = parts[0], parts[1], parts[2]
            pct_str = parts[6]  # "37.17%"
            
            # Parse percentage
            try:
                pct = float(pct_str.rstrip('%'))
                pct_int = int(round(pct))
            except ValueError:
                pct_int = 0
            
            svc = f"PVE_Storage_{name}"
            
            if status != "active":
                print(f"2 {svc} used={pct_int}%;{WARN};{CRIT} CRIT - {status}")
                continue
            
            state = 0
            if pct_int >= CRIT:
                state = 2
            elif pct_int >= WARN:
                state = 1
            
            print(f"{state} {svc} used={pct_int}%;{WARN};{CRIT} OK - used {pct_int}%")
        
        return 0
        
    except subprocess.TimeoutExpired:
        print(f"2 PVE_Storage - CRIT - pvesm timed out after {PVE_TIMEOUT}s")
        return 0
    except FileNotFoundError:
        print("3 PVE_Storage - pvesm command not found")
        return 0


if __name__ == "__main__":
    sys.exit(main())
