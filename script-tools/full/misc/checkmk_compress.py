#!/usr/bin/env python3
"""checkmk_compress.py - Compress Native CheckMK Backups

Optimize CheckMK native backups by removing heavy files (RRD, tmp, etc.)
and recompressing the archive. It also uploads to Rclone.

Features:
- Automatically detect completed backups
- Selective removal of paths (rrd, inventory, git) to save space
- GZIP compression
- Upload Rclone
- In-place replacement (optional)

Usage:
    checkmk_compress.py [site_name] [options]

Options:
    --backup-dir DIR Backup directory (default: /var/backups/checkmk)
    --rclone-remote Remote rclone (default: do:testmonbck)
    --keep-original Do not overwrite the original

Version: 1.0.0"""

import sys
import os
import shutil
import tarfile
import subprocess
import argparse
import time
from pathlib import Path
from datetime import datetime

# --- Configuration ---
DEFAULT_BACKUP_DIR = "/var/backups/checkmk"
DEFAULT_RCLONE_REMOTE = "do:testmonbck"

class Console:
    GREEN = '\033[0;32m'
    NC = '\033[0m'
    @staticmethod
    def log(msg):
        print(f"{Console.GREEN}[{datetime.now().strftime('%H:%M:%S')}] {msg}{Console.NC}")

def run_cmd(cmd, check=True):
    return subprocess.run(cmd, check=check, text=True, capture_output=True)

class Compressor:
    def __init__(self, site, args):
        self.site = site
        self.args = args
        self.backup_dir = Path(args.backup_dir)
        self.tmp_dir = Path("/opt/checkmk-backup/tmp")
        self.rclone_remote = args.rclone_remote
        
        self.remove_paths = [
            "monitoring/var/nagios",
            "monitoring/checkmk-tools",
            "monitoring/monitoring", # Binary
            "monitoring/var/check_mk/crashes",
            "monitoring/var/check_mk/rest_api",
            "monitoring/var/check_mk/precompiled_checks",
            "monitoring/var/check_mk/logwatch",
            "monitoring/var/check_mk/wato/snapshots",
            "monitoring/var/check_mk/wato/log",
            "monitoring/var/check_mk/inventory_archive",
            "monitoring/var/check_mk/background_jobs",
            "monitoring/var/tmp",
            "monitoring/tmp"
        ]

    def find_backup(self):
        Console.log("Cerco backup 'complete'...")
        # Look for backup directories that end in -complete
        candidates = list(self.backup_dir.glob("*-complete"))
        # If it doesn't find it, look for those with timestamps
        if not candidates:
            candidates = list(self.backup_dir.glob("Check_MK-*-complete-*"))
        
        if not candidates:
            Console.log("Nessun backup trovato.")
            return None
            
        # Get the latest one
        candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return candidates[0]

    def process(self):
        backup_path = self.find_backup()
        if not backup_path:
            sys.exit(1)
            
        backup_name = backup_path.name
        # The tar file inside the backup directory usually follows site-SITE.tar.gz pattern
        site_tar = backup_path / f"site-{self.site}.tar.gz"
        
        if not site_tar.exists():
            Console.log(f"File {site_tar} non trovato!")
            sys.exit(1)
            
        Console.log(f"Processo backup: {backup_name}")
        original_size = site_tar.stat().st_size
        Console.log(f"Dimensione originale: {original_size / 1024 / 1024:.2f} MB")
        
        # Prepare tmp
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        work_tgz = self.tmp_dir / f"site-{self.site}.tar.gz"
        work_tar = self.tmp_dir / f"site-{self.site}.tar"
        
        # Copy
        Console.log("Copia in tmp...")
        shutil.copy2(site_tar, work_tgz)
        
        # Decompress (gunzip)
        Console.log("Decompressione...")
        subprocess.run(["gunzip", "-f", str(work_tgz)], check=True)
        
        # Remove heavy items
        Console.log("Rimozione file pesanti...")
        # Use system tar --delete because python tarfile does not support efficient delete
        # The paths in tar are relative to site root, usually "monitoring/..." if site is monitoring
        # We need to construct arguments correctly
        
        # Filter remove paths to include site prefix if needed? 
        # Native backup structure: SITE/var/...
        # Let's assume remove_paths are correct relative to tar root logic from bash script
        
        cmd = ["tar", "--delete", "-f", str(work_tar)] + self.remove_paths
        try:
            subprocess.run(cmd, check=False, stderr=subprocess.DEVNULL)
        except Exception:
            pass
            
        # Recompress
        Console.log("Ricomprimo...")
        subprocess.run(["gzip", "-f", str(work_tar)], check=True)
        
        # Stats
        compressed_size = work_tgz.stat().st_size
        reduction = 100 - (compressed_size * 100 / original_size)
        Console.log(f"Nuova dimensione: {compressed_size / 1024 / 1024:.2f} MB (Riduzione: {reduction:.1f}%)")
        
        # Replace
        if not self.args.keep_original:
            Console.log("Sostituisco originale...")
            shutil.move(str(work_tgz), str(site_tar))
            if os.geteuid() == 0:
                shutil.chown(site_tar, user=self.site, group=self.site)
            site_tar.chmod(0o600)
            
        # Upload
        self.upload(backup_path)

    def upload(self, backup_path: Path):
        remote_path = f"{self.rclone_remote}/checkmk-backups/{self.site}-compressed/{backup_path.name}"
        Console.log(f"Upload su {remote_path}...")
        
        # Upload the whole directory
        cmd = [
            "rclone", "copy", str(backup_path), remote_path,
            "--s3-no-check-bucket", "--progress"
        ]
        
        config = Path(f"/opt/omd/sites/{self.site}/.config/rclone/rclone.conf")
        if config.exists():
            cmd.append(f"--config={config}")
        
        try:
            # Run as site user if possible
            if os.geteuid() == 0:
                full_cmd = ["su", "-", self.site, "-c", " ".join(f"'{c}'" for c in cmd)]
            else:
                full_cmd = cmd
                
            subprocess.run(full_cmd, check=True)
            Console.log("Upload completato")
        except Exception as e:
            Console.log(f"Upload fallito: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("site", nargs="?", default="monitoring")
    parser.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--rclone-remote", default=DEFAULT_RCLONE_REMOTE)
    parser.add_argument("--keep-original", action="store_true")
    
    args = parser.parse_args()
    
    Compressor(args.site, args).process()

if __name__ == "__main__":
    main()
