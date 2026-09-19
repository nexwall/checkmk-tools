#!/usr/bin/env python3
"""checkmk_backup.py - CheckMK Disaster Recovery Backup Tool

Performs a complete backup of a CheckMK site for Disaster Recovery.
Includes configuration, var data, and local extensions.
Support upload to remote storage via Rclone.

Features:
- OMD site auto-detect
- Advanced metadata collection (JSON)
- Smart exclusion of unnecessary files
- Rclone upload integrated with retention policy
- Generation of restore instructions

Usage:
    checkmk_backup.py [site_name] [options]

Options:
    --no-upload Skip rclone uploads
    --include-rrd Include historical RRD data (warning: large size)
    --debug Enable verbose logging

Env Vars:
    RCLONE_REMOTE rclone remote name (default: do:testmonbck)
    RCLONE_PATH Remote path (default: checkmk-backups/monitoring)
    RETENTION_DAYS Retention days (default: 30)

Version: 1.0.0"""

import sys
import os
import shutil
import tarfile
import json
import subprocess
import hashlib
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

# --- Default Configuration ---
DEFAULT_RCLONE_REMOTE = "do:testmonbck"
DEFAULT_RCLONE_PATH = "checkmk-backups/monitoring"
DEFAULT_RETENTION_DAYS = 30
BACKUP_BASE_DIR = Path("/opt/checkmk-backup")
LOG_FILE = BACKUP_BASE_DIR / "backup-dr.log"

# --- Colori ---
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'

