#!/usr/bin/env python3
"""checkmk_backup_cleanup.py - CheckMK Backup Cleanup Tool

Manages CheckMK backup retention and renaming:
- Renames completed backups with timestamps
- Applies retention policy (deletes oldest if exceeding limit)
- Supports systemd timer setup for automatic cleanup

Commands:
  setup - Setup automatic cleanup with systemd timer
  run - Run cleanup manually
  remove - Remove automatic cleanup
  
Version: 1.0.0"""

import sys
import os
import argparse
import subprocess
import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List

VERSION = "1.0.0"
DEFAULT_BACKUP_DIR = "/var/backups/checkmk"
DEFAULT_RETENTION_DAYS = 30
LOGFILE = "/var/log/checkmk-backup-cleanup.log"


def log(message: str) -> None:
    """Log message to stdout and logfile.
    
    Args:
        message: Message to log"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {message}"
    print(formatted)
    
    try:
        with open(LOGFILE, "a") as f:
            f.write(formatted + "\n")
    except Exception:
        pass  # Best effort logging


def err(message: str) -> None:
    """Log error message to stderr and logfile.
    
    Args:
        message: Error message to log"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] ERROR: {message}"
    print(formatted, file=sys.stderr)
    
    try:
        with open(LOGFILE, "a") as f:
            f.write(formatted + "\n")
    except Exception:
        pass


def die(message: str) -> None:
    """Log error and exit.
    
    Args:
        message: Error message"""
    err(message)
    sys.exit(1)


def need_root() -> None:
    """Check if running as root, exit if not."""
    if os.geteuid() != 0:
        die("This script must be run as root.")


def prompt_default(prompt: str, default: str) -> str:
    """Prompt user for input with default value.
    
    Args:
        prompt: Prompt message
        default: Default value if user enters nothing
        
    Returns:
        User input or default value"""
    if default:
        user_input = input(f"{prompt} [{default}]: ").strip()
    else:
        user_input = input(f"{prompt}: ").strip()
    
    return user_input if user_input else default


def confirm_default_yes(prompt: str) -> bool:
    """Ask user for confirmation (default: yes).
    
    Args:
        prompt: Confirmation prompt
        
    Returns:
        True if user confirms, False otherwise"""
    answer = input(f"{prompt} [Y/n]: ").strip().lower()
    return answer == "" or answer in ["y", "yes"]


