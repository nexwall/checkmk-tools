#!/usr/bin/env python3
"""check_webtop_maxmemory.py - CheckMK Local Check for WebTop MaxMemory setting

Extract WebTop MaxMemory configuration value.

NethServer 7.9

Version: 1.0.0"""

import subprocess
import sys
import re

VERSION = "1.0.0"
SERVICE_NAME = "WebTop-maxmemory"


def get_maxmemory():
    """Get WebTop MaxMemory setting from config database.
    
    Returns:
        MaxMemory value or empty string if unset"""
    try:
        result = subprocess.run(
            ["config", "show", "webtop"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return ""
        
        for line in result.stdout.splitlines():
            if "MaxMemory" in line:
                parts = line.split('=', 1)
                if len(parts) == 2:
                    return parts[1].strip()
        
        return ""
        
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def main():
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    maxmem = get_maxmemory()
    
    if maxmem:
        print(f"0 {SERVICE_NAME} - MaxMemory = {maxmem}M")
    else:
        print(f"0 {SERVICE_NAME} - MaxMemory unset")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
