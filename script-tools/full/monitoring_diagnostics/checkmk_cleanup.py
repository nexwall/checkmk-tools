#!/usr/bin/env python3
"""checkmk_cleanup.py - CheckMK Backup Retention & Cleanup Tool

Manages the rotation of CheckMK local backups.
Features:
- Rename completed backups (adding timestamps)
- Apply retention policy (maximum number of backups)
- Automatic systemd timer setup

Usage:
    checkmk_cleanup.py [run|setup|remove] [options]

Options:
    --dir DIR Backup directory (default: /var/backups/checkmk)
    --count N Max number of backups to keep (default: 30)

Version: 1.0.0"""

import sys
import os
import shutil
import time
import argparse
import subprocess
import glob
from pathlib import Path
from datetime import datetime
from typing import List, Optional

# --- Configuration ---
DEFAULT_BACKUP_DIR = "/var/backups/checkmk"
DEFAULT_RETENTION = 30
LOG_FILE = "/var/log/checkmk-backup-cleanup.log"

# --- Utils ---
def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(formatted + "\n")
    except Exception:
        pass

def error(msg: str, fatal: bool = False):
    log(f"ERROR: {msg}")
    if fatal:
        sys.exit(1)

def run_cmd(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=check, text=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        error(f"Comando fallito: {' '.join(cmd)}\n{e.stderr}", fatal=False)
        raise

def is_root():
    return os.geteuid() == 0

# --- Logic ---
def run_cleanup(backup_dir: str, retention: int):
    log(f"Avvio cleanup backup locali (Dir: {backup_dir}, Max: {retention})")
    
    path = Path(backup_dir)
    if not path.exists():
        error(f"Directory non trovata: {backup_dir}", fatal=True)

    # 1. Rename full backups
    # Look for directories that end with -complete
    renamed = 0
    now = time.time()
    
    for item in path.glob("*-complete"):
        if not item.is_dir() and not item.is_file():
            continue
            
        mtime = item.stat().st_mtime
        age = now - mtime
        
        # Ignore backups that are too recent (< 2 min)
        if age < 120:
            log(f"Backup troppo recente ({int(age)}s), skip: {item.name}")
            continue
            
        # Ignore backups that are too small (< 100KB)
        size = sum(f.stat().st_size for f in item.rglob('*')) if item.is_dir() else item.stat().st_size
        if size < 102400:
            log(f"Backup troppo piccolo ({size} bytes), skip: {item.name}")
            continue
            
        # Ignora se ha già timestamp (Check_MK-YYYY-MM-DD-HHhMM-complete)
        # But the bash logic was: rename IF it has NO timestamp AND ends with -complete
        # Bash example: Backup called 'Check_MK-mysite-complete' -> 'Check_MK-mysite-complete-2023...'
        if any(c.isdigit() for c in item.name[-15:]): # Check euristico
             # Se sembra già avere timestamp, skip?
             # Bash regex: -[0-9]{4}-[0-9]{2}-...
             # We assume that if it ends in pure -complete, it should be renamed
             pass

        timestamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d-%Hh%M")
        new_name = f"{item.name}-{timestamp}"
        new_path = path / new_name
        
        try:
            log(f"Rinomino: {item.name} -> {new_name}")
            shutil.move(str(item), str(new_path))
            renamed += 1
        except Exception as e:
            error(f"Errore rinomina {item.name}: {e}")

    log(f"Rinominati {renamed} backup")

    # 2. Rotazione
    # Find all valid backups Check_MK-*
    backups = []
    for item in path.glob("Check_MK-*"):
        if "incomplete" in item.name:
            continue
        backups.append(item)
    
    # Sort by mtime (oldest first)
    backups.sort(key=lambda x: x.stat().st_mtime)
    
    total = len(backups)
    log(f"Backup totali trovati: {total} (Max: {retention})")
    
    if total > retention:
        to_delete = total - retention
        log(f"Cancello {to_delete} backup vecchi...")
        
        for i in range(to_delete):
            b = backups[i]
            log(f"Cancello: {b.name}")
            try:
                if b.is_dir():
                    shutil.rmtree(b)
                else:
                    os.remove(b)
            except Exception as e:
                error(f"Errore cancellazione {b.name}: {e}")
    else:
        log("Nessuna cancellazione necessaria")

def setup_systemd(backup_dir: str, retention: int):
    if not is_root():
        error("Serve root per setup systemd", fatal=True)
        
    script_path = os.path.abspath(sys.argv[0])
    service_path = "/etc/systemd/system/checkmk-backup-cleanup.service"
    timer_path = "/etc/systemd/system/checkmk-backup-cleanup.timer"
    
    log("Configurazione Systemd...")
    
    service_content = f"""[Unit]
Description=CheckMK Backup Rename Service
After=multi-user.target

[Service]
Type=oneshot
ExecStart={sys.executable} {script_path} run --dir {backup_dir} --count {retention}
Nice=19
IOSchedulingClass=idle

[Install]
WantedBy=multi-user.target"""
    
    timer_content = """[Unit]
Description=CheckMK Backup Rename Timer (Every Minute)

[Timer]
OnCalendar=*:0/1
Persistent=true

[Install]
WantedBy=timers.target"""

    with open(service_path, "w") as f:
        f.write(service_content)
        
    with open(timer_path, "w") as f:
        f.write(timer_content)
        
    run_cmd(["systemctl", "daemon-reload"])
    run_cmd(["systemctl", "enable", "checkmk-backup-cleanup.timer"])
    run_cmd(["systemctl", "start", "checkmk-backup-cleanup.timer"])
    
    log("Setup completato. Timer attivo.")

def remove_systemd():
    if not is_root():
        error("Serve root per rimozione", fatal=True)
        
    log("Rimozione Systemd...")
    run_cmd(["systemctl", "stop", "checkmk-backup-cleanup.timer"], check=False)
    run_cmd(["systemctl", "disable", "checkmk-backup-cleanup.timer"], check=False)
    
    for p in ["/etc/systemd/system/checkmk-backup-cleanup.service", "/etc/systemd/system/checkmk-backup-cleanup.timer"]:
        if os.path.exists(p):
            os.remove(p)
            
    run_cmd(["systemctl", "daemon-reload"])
    log("Rimozione completata.")

def main():
    parser = argparse.ArgumentParser(description="CheckMK Backup Cleanup")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Run
    p_run = subparsers.add_parser("run", help="Esegui cleanup manuale")
    p_run.add_argument("--dir", default=DEFAULT_BACKUP_DIR, help="Backup directory")
    p_run.add_argument("--count", type=int, default=DEFAULT_RETENTION, help="Max backups")
    
    # Setup
    p_setup = subparsers.add_parser("setup", help="Installa systemd timer")
    p_setup.add_argument("--dir", default=DEFAULT_BACKUP_DIR)
    p_setup.add_argument("--count", type=int, default=DEFAULT_RETENTION)
    
    # Remove
    p_remove = subparsers.add_parser("remove", help="Rimuovi systemd timer")
    
    args = parser.parse_args()
    
    if args.command == "run":
        run_cleanup(args.dir, args.count)
    elif args.command == "setup":
        setup_systemd(args.dir, args.count)
    elif args.command == "remove":
        remove_systemd()

if __name__ == "__main__":
    main()
