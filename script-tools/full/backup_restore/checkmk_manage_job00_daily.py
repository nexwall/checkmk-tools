#!/usr/bin/env python3
"""checkmk_manage_job00_daily.py - CheckMK Job00 Daily Backup Management

Manages daily compressed CheckMK backups (job00-complete):
- Compresses from 362M to 1.2M using tar --delete
- Uploads to DigitalOcean Spaces cloud storage
- Retention: 90 backups (local + cloud)

Version: 1.0.0"""

import sys
import os
import subprocess
import shutil
import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple

VERSION = "1.0.0"

# Configuration
BACKUP_DIR = "/var/backups/checkmk"
SITE = "monitoring"
BACKUP_PATTERN = "*job00-complete*"
RETENTION_LOCAL = 90
RETENTION_CLOUD = 90
TMP_DIR = "/opt/checkmk-backup/tmp"
RCLONE_REMOTE = "do:testmonbck"
RCLONE_PATH = "checkmk-backups/job00-daily"
LOG_FILE = "/var/log/checkmk-backup-job00.log"


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
    if not shutil.which("tar"):
        error("tar not found")


def find_unprocessed_backup() -> Optional[Path]:
    """Find job00-complete backup without timestamp (unprocessed).
    
    Returns:
        Path to backup or None if not found"""
    log(" Searching for unprocessed job00-complete backup...")
    
    backup_path = Path(BACKUP_DIR)
    if not backup_path.exists():
        return None
    
    # Find backup without timestamp pattern (YYYY-MM-DD-HHhMM)
    for item in backup_path.iterdir():
        if item.is_dir() and "job00-complete" in item.name:
            # Check if it doesn't have timestamp
            if not re.search(r'-\d{4}-\d{2}-\d{2}-\d{2}h\d{2}$', item.name):
                return item
    
    return None