def get_backup_size(path: Path) -> int:
    """Get size of backup (file or directory).
    
    Args:
        path: Path to backup
        
    Returns:
        Size in bytes"""
    try:
        if path.is_dir():
            # Get directory size
            result = subprocess.run(
                ["du", "-sb", str(path)],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return int(result.stdout.split()[0])
        else:
            return path.stat().st_size
    except Exception:
        return 0


def cleanup_backups(backup_dir: str, retention_days: int) -> None:
    """Perform backup cleanup: rename complete backups and apply retention.
    
    Args:
        backup_dir: Directory containing backups
        retention_days: Maximum number of backups to keep"""
    log("Starting backup rename and retention check (local backup)")
    log(f"Backup directory: {backup_dir}")
    log(f"Max backups to keep: {retention_days}")
    
    backup_path = Path(backup_dir)
    if not backup_path.exists():
        err(f"Backup directory not found: {backup_dir}")
        return
    
    # Count backups before processing
    all_items = list(backup_path.iterdir())
    total_before = len(all_items)
    log(f"Total backups: {total_before}")
    
    # Rename complete backups without timestamp
    log("Looking for completed backups to rename...")
    renamed = 0
    
    for item in all_items:
        if not item.name.endswith("-complete"):
            continue
        
        log(f"Found complete backup: {item.name}")
        
        # Check if backup is stable (not modified in last 2 minutes)
        try:
            last_modified = item.stat().st_mtime
            current_time = datetime.now().timestamp()
            age_seconds = int(current_time - last_modified)
            
            if age_seconds < 120:
                log(f"Backup too recent ({age_seconds}s old), skipping: {item.name}")
                continue
            
            # Check backup size (must be > 100KB)
            backup_size = get_backup_size(item)
            if backup_size < 102400:
                log(f"Backup too small ({backup_size} bytes), skipping: {item.name}")
                continue
            
            # Check if already has timestamp pattern (YYYY-MM-DD-HHhMM)
            if not re.search(r'-\d{4}-\d{2}-\d{2}-\d{2}h\d{2}$', item.name):
                # Get modification time and create timestamp
                mtime = datetime.fromtimestamp(last_modified)
                timestamp = mtime.strftime("%Y-%m-%d-%Hh%M")
                new_name = f"{item.name}-{timestamp}"
                new_path = backup_path / new_name
                
                log(f"Renaming: {item.name} -> {new_name} (age: {age_seconds}s, size: {backup_size} bytes)")
                try:
                    item.rename(new_path)
                    renamed += 1
                except Exception as e:
                    err(f"Failed to rename {item.name}: {e}")
        
        except Exception as e:
            err(f"Error processing {item.name}: {e}")
    
    log(f"Renamed {renamed} backup(s)")
    
    # Count valid backups (exclude incomplete)
    valid_backups = [
        b for b in backup_path.iterdir()
        if b.name.startswith("Check_MK-") and "-incomplete" not in b.name
    ]
    backup_count = len(valid_backups)
    log(f"Current backup count: {backup_count} (max: {retention_days})")
    
    # Delete oldest backups if exceeding retention
    if backup_count > retention_days:
        to_delete = backup_count - retention_days
        log(f"Exceeding retention limit by {to_delete} backup(s), deleting oldest...")
        
        # Sort by modification time (oldest first)
        valid_backups.sort(key=lambda b: b.stat().st_mtime)
        
        deleted = 0
        for backup in valid_backups[:to_delete]:
            log(f"Deleting old backup: {backup.name}")
            try:
                if backup.is_dir():
                    shutil.rmtree(backup)
                else:
                    backup.unlink()
                deleted += 1
            except Exception as e:
                err(f"Failed to delete {backup.name}: {e}")
        
        log(f"Deleted {deleted} old backup(s)")
    else:
        log("Backup count within retention limit, no deletion needed")
    
    # Count backups after processing
    total_after = len(list(backup_path.iterdir()))
    log(f"Processing completed. Renamed: {renamed}, Total backups: {total_after}")
    
    # Show disk usage
    try:
        result = subprocess.run(
            ["du", "-sh", backup_dir],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            disk_usage = result.stdout.split()[0]
            log(f"Current backup directory size: {disk_usage}")
    except Exception:
        pass


def setup() -> None:
    """Setup automatic backup cleanup with systemd timer."""
    need_root()
    
    log("Setting up automatic backup rename with retention (local backups)")
    
    backup_dir = prompt_default("Backup directory", DEFAULT_BACKUP_DIR)
    retention_days_str = prompt_default("Max number of backups to keep", str(DEFAULT_RETENTION_DAYS))
    
    # Validate inputs
    backup_path = Path(backup_dir)
    if not backup_path.exists():
        if confirm_default_yes(f"Directory {backup_dir} does not exist. Create it?"):
            try:
                backup_path.mkdir(parents=True, exist_ok=True)
                log(f"Created directory: {backup_dir}")
            except Exception as e:
                die(f"Failed to create directory: {e}")
        else:
            die(f"Backup directory does not exist: {backup_dir}")
    
    try:
        retention_days = int(retention_days_str)
        if retention_days < 1:
            raise ValueError
    except ValueError:
        die(f"Invalid retention count: {retention_days_str}")
    
    # Get script path
    script_path = os.path.realpath(__file__)
    
    # Create systemd service
    service_file = "/etc/systemd/system/checkmk-backup-cleanup.service"
    log(f"Creating systemd service: {service_file}")
    
    service_content = f"""[Unit]
Description=CheckMK Backup Rename Service
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {script_path} run-internal {backup_dir} {retention_days}
Nice=19
IOSchedulingClass=idle

[Install]
WantedBy=multi-user.target"""
    
    try:
        with open(service_file, "w") as f:
            f.write(service_content)
    except Exception as e:
        die(f"Failed to create service file: {e}")
    
    # Create systemd timer
    timer_file = "/etc/systemd/system/checkmk-backup-cleanup.timer"
    log(f"Creating systemd timer: {timer_file}")
    
    timer_content = """[Unit]
Description=CheckMK Backup Rename Timer (Every Minute)

[Timer]
OnCalendar=*:0/1
Persistent=true

[Install]
WantedBy=timers.target"""
    
    try:
        with open(timer_file, "w") as f:
            f.write(timer_content)
    except Exception as e:
        die(f"Failed to create timer file: {e}")
    
    # Reload and enable
    try:
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "checkmk-backup-cleanup.timer"], check=True)
        subprocess.run(["systemctl", "start", "checkmk-backup-cleanup.timer"], check=True)
    except subprocess.CalledProcessError as e:
        die(f"Failed to enable/start timer: {e}")
    
    log("")
    log("Setup completed!")
    log("Configuration:")
    log(f"  - Backup directory: {backup_dir}")
    log(f"  - Max backups to keep: {retention_days}")
    log("  - Mode: Rename -complete backups, delete oldest if exceeding limit")
    log("  - Schedule: Every minute (checks for -complete suffix)")
    log("")
    log("Timer status:")
    
    try:
        subprocess.run(["systemctl", "status", "checkmk-backup-cleanup.timer", "--no-pager"])
    except Exception:
        pass
    
    log("")
    log("Manual commands:")
    log(f"  Run rename now:         {sys.argv[0]} run")
    log("  Check timer status:     systemctl status checkmk-backup-cleanup.timer")
    log("  Check service logs:     journalctl -u checkmk-backup-cleanup.service")
    log(f"  Remove cleanup:         {sys.argv[0]} remove")


