#!/usr/bin/env python3
"""check_disk_space.py - CheckMK Local Check for Disk Space Monitoring

Monitors disk space usage on root filesystem with configurable thresholds.
Compatible with CheckMK local check format.

Version: 1.0.0"""

import subprocess
import sys
import re
from typing import Tuple, Optional

VERSION = "1.0.0"
SERVICE = "Disk.Space.Root"

# Configurable thresholds (percentage)
THRESHOLD_WARNING = 80
THRESHOLD_CRITICAL = 95


def run_command(cmd: list[str]) -> Tuple[int, str, str]:
    """Execute a shell command and return exit code, stdout, stderr.
    
    Args:
        cmd: Command as list of strings
        
    Returns:
        Tuple of (exit_code, stdout, stderr)"""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Command timeout"
    except FileNotFoundError:
        return 127, "", "Command not found"
    except Exception as e:
        return 1, "", str(e)


def get_disk_usage(mount_point: str = "/") -> Optional[int]:
    """Get disk usage percentage for specified mount point.
    
    Args:
        mount_point: Filesystem mount point to check (default: /)
        
    Returns:
        Usage percentage (0-100) or None if error"""
    exit_code, stdout, _ = run_command(["df", mount_point])
    
    if exit_code != 0 or not stdout:
        return None
    
    # Parse df output: skip header line, get last line
    lines = stdout.strip().split('\n')
    if len(lines) < 2:
        return None
    
    # Extract usage percentage (5th column, format: "XX%")
    last_line = lines[-1]
    parts = last_line.split()
    if len(parts) < 5:
        return None
    
    usage_str = parts[4]  # e.g., "45%"
    
    # Remove % sign and convert to int
    match = re.match(r'(\d+)%?', usage_str)
    if match:
        return int(match.group(1))
    
    return None


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    usage = get_disk_usage("/")
    
    if usage is None:
        print(f"3 {SERVICE} - Failed to get disk usage")
        return 0
    
    # Determine status based on thresholds
    if usage < THRESHOLD_WARNING:
        print(f"0 {SERVICE} - OK - Disk space used: {usage}%")
    elif usage < THRESHOLD_CRITICAL:
        print(f"1 {SERVICE} - WARNING - Disk space used: {usage}%")
    else:
        print(f"2 {SERVICE} - CRITICAL - Disk space used: {usage}%")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
