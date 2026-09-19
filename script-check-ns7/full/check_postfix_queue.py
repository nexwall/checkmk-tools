#!/usr/bin/env python3
"""check_postfix_queue.py - CheckMK Local Check for Postfix mail queue

Monitor Postfix mail queue size with thresholds.
Thresholds: <20 OK, <100 WARNING, >=100 CRITICAL

NethServer 7.9

Version: 1.0.0"""

import subprocess
import sys
import re

VERSION = "1.0.0"
SERVICE_NAME = "Postfix-queue"


def get_queue_size() -> int:
    """Get number of messages in Postfix queue.
    
    Returns:
        Number of messages in queue, -1 if unable to read"""
    try:
        result = subprocess.run(
            ["mailq"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return -1
        
        # Count lines starting with hex ID (Message-ID format)
        count = 0
        for line in result.stdout.splitlines():
            if re.match(r'^[A-F0-9]', line):
                count += 1
        
        return count
        
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return -1


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    queue_size = get_queue_size()
    
    if queue_size < 0:
        print(f"3 {SERVICE_NAME} - Unable to read postfix queue")
        return 0
    
    if queue_size < 20:
        state = 0
        status = "OK"
    elif queue_size < 100:
        state = 1
        status = "WARNING"
    else:
        state = 2
        status = "CRITICAL"
    
    print(f"{state} {SERVICE_NAME} - Mail queue {status}: {queue_size} messages")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
