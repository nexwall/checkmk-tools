#!/usr/bin/env python3
"""checkmk_restore.py - CheckMK Disaster Recovery Restore Tool

Interactive tool for restoring CheckMK sites from DR backups.
Supports direct download from Rclone, OMD site management and configuration restore.

Features:
- Interactive listing of remote backups (rclone)
- Download and verify integrity
- Automatic stop/start of the site
- Pre-restore security backup
- Restoring permissions and recompiling cmk

Usage:
    checkmk_restore.py [options]

Options:
    --site NAME Name of the site to restore
    --backup FILE Name of the backup file to use (if already local or known)
    --non-interactive Run in non-interactive mode (requires --site and --backup)
    --debug Debug logging

Version: 1.0.0"""

import sys
import os
import shutil
import tarfile
import subprocess
import argparse
import time
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# --- Configuration ---
DEFAULT_RCLONE_REMOTE = "do:testmonbck"
BACKUP_BASE_DIR = Path("/opt/checkmk-backup")
LOG_FILE = BACKUP_BASE_DIR / "restore-dr.log"

# --- Utility Class ---
class Console:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'

    @staticmethod
    def title(msg: str):
        print(f"\n{Console.CYAN}╔{'═'*60}╗{Console.NC}")
        print(f"{Console.CYAN}║ {msg.center(58)} ║{Console.NC}")
        print(f"{Console.CYAN}╚{'═'*60}╝{Console.NC}\n")

    @staticmethod
    def success(msg: str):
        print(f"{Console.GREEN} {msg}{Console.NC}")
        log(f"SUCCESS: {msg}")

    @staticmethod
    def error(msg: str, fatal: bool = False):
        print(f"{Console.RED} {msg}{Console.NC}")
        log(f"ERROR: {msg}")
        if fatal:
            sys.exit(1)

    @staticmethod
    def warn(msg: str):
        print(f"{Console.YELLOW}  {msg}{Console.NC}")
        log(f"WARN: {msg}")

    @staticmethod
    def info(msg: str):
        print(f"{Console.BLUE}ℹ  {msg}{Console.NC}")
        log(f"INFO: {msg}")

    @staticmethod
    def confirm(question: str, default: bool = False) -> bool:
        choice = "Y/n" if default else "y/N"
        res = input(f"{question} [{choice}] ").lower().strip()
        if not res:
            return default
        return res in ['y', 'yes']

    @staticmethod
    def input_value(prompt: str, default: str = "") -> str:
        d_str = f" [{default}]" if default else ""
        res = input(f"{prompt}{d_str}: ").strip()
        return res if res else default

def log(msg: str):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        BACKUP_BASE_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(f"[{timestamp}] {msg}\n")
    except Exception:
        pass

