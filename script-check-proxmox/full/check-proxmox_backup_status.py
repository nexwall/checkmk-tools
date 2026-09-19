#!/usr/bin/env python3
"""check-proxmox_backup_status.py - CheckMK Local Check for Proxmox Backup

Monitor last vzdump backup age (WARN 30 hours, CRIT 54 hours).

Proxmox VE

Version: 1.0.0"""

import subprocess
import sys
import os
import glob
import time

VERSION = "1.0.0"
WARN_HOURS = 30
CRIT_HOURS = 54

INDEX_FILES = [
    "/var/log/pve/tasks/index",
    "/var/log/pve/tasks/index.1"
]


def get_vzdump_lines():
    """Get all vzdump task lines from index files."""
    lines = []
    
    for index_file in INDEX_FILES:
        if not os.path.isfile(index_file):
            continue
        
        try:
            with open(index_file, 'r') as f:
                for line in f:
                    if ":vzdump:" in line:
                        lines.append(line.strip())
        except (PermissionError, IOError):
            continue
    
    return lines


def parse_upid_timestamp(upid_full):
    """Extract epoch timestamp from UPID hex start field."""
    try:
        parts = upid_full.split(':')
        if len(parts) < 6:
            return 0
        
        start_hex = parts[4]  # 5th field (0-indexed 4)
        if not start_hex:
            return 0
        
        # Convert hex to decimal
        start_epoch = int(start_hex, 16)
        return start_epoch
    except (ValueError, IndexError):
        return 0


def find_newest_vzdump():
    """Find newest vzdump task by parsing UPIDs."""
    lines = get_vzdump_lines()
    if not lines:
        return None, 0
    
    best_line = ""
    best_epoch = 0
    
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        
        upid_full = parts[0]
        start_epoch = parse_upid_timestamp(upid_full)
        
        if start_epoch > best_epoch:
            best_epoch = start_epoch
            best_line = line
    
    return best_line, best_epoch


def get_task_status(upid_full):
    """Get task status from task file."""
    # Find task file
    task_files = glob.glob(f"/var/log/pve/tasks/**/{upid_full}", recursive=True)
    if not task_files:
        return "unknown", ""
    
    task_file = task_files[0]
    
    try:
        with open(task_file, 'r') as f:
            content = f.read()
        
        # Check for completion status
        if "TASK OK" in content:
            return "OK", ""
        elif "TASK ERROR" in content:
            # Try to extract error
            for line in content.splitlines():
                if "ERROR:" in line or "TASK ERROR" in line:
                    return "ERROR", line.strip()
            return "ERROR", "TASK ERROR (no detail)"
        elif "TASK WARNING" in content:
            return "WARNING", "TASK WARNING"
        else:
            return "unknown", "task file exists but no status found"
    except (PermissionError, IOError):
        return "unknown", "cannot read task file"


def main():
    best_line, best_epoch = find_newest_vzdump()
    
    if not best_line or best_epoch == 0:
        print("2 PVE_Backup - CRIT - no vzdump tasks found or could not parse timestamps")
        return 0
    
    # Parse UPID
    upid_full = best_line.split()[0]
    
    # Calculate age
    now_epoch = int(time.time())
    age_sec = now_epoch - best_epoch
    age_hours = age_sec // 3600
    
    # Get task status
    task_status, task_detail = get_task_status(upid_full)
    
    # Determine state
    state = 0
    label = "OK"
    
    if task_status == "ERROR":
        state = 2
        label = "CRIT"
    elif task_status == "WARNING":
        state = 1
        label = "WARN"
    elif age_hours >= CRIT_HOURS:
        state = 2
        label = "CRIT"
    elif age_hours >= WARN_HOURS:
        state = 1
        label = "WARN"
    
    msg = f"last backup {age_hours}h ago, status={task_status}"
    if task_detail:
        msg += f", {task_detail}"
    
    print(f"{state} PVE_Backup age_hours={age_hours};{WARN_HOURS};{CRIT_HOURS} {label} - {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
