#!/usr/bin/env python3
"""checkmk_manage_job01_weekly.py - CheckMK Job01 Weekly Backup Management

Manages weekly full CheckMK backups (job01-complete):
- Direct upload without compression (362M)
- Uploads to DigitalOcean Spaces cloud storage
- Retention: 5 backups (local + cloud)

Version: 1.0.0"""

import sys
import os
import subprocess
import shutil
import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional

VERSION = "1.0.0"

# Configuration
BACKUP_DIR = "/var/backups/checkmk"
SITE = "monitoring"
BACKUP_PATTERN = "*job01-complete*"
RETENTION_LOCAL = 5
RETENTION_CLOUD = 5
RCLONE_REMOTE = "do:testmonbck"
RCLONE_PATH = "checkmk-backups/job01-weekly"
LOG_FILE = "/var/log/checkmk-backup-job01.log"


def log(message: str) -> None:
    """Log message to stdout and log file.
    
    Args:
        message: Message to log"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {message}"
    print(formatted)
    
    try:
        with open(LOG_FILE, "a") as f:
            f.write(formatted + "\n")
    except Exception:
        pass


def error(message: str) -> None:
    """Log error and exit.
    
    Args:
        message: Error message"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}]  ERROR: {message}"
    print(formatted, file=sys.stderr)
    
    try:
        with open(LOG_FILE, "a") as f:
            f.write(formatted + "\n")
    except Exception:
        pass
    
    sys.exit(1)