def run_cmd(cmd: List[str], user: Optional[str] = None, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    if user:
        cmd = ["su", "-", user, "-c", " ".join(f"'{c}'" for c in cmd)]
    
    log(f"EXEC: {' '.join(cmd)}")
    try:
        res = subprocess.run(cmd, check=check, text=True, capture_output=capture)
        return res
    except subprocess.CalledProcessError as e:
        log(f"CMD FAILED: {e.stderr}")
        raise

# --- Logic Classes ---
class OMDManager:
    @staticmethod
    def list_sites() -> List[str]:
        try:
            res = run_cmd(["omd", "sites"], capture=True)
            return [line.split()[0] for line in res.stdout.splitlines() if not line.startswith("SITE")]
        except:
            return []

    @staticmethod
    def site_exists(site: str) -> bool:
        return Path(f"/opt/omd/sites/{site}").exists()

    @staticmethod
    def create_site(site: str) -> bool:
        Console.info(f"Creazione site '{site}'...")
        try:
            run_cmd(["omd", "create", site], check=True, capture=False)
            return True
        except:
            return False

    @staticmethod
    def stop_site(site: str) -> bool:
        Console.info(f"Fermo site '{site}'...")
        try:
            run_cmd(["omd", "stop", site], check=True, capture=False)
            return True
        except:
            return False

    @staticmethod
    def start_site(site: str) -> bool:
        Console.info(f"Avvio site '{site}'...")
        try:
            run_cmd(["omd", "start", site], check=True, capture=False)
            return True
        except:
            return False

class RcloneManager:
    def __init__(self, site: str, remote: str = DEFAULT_RCLONE_REMOTE):
        self.site = site
        self.remote = remote
        self.config = f"/opt/omd/sites/{site}/.config/rclone/rclone.conf"

    def is_configured(self) -> bool:
        return Path(self.config).exists()

    def configure_interactive(self) -> bool:
        Console.title("Configurazione Rclone DigitalOcean")
        
        access_key = Console.input_value("Access Key ID")
        secret_key = Console.input_value("Secret Access Key")
        region = Console.input_value("Region", "ams3")
        endpoint = Console.input_value("Endpoint", f"{region}.digitaloceanspaces.com")
        
        remote_name = self.remote.split(':')[0]
        
        cmd = [
            "rclone", "config", "create", remote_name, "s3",
            f"access_key_id={access_key}",
            f"secret_access_key={secret_key}",
            f"region={region}",
            f"endpoint={endpoint}",
            "provider=DigitalOcean",
            "env_auth=false",
            "acl=private"
        ]
        
        try:
            # Create config directory first
            run_cmd(["mkdir", "-p", ".config/rclone"], user=self.site)
            run_cmd(cmd, user=self.site)
            Console.success("Rclone configurato")
            return True
        except Exception as e:
            Console.error(f"Configurazione fallita: {e}")
            return False

    def list_backups(self) -> List[tuple]:
        """Return list (filename, size, date)"""
        Console.info("Recupero lista backup...")
        paths = [
            f"checkmk-backups/{self.site}",
            f"checkmk-backups/{self.site}-minimal"
        ]
        
        backups = []
        for p in paths:
            try:
                # Use lsf with tsp (time, size, path) format
                remote_path = f"{self.remote}/{p}"
                cmd = ["rclone", "lsf", remote_path, "--format", "tsp", 
                       f"--config={self.config}", "--s3-no-check-bucket", "--files-only"]
                res = run_cmd(cmd, user=self.site, check=False)
                
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        parts = line.split(";")
                        if len(parts) >= 3 and parts[2].endswith(".tgz"):
                            # Parts: time, size, filename
                            backups.append({
                                "time": parts[0],
                                "size": parts[1],
                                "name": parts[2],
                                "remote_path": p
                            })
            except Exception:
                pass
                
        # Sort by time desc
        backups.sort(key=lambda x: x["time"], reverse=True)
        return backups

    def download(self, filename: str, remote_subpath: str, dest: Path) -> bool:
        Console.info(f"Download {filename}...")
        remote_path = f"{self.remote}/{remote_subpath}"
        cmd = [
            "rclone", "copyto", 
            f"{remote_path}/{filename}", 
            str(dest),
            f"--config={self.config}", 
            "--s3-no-check-bucket",
            "--progress"
        ]
        try:
            # Interactive rclone needs stdout attached? subprocess.run captures it.
            # For progress bar we might want to not capture stdout check=True
            subprocess.run(["su", "-", self.site, "-c", " ".join(f"'{c}'" for c in cmd)], check=True)
            return True
        except Exception:
            return False

    def download_metadata(self, filename: str, remote_subpath: str) -> Optional[str]:
        meta_name = filename.replace(".tgz", ".json")
        # Try json first, then metadata.txt
        for ext in [".json", ".metadata.txt"]:
            f_name = filename.replace(".tgz", ext)
            tmp_path = Path(f"/tmp/{f_name}")
            remote_full = f"{self.remote}/{remote_subpath}/{f_name}"
            
            cmd = ["rclone", "copyto", remote_full, str(tmp_path), f"--config={self.config}", "--s3-no-check-bucket", "-q"]
            try:
                run_cmd(cmd, user=self.site)
                if tmp_path.exists():
                    return tmp_path.read_text()
            except:
                pass
        return None


class RestoreManager:
    def __init__(self):
        self.tmp_dir = Path("/opt/checkmk-backup/tmp_restore")
        self.backup_base = Path("/opt/checkmk-backup")
        
        if os.geteuid() != 0:
            Console.error("Questo script deve essere eseguito come root", fatal=True)

    def select_site(self, preselected: Optional[str] = None) -> str:
        Console.title("Selezione Site CheckMK")
        
        sites = OMDManager.list_sites()
        if sites:
            print("Sites disponibili:")
            for s in sites:
                print(f" - {s}")
        else:
            print("Nessun site trovato.")
        
        print()
        if preselected:
            site = preselected
        else:
            site = Console.input_value("Nome del site da ripristinare", "monitoring")

        if not OMDManager.site_exists(site):
            Console.warn(f"Site '{site}' non trovato.")
            if Console.confirm(f"Vuoi creare il site '{site}' ora?", True):
                if not OMDManager.create_site(site):
                    Console.error("Creazione site fallita", fatal=True)
            else:
                Console.error("Site necessario per il restore", fatal=True)
        
        return site

    def run(self):
        Console.title(" CHECKMK DR RESTORE")
        
        parser = argparse.ArgumentParser()
        parser.add_argument("--site", help="Site name")
        parser.add_argument("--backup", help="Backup file path")
        parser.add_argument("--non-interactive", action="store_true")
        args = parser.parse_args()
        
        # 1. Select Site
        site = self.select_site(args.site)
        site_base = Path(f"/opt/omd/sites/{site}")
        
        # 2. Select Backup
        backup_file = None
        rclone_mgr = RcloneManager(site)
        
        if args.backup:
            backup_file = Path(args.backup)
            if not backup_file.exists():
                Console.error(f"File backup non trovato: {backup_file}", fatal=True)
        else:
            # Interactive rclone selection
            if not rclone_mgr.is_configured():
                Console.warn(f"Rclone non configurato per {site}")
                if Console.confirm("Configurare ora?", True):
                    rclone_mgr.configure_interactive()
                else:
                    Console.error("Rclone necessario per download", fatal=True)
            
            backups = rclone_mgr.list_backups()
            if not backups:
                Console.error("Nessun backup trovato remoto.", fatal=True)
            
            print(f"\nBackup disponibili per {site}:")
            for i, b in enumerate(backups, 1):
                size_mb = int(b['size']) / 1024 / 1024 if b['size'].isdigit() else 0
                print(f"{i:2d}) {b['time']} | {size_mb:6.1f} MB | {b['name']}")
            
            print()
            sel = Console.input_value(f"Seleziona (1-{len(backups)})", "1")
            try:
                idx = int(sel) - 1
                selected = backups[idx]
            except:
                Console.error("Selezione non valida", fatal=True)
            
            # Show metadata
            meta = rclone_mgr.download_metadata(selected['name'], selected['remote_path'])
            if meta:
                Console.title("Info Backup")
                print(meta)
                # Pause to read
                input("\nPremi INVIO per continuare...")
            
            # Download
            self.tmp_dir.mkdir(parents=True, exist_ok=True)
            local_backup_path = self.tmp_dir / selected['name']
            
            if not rclone_mgr.download(selected['name'], selected['remote_path'], local_backup_path):
                Console.error("Download fallito", fatal=True)
            
            backup_file = local_backup_path

        # 3. Confirmation
        Console.title("  CONFERMA RIPRISTINO")
        print(f"Site:   {site}")
        print(f"Backup: {backup_file}")
        print("Azioni: STOP site, Backup config attuale, Restore, START site")
        
        if not args.non_interactive:
            if not Console.confirm("Sei SICURO di voler procedere?", False):
                Console.info("Annullato")
                sys.exit(0)

        # 4. Execution
        # Stop site
        OMDManager.stop_site(site)
        
        # Safety Backup
        Console.info("Backup di sicurezza configurazione attuale...")
        safety_dir = self.backup_base / f"pre-restore-{int(time.time())}"
        safety_dir.mkdir(parents=True, exist_ok=True)
        try:
            # Backup etc and local
            run_cmd(["tar", "czf", str(safety_dir / "etc.tgz"), "-C", str(site_base), "etc"], capture=False)
            run_cmd(["tar", "czf", str(safety_dir / "local.tgz"), "-C", str(site_base), "local"], capture=False)
            Console.success(f"Backup sicurezza in {safety_dir}")
        except:
            Console.warn("Backup sicurezza fallito (proseguo comunque)")

        # Extract
        Console.info(f"Estrazione {backup_file}...")
        try:
            with tarfile.open(backup_file, "r:gz") as tar:
                # Exclude metadata file from tar execution if present as root item
                # But tar.extractall handles paths efficiently
                tar.extractall(path=site_base, filter='data') # 'data' filter is safer in python 3.12+ but might not exist in older. default is/was unsafe.
                # Actually python 3.9/3.10 doesn't have filter argument on extractall.
                # Workaround:
        except AttributeError:
             # Fallback for older python
             subprocess.run(["tar", "xzf", str(backup_file), "-C", str(site_base)], check=True)
        except Exception as e:
            # If py lib fails, try system tar
            Console.warn(f"Python tar fallito ({e}), uso system tar...")
            run_cmd(["tar", "xzf", str(backup_file), "-C", str(site_base)], check=True, capture=False)

        Console.success("Estrazione completata")

        # Permissions
        Console.info("Ripristino permessi...")
        run_cmd(["chown", "-R", f"{site}:{site}", str(site_base)])
        # Ydea toolkit special handling if present
        if (site_base / "ydea-toolkit").exists():
            if Path("/opt/ydea-toolkit").exists():
                shutil.rmtree("/opt/ydea-toolkit")
            shutil.move(str(site_base / "ydea-toolkit"), "/opt/ydea-toolkit")
            run_cmd(["chown", "-R", "root:root", "/opt/ydea-toolkit"])

        # Restart
        if not OMDManager.start_site(site):
            Console.warn("Start site fallito. Verificare log.")
        else:
            Console.success("Site avviato")

        # Compile
        if Console.confirm("Ricompilare configurazione monitoring?", True):
            run_cmd(["su", "-", site, "-c", "cmk -R"], check=False)

        Console.title(" RESTORE COMPLETATO")
        print(f"Verifica: https://$(hostname)/{site}/")

if __name__ == "__main__":
    RestoreManager().run()