def compress_backup(backup_path: Path, site: str) -> Tuple[str, str]:
    """Compress backup by removing heavy directories.
    
    Args:
        backup_path: Path to backup directory
        site: Site name
        
    Returns:
        Tuple of (original_size, compressed_size)"""
    log(" Starting compression...")
    
    tmp_path = Path(TMP_DIR)
    tmp_path.mkdir(parents=True, exist_ok=True)
    
    site_tar = backup_path / f"site-{site}.tar.gz"
    work_targz = tmp_path / f"site-{site}.tar.gz"
    work_tar = tmp_path / f"site-{site}.tar"
    
    if not site_tar.exists():
        error(f"Site tar not found: {site_tar}")
    
    # Copy to tmp
    shutil.copy2(site_tar, work_targz)
    
    # Get original size
    original_size = site_tar.stat().st_size
    
    # Decompress
    log("   Decompressing...")
    run_command(["gunzip", "-f", str(work_targz)])
    
    # Directories to remove (441M -> 1.2M)
    remove_paths = [
        f"{site}/var/nagios",
        f"{site}/checkmk-tools",
        f"{site}/monitoring",
        f"{site}/var/check_mk/crashes",
        f"{site}/var/check_mk/rest_api",
        f"{site}/var/check_mk/precompiled_checks",
        f"{site}/var/check_mk/logwatch",
        f"{site}/var/check_mk/wato/snapshots",
        f"{site}/var/check_mk/wato/log",
        f"{site}/var/check_mk/inventory_archive",
        f"{site}/var/check_mk/background_jobs",
        f"{site}/var/tmp",
        f"{site}/tmp",
    ]
    
    # Remove directories from tar
    log("   Removing heavy components...")
    for path in remove_paths:
        run_command(
            ["tar", "--delete", "-f", str(work_tar), path],
            check=False,
            capture_output=True
        )
    
    # Recompress
    log("   Recompressing...")
    run_command(["gzip", "-f", str(work_tar)])
    
    # Calculate sizes
    compressed_size = work_targz.stat().st_size
    reduction = 100 - (compressed_size * 100 // original_size)
    
    original_size_hr = format_size(original_size)
    compressed_size_hr = format_size(compressed_size)
    
    log(f"   Compressed: {original_size_hr} -> {compressed_size_hr} ({reduction}% reduction)")
    
    # Replace original file
    shutil.move(str(work_targz), str(site_tar))
    
    # Fix ownership
    try:
        import pwd
        site_uid = pwd.getpwnam(site).pw_uid
        site_gid = pwd.getpwnam(site).pw_gid
        os.chown(site_tar, site_uid, site_gid)
        os.chmod(site_tar, 0o600)
    except Exception:
        pass
    
    return original_size_hr, compressed_size_hr


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
    log(f"   Renamed to: {new_name}")
    
    return new_path


def upload_to_cloud(backup_path: Path, site: str) -> None:
    """Upload backup to cloud using rclone.
    
    Args:
        backup_path: Backup directory path
        site: Site name"""
    log("  Uploading to cloud...")
    
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


def apply_local_retention(retention: int) -> None:
    """Apply retention policy to local backups.
    
    Args:
        retention: Number of backups to keep"""
    log(f"  Applying local retention (keep last {retention})...")
    
    backup_path = Path(BACKUP_DIR)
    
    # Find all job00-complete backups
    backups = sorted(
        [b for b in backup_path.iterdir() if b.is_dir() and "job00-complete" in b.name],
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


def apply_cloud_retention(retention: int, site: str) -> None:
    """Apply retention policy to cloud backups.
    
    Args:
        retention: Number of backups to keep
        site: Site name"""
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
    
    except Exception as e:
        error(f"Cloud retention failed: {e}")


def format_size(size_bytes: int) -> str:
    """Format size in bytes to human-readable string."""
    for unit in ['B', 'K', 'M', 'G', 'T']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}P"


def main() -> int:
    """Main entry point.
    
    Returns:
        Exit code (0=success, 1=error)"""
    log("============================================")
    log("CheckMK Job00 Daily Backup Management")
    log("============================================")
    
    # Check dependencies
    check_dependencies()
    
    # Find unprocessed backup
    backup = find_unprocessed_backup()
    
    if not backup:
        log("  No job00-complete backup found, exiting")
        return 0
    
    log(f" Found: {backup.name}")
    
    # Check if already processed (has timestamp)
    if re.search(r'-\d{4}-\d{2}-\d{2}-\d{2}h\d{2}$', backup.name):
        log(" Backup already processed (has timestamp), skipping compression")
        already_processed = True
    else:
        # Compress backup
        compress_backup(backup, SITE)
        
        # Rename with timestamp
        backup = rename_with_timestamp(backup)
        already_processed = False
    
    # Upload to cloud
    upload_to_cloud(backup, SITE)
    
    # Apply local retention
    apply_local_retention(RETENTION_LOCAL)
    
    # Apply cloud retention
    apply_cloud_retention(RETENTION_CLOUD, SITE)
    
    # Count final backups
    backup_path = Path(BACKUP_DIR)
    local_count = len([b for b in backup_path.iterdir() if b.is_dir() and "job00-complete" in b.name])
    
    # Get cloud count
    try:
        result = run_command([
            "su", "-", SITE, "-c",
            f"rclone lsf '{RCLONE_REMOTE}/{RCLONE_PATH}/' --dirs-only "
            f"--config=$HOME/.config/rclone/rclone.conf"
        ], capture_output=True)
        cloud_count = len([b.strip() for b in result.stdout.split('\n') if b.strip()])
    except Exception:
        cloud_count = 0
    
    log("============================================")
    log(" Job00 Daily Backup Management Completed")
    log("============================================")
    log(f"Backup: {backup.name}")
    log(f"Local backups: {local_count}/{RETENTION_LOCAL}")
    log(f"Cloud backups: {cloud_count}/{RETENTION_CLOUD}")
    log("============================================")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
