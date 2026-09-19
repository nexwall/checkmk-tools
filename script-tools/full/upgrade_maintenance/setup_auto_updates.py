#!/usr/bin/env python3
"""setup_auto_updates.py - Setup System Auto-Updates

Configure automatic system updates (apt update/upgrade)
via cronjob.

Features:
- Interactive menu for frequency (Daily, Weekly, Monthly, Custom)
- Integrated logging (/var/log/auto-updates.log)
- Backup existing crontab
- Removal of old configs

Usage:
    setup_auto_updates.py

Version: 1.0.0"""

import sys
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# --- Configuration ---
LOG_FILE = "/var/log/auto-updates.log"
UPDATE_CMD = "sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove -y"

class Console:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'

    @staticmethod
    def print_info(msg):
        print(f"{Console.BLUE}[INFO]{Console.NC} {msg}")

    @staticmethod
    def print_success(msg):
        print(f"{Console.GREEN}[SUCCESS]{Console.NC} {msg}")

    @staticmethod
    def print_warn(msg):
        print(f"{Console.YELLOW}[WARN]{Console.NC} {msg}")

    @staticmethod
    def print_error(msg):
        print(f"{Console.RED}[ERROR]{Console.NC} {msg}")

    @staticmethod
    def input(prompt, default=None):
        if default:
            res = input(f"{prompt} [{default}]: ")
            return res if res else default
        return input(f"{prompt}: ")

def is_root():
    return os.geteuid() == 0

def backup_crontab():
    backup_dir = Path("/root/crontab_backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / f"crontab_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    try:
        current = subprocess.check_output(["crontab", "-l"], stderr=subprocess.DEVNULL)
        with open(backup_file, "wb") as f:
            f.write(current)
        Console.print_success(f"Backup crontab salvato in: {backup_file}")
    except subprocess.CalledProcessError:
        Console.print_warn("Nessun crontab preesistente o errore lettura.")
        # Create empty backup just in case
        with open(backup_file, "w") as f:
            f.write("# Empty crontab\n")

def get_current_crontab() -> str:
    try:
        return subprocess.check_output(["crontab", "-l"], stderr=subprocess.DEVNULL, text=True)
    except subprocess.CalledProcessError:
        return ""

def set_crontab(content: str):
    p = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
    p.communicate(input=content)
    if p.returncode != 0:
        Console.print_error("Errore salvataggio crontab")
        sys.exit(1)

def main():
    if not is_root():
        Console.print_error("Eseguire come root (sudo)")
        sys.exit(1)

    print(f"\n{Console.BLUE}╔{'═'*50}╗{Console.NC}")
    print(f"{Console.BLUE}║    Configurazione Aggiornamenti Automatici       ║{Console.NC}")
    print(f"{Console.BLUE}╚{'═'*50}╝{Console.NC}\n")

    Console.print_info(f"Comando update: {Console.GREEN}{UPDATE_CMD}{Console.NC}\n")

    print("Seleziona frequenza:")
    print("  1) Giornaliero  (03:00)")
    print("  2) Settimanale  (Domenica 03:00)")
    print("  3) Mensile      (1° del mese 03:00)")
    print("  4) Custom Cron")
    print("  5) Esci")
    
    choice = Console.input("Scelta", "1")
    
    schedule = ""
    desc = ""
    
    if choice == "1":
        schedule = "0 3 * * *"
        desc = "Giornaliero @ 03:00"
    elif choice == "2":
        schedule = "0 3 * * 0"
        desc = "Settimanale (Dom) @ 03:00"
    elif choice == "3":
        schedule = "0 3 1 * *"
        desc = "Mensile (1°) @ 03:00"
    elif choice == "4":
        schedule = Console.input("Inserisci cron schedule (es. '0 4 * * *')")
        desc = "Custom"
    elif choice == "5":
        sys.exit(0)
    else:
        Console.print_error("Scelta non valida")
        sys.exit(1)

    # Modify time option
    if choice in ["1", "2", "3"]:
        if Console.input("Modificare orario?", "n").lower() in ['s', 'y']:
            h = Console.input("Ora (0-23)", "3")
            m = Console.input("Minuti (0-59)", "0")
            parts = schedule.split()
            # replace minute and hour
            schedule = f"{m} {h} {' '.join(parts[2:])}"
            desc = f"Custom Time: {schedule}"

    cron_entry = f"{schedule} (echo \"[$(date)] Starting auto-update\" && {UPDATE_CMD} && echo \"[$(date)] Completed\") >> {LOG_FILE} 2>&1"
    
    print(f"\nNuova entry:\n{Console.GREEN}{cron_entry}{Console.NC}\n")
    
    if Console.input("Confermi?", "s").lower() not in ['s', 'y']:
        sys.exit(0)

    backup_crontab()
    
    current_cron = get_current_crontab()
    new_cron_lines = []
    
    # Filter old entries
    if "apt update" in current_cron and "apt full-upgrade" in current_cron:
        Console.print_warn("Trovata entry preesistente.")
        if Console.input("Rimuovere vecchie entry?", "s").lower() in ['s', 'y']:
            for line in current_cron.splitlines():
                if "apt update" in line and "apt full-upgrade" in line:
                    continue
                new_cron_lines.append(line)
        else:
            new_cron_lines = current_cron.splitlines()
    else:
        new_cron_lines = current_cron.splitlines()

    # Add new entry
    new_cron_lines.append(f"# Auto-updates: {desc}")
    new_cron_lines.append(cron_entry)
    
    # Save
    set_crontab("\n".join(new_cron_lines) + "\n")
    Console.print_success("Crontab aggiornato!")
    
    # Setup log
    Path(LOG_FILE).touch()
    os.chmod(LOG_FILE, 0o644)
    
    Console.print_info(f"Log file: {LOG_FILE}")
    Console.print_info("Test immediato con: setup_auto_updates.py --test (non implementato in v1 ma puoi lanciare il comando update a mano)")

if __name__ == "__main__":
    main()