def run() -> None:
    """Run cleanup manually (reads config from systemd service if exists)."""
    need_root()
    
    backup_dir = DEFAULT_BACKUP_DIR
    retention_days = DEFAULT_RETENTION_DAYS
    
    service_file = Path("/etc/systemd/system/checkmk-backup-cleanup.service")
    if service_file.exists():
        try:
            content = service_file.read_text()
            # Extract parameters from ExecStart line
            for line in content.splitlines():
                if line.startswith("ExecStart="):
                    parts = line.split()
                    if len(parts) >= 5:
                        backup_dir = parts[3]
                        retention_days = int(parts[4])
                    break
        except Exception:
            pass
    else:
        log("No systemd service found. Using defaults or run 'setup' first.")
        backup_dir = prompt_default("Backup directory", DEFAULT_BACKUP_DIR)
        retention_days_str = prompt_default("Max backups to keep", str(DEFAULT_RETENTION_DAYS))
        try:
            retention_days = int(retention_days_str)
        except ValueError:
            die(f"Invalid retention count: {retention_days_str}")
    
    cleanup_backups(backup_dir, retention_days)


def run_internal(backup_dir: str, retention_days: int) -> None:
    """Run cleanup internally (called by systemd service).
    
    Args:
        backup_dir: Backup directory path
        retention_days: Number of backups to keep"""
    cleanup_backups(backup_dir, retention_days)


def remove() -> None:
    """Remove automatic backup cleanup (systemd timer/service)."""
    need_root()
    
    log("Removing automatic backup cleanup")
    
    timer_file = Path("/etc/systemd/system/checkmk-backup-cleanup.timer")
    service_file = Path("/etc/systemd/system/checkmk-backup-cleanup.service")
    
    if timer_file.exists() or service_file.exists():
        try:
            subprocess.run(["systemctl", "stop", "checkmk-backup-cleanup.timer"], 
                         stderr=subprocess.DEVNULL)
            subprocess.run(["systemctl", "disable", "checkmk-backup-cleanup.timer"], 
                         stderr=subprocess.DEVNULL)
            
            if timer_file.exists():
                timer_file.unlink()
            if service_file.exists():
                service_file.unlink()
            
            subprocess.run(["systemctl", "daemon-reload"], check=True)
            
            log("Cleanup timer and service removed.")
        except Exception as e:
            err(f"Error during removal: {e}")
    else:
        log("No cleanup timer/service found.")
    
    log("Remove completed.")


def print_usage() -> None:
    """Print usage information."""
    print(f"""CheckMK Backup Cleanup Tool - Version {VERSION}

Usage:
  {sys.argv[0]} setup # Setup automatic cleanup
  {sys.argv[0]} run # Run cleanup manually
  {sys.argv[0]} remove # Remove automatic cleanup

Configuration:
  Default backup directory: {DEFAULT_BACKUP_DIR}
  Default retention: {DEFAULT_RETENTION_DAYS} days
  Log file: {LOGFILE}

Examples:
  # Setup automatic cleanup with defaults
  {sys.argv[0]} setup

  # Run cleanup manually
  {sys.argv[0]} run

  # Remove automatic cleanup
  {sys.argv[0]} remove""")


def main() -> int:
    """Main entry point.
    
    Returns:
        Exit code (0=success, 1=error)"""
    if len(sys.argv) < 2:
        print_usage()
        return 1
    
    command = sys.argv[1]
    
    if command == "setup":
        setup()
    elif command == "run":
        run()
    elif command == "run-internal":
        if len(sys.argv) < 4:
            die("run-internal requires backup_dir and retention_days")
        backup_dir = sys.argv[2]
        retention_days = int(sys.argv[3])
        run_internal(backup_dir, retention_days)
    elif command == "remove":
        remove()
    elif command in ["-h", "--help", "help"]:
        print_usage()
    else:
        print_usage()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
