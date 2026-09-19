#!/usr/bin/env python3
"""monitor_podman_events.py - Daemon for monitoring Podman events

Listen to Podman events in real time and only record events
create/start/stop/remove, excluding redis containers.

Writes events to /var/log/podman_events.log

Version: 1.0.0"""

import subprocess
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

VERSION = "1.0.0"
LOGFILE = Path("/var/log/podman_events.log")


def should_log_event(event_line: str) -> bool:
    """Check if event should be logged.
    
    Args:
        event_line: Event line from podman events
        
    Returns:
        True if event should be logged, False otherwise"""
    # Exclude redis containers
    if "redis" in event_line.lower():
        return False
    
    # Only log these event types
    event_types = [" create ", " start ", " stop ", " remove "]
    return any(event_type in event_line for event_type in event_types)


def run_podman_events_daemon() -> int:
    """Run podman events daemon and log filtered events.
    
    Returns:
        Exit code (0 on success, non-zero on error)"""
    # Create log directory if needed
    LOGFILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Podman events command with format
    cmd = [
        "podman", "events",
        "--filter", "type=container",
        "--format", "{{.Time}} {{.Status}} {{.Name}} ({{.ID}})"
    ]
    
    try:
        # Open log file for appending
        with open(LOGFILE, 'a', encoding='utf-8') as log_fp:
            # Run podman events and process output line by line
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1  # Line buffered
            )
            
            print(f"[INFO] Podman events daemon started (PID: {process.pid})")
            print(f"[INFO] Logging to: {LOGFILE}")
            
            # Process events in real time
            for line in process.stdout:
                line = line.strip()
                if line and should_log_event(line):
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    log_entry = f"{timestamp} - {line}\n"
                    log_fp.write(log_entry)
                    log_fp.flush()  # Ensure immediate write
            
            # Wait for process to complete
            process.wait()
            return process.returncode
            
    except KeyboardInterrupt:
        print("\n[INFO] Daemon stopped by user")
        return 0
    except FileNotFoundError:
        print("[ERROR] podman command not found")
        return 127
    except PermissionError:
        print(f"[ERROR] Permission denied writing to {LOGFILE}")
        return 1
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        return 1


def main() -> int:
    """Main daemon entry point.
    
    Returns:
        Exit code"""
    print(f"monitor_podman_events.py v{VERSION}")
    print("Starting Podman events monitoring daemon...")
    print("Press Ctrl+C to stop\n")
    
    return run_podman_events_daemon()


if __name__ == "__main__":
    sys.exit(main())
