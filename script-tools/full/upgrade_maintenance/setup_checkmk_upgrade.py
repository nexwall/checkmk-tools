#!/usr/bin/env python3
"""setup_checkmk_upgrade.py - Setup CheckMK Auto-Upgrade

Configure Cron jobs to automatically update CheckMK RAW Edition.
Features:
- Interactive menu by frequency (Weekly, Monthly, Custom)
- Email notification configuration
- Backup existing crontab
- Creation of wrappers for execution via Cron

Usage:
    setup_checkmk_upgrade.py

Version: 1.0.0"""

import sys
import os
import subprocess
import re
from datetime import datetime
from pathlib import Path

VERSION = "1.0.0"

# --- Configuration ---
LOG_FILE = "/var/log/auto-upgrade-checkmk.log"
UPGRADE_SCRIPT_PATH = "/opt/omd/sites/monitoring/local/bin/upgrade_checkmk.py" # Assumes local deploy
# Fallback/Remote if needed, but we prefer local python script now
REMOTE_SCRIPT = "python3 /opt/omd/sites/monitoring/local/bin/upgrade_checkmk.py"

class Console:
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'
    
    @staticmethod
    def info(msg): print(f"{Console.BLUE}[INFO]{Console.NC} {msg}")
    @staticmethod
    def success(msg): print(f"{Console.GREEN}[SUCCESS]{Console.NC} {msg}")
    @staticmethod
    def warn(msg): print(f"{Console.YELLOW}[WARNING]{Console.NC} {msg}")
    @staticmethod
    def error(msg): print(f"{Console.RED}[ERROR]{Console.NC} {msg}")

    @staticmethod
    def input_choice(prompt, choices):
        while True:
            res = input(f"{prompt} [{'/'.join(choices)}]: ").strip().lower()
            if res in [c.lower() for c in choices]: return res
            print("Scelta non valida")

def install_mail_utils():
    if not shutil.which("mail"):
        Console.warn("'mail' command not found.")
        if Console.input_choice("Install mailutils?", ["y", "n"]) == "y":
            subprocess.run(["apt-get", "update"], check=False)
            subprocess.run(["apt-get", "install", "-y", "mailutils"], check=False)

def get_schedule():
    print(f"\n{Console.YELLOW}Seleziona frequenza upgrade:{Console.NC}")
    print("  1) Settimanale (Domenica 02:00)")
    print("  2) Mensile (1° del mese 02:00)")
    print("  3) Personalizzato")
    print("  4) Annulla")
    
    choice = input("Scelta [1-4]: ").strip()
    
    cron = ""
    desc = ""
    
    if choice == "1":
        cron = "0 2 * * 0"
        desc = "Weekly (Sun 02:00)"
    elif choice == "2":
        cron = "0 2 1 * *"
        desc = "Monthly (1st 02:00)"
    elif choice == "3":
        cron = input("Inserisci cron expression (es. '0 3 * * 5'): ").strip()
        desc = f"Custom: {cron}"
        # Basic validation
        if len(cron.split()) != 5:
            Console.error("Formato cron non valido (richiesti 5 campi)")
            sys.exit(1)
    elif choice == "4":
        sys.exit(0)
    else:
        Console.error("Scelta non valida")
        sys.exit(1)
        
    # Modify time
    if Console.input_choice("Modificare orario?", ["s", "n"]) == "s":
        try:
            h = int(input("Ora (0-23): "))
            m = int(input("Minuti (0-59): "))
            if not (0 <= h <= 23 and 0 <= m <= 59): raise ValueError
            parts = cron.split()
            parts[0] = str(m)
            parts[1] = str(h)
            cron = " ".join(parts)
            Console.info(f"Nuova pianificazione: {cron}")
        except:
             Console.error("Orario non valido")
             sys.exit(1)
             
    return cron, desc

def configure_email():
    if Console.input_choice("Ricevere notifiche email?", ["s", "n"]) != "s":
        return ""
        
    email = input("Indirizzo email: ").strip()
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        Console.error("Email non valida")
        sys.exit(1)
        
    install_mail_utils()
    
    hostname = subprocess.check_output("hostname", text=True).strip()
    return f" && (echo 'Upgrade OK' | mail -s 'CHECKMK UPGRADE OK - {hostname}' {email}) || (echo 'Upgrade FAILED' | mail -s 'CHECKMK UPGRADE ERROR - {hostname}' {email})"

def main():
    if os.geteuid() != 0:
        Console.error("Richiesti privilegi di root")
        sys.exit(1)
        
    print(f"\n{Console.BLUE}--- Setup CheckMK Auto-Upgrade v{VERSION} ---{Console.NC}\n")
    
    cron_sched, desc = get_schedule()
    email_cmd = configure_email()
    
    # Construct wrapper command
    # We use the python script created previously: upgrade_checkmk.py
    # Ensure it's executable
    python_script = Path(UPGRADE_SCRIPT_PATH)
    if not python_script.exists():
        # Try finding it in current dir or script-tools
        current = Path(__file__).parent / "upgrade_checkmk.py"
        if current.exists():
            python_script = current
        else:
             Console.warn(f"Script {UPGRADE_SCRIPT_PATH} non trovato. Assicurati di aver deployato i tools.")
    
    cmd = f"{python_script} >> {LOG_FILE} 2>&1"
    full_cron_line = f"{cron_sched} {cmd}{email_cmd}"
    
    print(f"\n{Console.BLUE}[INFO] Entry Crontab proposta:{Console.NC}")
    print(f"{Console.GREEN}{full_cron_line}{Console.NC}\n")
    
    if Console.input_choice("Confermi l'installazione?", ["s", "n"]) != "s":
        sys.exit(0)
        
    # Backups
    try:
        current_cron: str = subprocess.check_output(["crontab", "-l"], text=True, stderr=subprocess.DEVNULL)
    except:
        current_cron = ""
        
    backup_file = f"/root/cron_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    with open(backup_file, "w") as f: f.write(current_cron)
    Console.success(f"Backup crontab salvato in {backup_file}")
    
    # Filter old entries
    new_lines = []
    for line in current_cron.splitlines():
        if "upgrade_checkmk" not in line and "upgrade-checkmk" not in line:
            new_lines.append(line)
            
    new_lines.append(f"# CheckMK Auto-Upgrade: {desc}")
    new_lines.append(full_cron_line)
    
    # Write new crontab
    proc = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
    proc.communicate(input="\n".join(new_lines) + "\n")
    
    if proc.returncode == 0:
        Console.success("Crontab aggiornato con successo!")
        # Create log
        Path(LOG_FILE).touch()
        Console.success(f"Log file creato: {LOG_FILE}")
    else:
        Console.error("Errore aggiornamento crontab")

import shutil

if __name__ == "__main__":
    main()