def run_command(cmd: List[str], check: bool = True, capture_output: bool = False,
                shell: bool = False, timeout: int = 300) -> subprocess.CompletedProcess:
    """Execute a shell command."""
    try:
        if shell:
            return subprocess.run(
                cmd if isinstance(cmd, str) else " ".join(cmd),
                shell=True,
                check=check,
                capture_output=capture_output,
                text=True,
                timeout=timeout
            )
        else:
            return subprocess.run(
                cmd,
                check=check,
                capture_output=capture_output,
                text=True,
                timeout=timeout
            )
    except subprocess.CalledProcessError as e:
        if check:
            error(f"Command failed: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
        return e
    except subprocess.TimeoutExpired:
        error(f"Command timeout: {' '.join(cmd) if isinstance(cmd, list) else cmd}")


def check_dependencies() -> None:
    """Check required dependencies."""
    if not shutil.which("rclone"):
        error("rclone not found")


def find_unprocessed_backup() -> Optional[Path]:
    """Find job01-complete backup without timestamp (unprocessed).
    
    Returns:
        Path to backup or None if not found"""
    log(" Searching for unprocessed job01-complete backup...")
    
    backup_path = Path(BACKUP_DIR)
    if not backup_path.exists():
        return None
    
    # Find backup without timestamp pattern (YYYY-MM-DD-HHhMM)
    for item in backup_path.iterdir():
        if item.is_dir() and "job01-complete" in item.name:
            # Check if it doesn't have timestamp
            if not re.search(r'-\d{4}-\d{2}-\d{2}-\d{2}h\d{2}$', item.name):
                return item
    
    return None


def get_backup_size(backup_path: Path, site: str) -> str:
    """Get human-readable backup size.
    
    Args:
        backup_path: Path to backup directory
        site: Site name
        
    Returns:
        Human-readable size string"""
    site_tar = backup_path / f"site-{site}.tar.gz"
    
    if not site_tar.exists():
        return "N/A"
    
    try:
        result = run_command(["du", "-h", str(site_tar)], capture_output=True)
        return result.stdout.split()[0]
    except Exception:
        return "N/A"


def rename_with_timestamp(backup_path: Path) -> Path:
    """Rename backup with timestamp of modification time.
    
    Args:
        backup_path: Current backup path
        
    Returns:
        New backup path"""
    # Get backup modification time
    mtime = backup_path.stat().st_mtime
    timestamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d-%Hh%M")
    
    new_name = f"{backup_path.name}-{timestamp}"
    new_path = backup_path.parent / new_name
    
    backup_path.rename(new_path)
    log(f" Renamed to: {new_name}")
    
    return new_path


def upload_to_cloud(backup_path: Path, site: str) -> None:
    """Upload full backup to cloud using rclone (no compression).
    
    Args:
        backup_path: Backup directory path
        site: Site name"""
    log("  Uploading to cloud (full backup, no compression)...")
    
    rclone_config = f"/opt/omd/sites/{site}/.config/rclone/rclone.conf"
    
    try:
        result = run_command([
            "su", "-", site, "-c",
            f"rclone copy '{backup_path}' '{RCLONE_REMOTE}/{RCLONE_PATH}/{backup_path.name}/' "
            f"--progress --s3-no-check-bucket --config=$HOME/.config/rclone/rclone.conf"
        ], capture_output=True)
        
        # Append rclone output to log file
        if result.returncode == 0:
            log(" Upload completed")
        else:
            error("Upload failed")
    except Exception as e:
        error(f"Upload failed: {e}")


def apply_local_retention(retention: int) -> int:
    """Apply retention policy to local backups.
    
    Args:
        retention: Number of backups to keep
        
    Returns:
        Number of local backups after retention"""
    log(f"  Applying local retention (keep last {retention})...")
    
    backup_path = Path(BACKUP_DIR)
    
    # Find all job01-complete backups
    backups = sorted(
        [b for b in backup_path.iterdir() if b.is_dir() and "job01-complete" in b.name],
        key=lambda b: b.stat().st_mtime,
        reverse=True
    )
    
    if len(backups) > retention:
        for old_backup in backups[retention:]:
            log(f"    Removing old backup: {old_backup.name}")
            shutil.rmtree(old_backup)
        
        removed = len(backups) - retention
        log(f" Local retention applied: removed {removed} old backups")
    else:
        log(f" Local retention OK: {len(backups)} backups (max {retention})")
    
    return min(len(backups), retention)


def apply_cloud_retention(retention: int, site: str) -> int:
    """Apply retention policy to cloud backups.
    
    Args:
        retention: Number of backups to keep
        site: Site name
        
    Returns:
        Number of cloud backups after retention"""
    log(f"  Applying cloud retention (keep last {retention})...")
    
    try:
        # List cloud backups
        result = run_command([
            "su", "-", site, "-c",
            f"rclone lsf '{RCLONE_REMOTE}/{RCLONE_PATH}/' --dirs-only "
            f"--config=$HOME/.config/rclone/rclone.conf"
        ], capture_output=True)
        
        backups = sorted([b.strip() for b in result.stdout.split('\n') if b.strip()], reverse=True)
        
        if len(backups) > retention:
            for old_backup in backups[retention:]:
                log(f"    Removing old cloud backup: {old_backup}")
                run_command([
                    "su", "-", site, "-c",
                    f"rclone purge '{RCLONE_REMOTE}/{RCLONE_PATH}/{old_backup}' "
                    f"--config=$HOME/.config/rclone/rclone.conf"
                ], capture_output=True)
            
            removed = len(backups) - retention
            log(f" Cloud retention applied: removed {removed} old backups")
        else:
            log(f" Cloud retention OK: {len(backups)} backups (max {retention})")
        
        return min(len(backups), retention)
    
    except Exception as e:
        error(f"Cloud retention failed: {e}")


def main() -> int:
    """Main entry point.
    
    Returns:
        Exit code (0=success, 1=error)"""
    log("============================================")
    log("CheckMK Job01 Weekly Backup Management")
    log("============================================")
    
    # Check dependencies
    check_dependencies()
    
    # Find unprocessed backup
    backup = find_unprocessed_backup()
    
    if not backup:
        log("  No job01-complete backup found, exiting")
        return 0
    
    log(f" Found: {backup.name}")
    
    # Get backup size
    backup_size = get_backup_size(backup, SITE)
    log(f" Backup size: {backup_size}")
    
    # Check if already processed (has timestamp)
    if re.search(r'-\d{4}-\d{2}-\d{2}-\d{2}h\d{2}$', backup.name):
        log(" Backup already processed (has timestamp)")
    else:
        # Rename with timestamp
        backup = rename_with_timestamp(backup)
    
    # Upload to cloud (full, no compression)
    upload_to_cloud(backup, SITE)
    
    # Apply local retention
    local_count = apply_local_retention(RETENTION_LOCAL)
    
    # Apply cloud retention
    cloud_count = apply_cloud_retention(RETENTION_CLOUD, SITE)
    
    log("============================================")
    log(" Job01 Weekly Backup Management Completed")
    log("============================================")
    log(f"Backup: {backup.name}")
    log(f"Size: {backup_size} (full, uncompressed)")
    log(f"Local backups: {local_count}/{RETENTION_LOCAL}")
    log(f"Cloud backups: {cloud_count}/{RETENTION_CLOUD}")
    log("============================================")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