# --- Logger ---
def log(msg: str, level: str = "INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] [{level}] {msg}"
    print(formatted_msg)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(formatted_msg + "\n")
    except Exception:
        pass

# --- Helper Functions ---
def run_command(cmd: List[str], user: Optional[str] = None, check: bool = True, capture_output: bool = True) -> subprocess.CompletedProcess:
    """Run a command, optionally as another user"""
    if user:
        cmd = ["su", "-", user, "-c", " ".join(f"'{c}'" for c in cmd)]
    
    try:
        result = subprocess.run(
            cmd,
            check=check,
            text=True,
            capture_output=capture_output
        )
        return result
    except subprocess.CalledProcessError as e:
        log(f"Errore comando: {' '.join(cmd)}\nStderr: {e.stderr}", "ERROR")
        raise

def get_omd_site(arg_site: Optional[str] = None) -> str:
    """Detect the OMD site"""
    if arg_site:
        return arg_site
    
    try:
        result = run_command(["omd", "sites"], capture_output=True)
        sites = [line.split()[0] for line in result.stdout.splitlines() if not line.startswith("SITE")]
        
        if not sites:
            log("Nessun site CheckMK trovato", "ERROR")
            sys.exit(1)
            
        if len(sites) == 1:
            log(f"Auto-detect site: {sites[0]}", "INFO")
            return sites[0]
        else:
            log(f"Trovati {len(sites)} site, uso: {sites[0]}", "INFO")
            return sites[0]
            
    except shutil.Error:
        log("Comando 'omd' non trovato", "ERROR")
        sys.exit(1)

def check_rclone(site: str, remote: str) -> bool:
    """Check rclone configuration"""
    if not shutil.which("rclone"):
        log("Rclone non installato", "ERROR")
        return False
    
    remote_name = remote.split(':')[0]
    try:
        # Check if the remote is configured for the site user
        result = run_command(["rclone", "listremotes"], user=site, capture_output=True)
        if f"{remote_name}:" in result.stdout:
            log(f"Rclone remote '{remote_name}' configurato OK", "INFO")
            return True
        else:
            log(f"Remote '{remote_name}' non trovato per utente {site}", "ERROR")
            return False
    except Exception as e:
        log(f"Errore verifica rclone: {e}", "ERROR")
        return False

def collect_metadata(site: str, site_base: Path) -> Dict[str, Any]:
    """Collects system and site metadata"""
    metadata = {
        "timestamp": datetime.now().isoformat(),
        "hostname": os.uname().nodename,
        "site": site,
        "os_info": {},
        "checkmk_info": {},
        "stats": {}
    }
    
    # OS Info
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME"):
                    metadata["os_info"]["pretty_name"] = line.split("=")[1].strip().strip('"')
    except:
        metadata["os_info"]["pretty_name"] = "Unknown"
        
    metadata["os_info"]["kernel"] = os.uname().release
    
    # CheckMK Info
    try:
        version_file = site_base / "version"
        if version_file.exists():
            metadata["checkmk_info"]["version"] = version_file.read_text().strip()
    except:
        pass
        
    # Stats
    try:
        du_site = subprocess.check_output(["du", "-sh", str(site_base)], text=True).split()[0]
        metadata["stats"]["site_size"] = du_site
    except:
        pass
        
    return metadata

def create_restore_instructions(backup_file: str, checksum: str, site: str):
    """Generate restore instruction files"""
    content = f"""=== DISASTER RECOVERY RESTORE INSTRUCTIONS ===

1. PREREQUISITES:
   - CheckMK installed (same version)
   - OMD site created: `omd create {site}`
   - Site stopped: `omd stop {site}`

2. PROCEDURE:
   # Stop the site
   omd stop {site}

   # Extract backup
   tar xzf {backup_file} -C /opt/omd/sites/{site}/

   # Reset permissions
   chown -R {site}:{site} /opt/omd/sites/{site}

   # Verify Checksum
   # Expected: {checksum}
   sha256sum {backup_file}

   # Restart
   omd start {site}
   
   # Recompile configuration
   su - {site} -c "cmk -R"

3. NOTES:
   - Configure /opt/ydea-toolkit/.env if necessary
   - Reinstall any lost cronjobs"""
    return content

class BackupManager:
    def __init__(self, site: str, args):
        self.site = site
        self.args = args
        self.site_base = Path(f"/opt/omd/sites/{site}")
        self.tmp_dir = BACKUP_BASE_DIR / "tmp"
        
        # Config
        self.rclone_remote = os.environ.get("RCLONE_REMOTE", DEFAULT_RCLONE_REMOTE)
        self.rclone_path = os.environ.get("RCLONE_PATH", DEFAULT_RCLONE_PATH)
        self.retention_days = int(os.environ.get("RETENTION_DAYS", DEFAULT_RETENTION_DAYS))
        
        # Filenames
        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.archive_name = f"checkmk-DR-{site}-{date_str}.tgz"
        self.metadata_name = f"checkmk-DR-{site}-{date_str}.json"
        
        # Setup dirs
        BACKUP_BASE_DIR.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def run_backup(self):
        log(f"=== INIZIO BACKUP DR per site {self.site} ===")
        
        # 1. Raccolta Metadata
        log("Raccolgo metadati...")
        metadata = collect_metadata(self.site, self.site_base)
        metadata_file = self.tmp_dir / self.metadata_name
        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)
            
        # 2. File Selection
        backup_items = [
            "etc/check_mk", "etc/omd", "etc/apache", "etc/ssl", 
            "etc/htpasswd", "etc/auth.secret", "etc/auth.serials", "etc/environment",
            "var/check_mk/web", "var/check_mk/wato", "var/check_mk/agents", 
            "var/check_mk/packages", "var/check_mk/inventory_archive",
            "local", "version", ".version"
        ]
        
        if self.args.include_rrd:
            log("Includo RRD (backup dimensionale!)", "WARNING")
            backup_items.extend(["var/check_mk/rrd", "var/pnp4nagios/perfdata"])
            
        # 3. Creazione Tarball
        archive_path = self.tmp_dir / self.archive_name
        log(f"Creo archivio: {self.archive_name}")
        
        try:
            with tarfile.open(archive_path, "w:gz") as tar:
                # Aggiungi metadata
                tar.add(metadata_file, arcname="backup_metadata.json")
                
                # Add site items
                for item in backup_items:
                    full_path = self.site_base / item
                    if full_path.exists():
                        log(f"   + {item}")
                        tar.add(full_path, arcname=item)
                    else:
                        log(f"   - {item} (skip)", "debug" if not self.args.debug else "INFO")
                        
        except Exception as e:
            log(f"Errore creazione tar: {e}", "ERROR")
            return False
            
        # 4. Checksum
        log("Calcolo checksum...")
        sha256 = hashlib.sha256()
        with open(archive_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)
        checksum = sha256.hexdigest()
        log(f"SHA256: {checksum}")
        
        # 5. Restore Instructions
        instructions = create_restore_instructions(self.archive_name, checksum, self.site)
        instr_file = self.tmp_dir / "RESTORE_INSTRUCTIONS.txt"
        instr_file.write_text(instructions)
        
        # 6. Upload
        if not self.args.no_upload:
            if check_rclone(self.site, self.rclone_remote):
                self.upload_backup(archive_path, metadata_file, instr_file)
                self.cleanup_remote()
            else:
                log("Upload saltato (rclone non configurato)", "WARNING")
        
        # 7. Cleanup Locale
        log("Pulizia file temporanei locali...")
        if archive_path.exists(): os.remove(archive_path)
        if metadata_file.exists(): os.remove(metadata_file)
        if instr_file.exists(): os.remove(instr_file)
        
        log(f"=== BACKUP COMPLETATO ===")
        return True

    def upload_backup(self, archive: Path, metadata: Path, instr: Path):
        log(f"Upload su {self.rclone_remote}:{self.rclone_path}...")
        
        dest = f"{self.rclone_remote}:{self.rclone_path}"
        rclone_conf = f"/opt/omd/sites/{self.site}/.config/rclone/rclone.conf"
        
        files = [archive, metadata, instr]
        
        for f in files:
            cmd = [
                "rclone", "copy", str(f), dest,
                f"--config={rclone_conf}",
                "--checksum", "--immutable"
            ]
            try:
                run_command(cmd, user=self.site)
                log(f"Uploaded: {f.name}")
            except Exception as e:
                log(f"Upload fallito per {f.name}: {e}", "ERROR")

    def cleanup_remote(self):
        log(f"Applico retention policy ({self.retention_days} giorni)...")
        
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        
        dest = f"{self.rclone_remote}:{self.rclone_path}"
        rclone_conf = f"/opt/omd/sites/{self.site}/.config/rclone/rclone.conf"
        
        # List files with time
        cmd = ["rclone", "lsf", dest, "--format", "tp", f"--config={rclone_conf}"]
        try:
            result = run_command(cmd, user=self.site, capture_output=True)
            for line in result.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) != 2: continue
                
                time_str, filename = parts
                # rclone output format: 2023-01-01 12:00:00; filename
                try:
                    file_date_str = time_str.split(" ")[0]
                    if file_date_str < cutoff_str and (filename.endswith(".tgz") or filename.endswith(".json")):
                        log(f"Rimuovo file obsoleto: {filename}")
                        del_cmd = ["rclone", "delete", f"{dest}/{filename}", f"--config={rclone_conf}"]
                        run_command(del_cmd, user=self.site)
                except Exception:
                    pass
        except Exception as e:
            log(f"Errore retention: {e}", "WARNING")


def main():
    parser = argparse.ArgumentParser(description="CheckMK DR Backup")
    parser.add_argument("site", nargs="?", help="CheckMK site name")
    parser.add_argument("--no-upload", action="store_true", help="Skip rclone upload")
    parser.add_argument("--include-rrd", action="store_true", help="Include RRD data (huge!)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    site = get_omd_site(args.site)
    manager = BackupManager(site, args)
    
    if not manager.run_backup():
        sys.exit(1)

if __name__ == "__main__":
    main()
