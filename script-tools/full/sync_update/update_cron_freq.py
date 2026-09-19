#!/usr/bin/env python3
"""update_cron_freq.py - Update Cron Job Frequency

Interactive script to change the execution frequency of specific jobs in the crontab.
Target: rcheck-ticket-monitor.sh (or similar configured)

Usage:
    update_cron_freq.py

Version: 1.0.0"""

import sys
import os
import subprocess
import re
from datetime import datetime

VERSION = "1.0.0"

# --- Configuration ---
TARGET_CMD = "rcheck-ticket-monitor.sh" # Keyword to search in crontab

class Console:
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    NC = '\033[0m'
    
    @staticmethod
    def error(msg): print(f"{Console.RED}[ERROR] {msg}{Console.NC}"); sys.exit(1)
    @staticmethod
    def log(msg): print(f"[INFO] {msg}")

def get_crontab() -> str:
    try:
        return subprocess.check_output(["crontab", "-l"], text=True, stderr=subprocess.DEVNULL)
    except:
        return ""

def parse_freq(line):
    parts = line.split()
    if len(parts) < 5: return "invalid"
    # Return minute part or description
    min_part = parts[0]
    if min_part == "*": return "ogni minuto"
    if "/" in min_part: return f"ogni {min_part.split('/')[1]} minuti"
    return f"al minuto {min_part}"

def main():
    if os.geteuid() != 0:
        Console.error("Richiesti privilegi di root")
        
    current = get_crontab()
    target_line = None
    
    for line in current.splitlines():
        if TARGET_CMD in line and not line.strip().startswith("#"):
            target_line = line
            break
            
    current_freq_desc = "Non impostato"
    if target_line:
        current_freq_desc = parse_freq(target_line)
        
    print(f"\nConfigurazione Frequenza {TARGET_CMD} v{VERSION}")
    print(f"Frequenza attuale: {Console.GREEN}{current_freq_desc}{Console.NC}\n")
    
    print("Scegli nuova frequenza:")
    print("  1) Ogni 1 minuto   (*/1)")
    print("  2) Ogni 5 minuti   (*/5)")
    print("  3) Ogni 10 minuti  (*/10)")
    print("  4) Ogni 15 minuti  (*/15)")
    print("  5) Ogni 30 minuti  (*/30)")
    print("  6) Personalizzato")
    print("  0) Esci")
    
    choice = input("\nScelta [1-6, 0]: ").strip()
    
    new_freq = ""
    
    if choice == "1": new_freq = "*/1"
    elif choice == "2": new_freq = "*/5"
    elif choice == "3": new_freq = "*/10"
    elif choice == "4": new_freq = "*/15"
    elif choice == "5": new_freq = "*/30"
    elif choice == "6": 
        new_freq = input("Inserisci frequenza minuti (es. */5 o 0,15,30): ").strip()
        # Basic validation
        if not re.match(r"^(\*\/[0-9]+|[0-9,]+)$", new_freq):
            Console.error("Formato non valido")
    elif choice == "0": sys.exit(0)
    else: Console.error("Scelta non valida")
    
    # Apply
    # We replace the minute part of the line matching TARGET_CMD
    # If not exists, we append? The bash script appends.
    
    new_lines = []
    found = False
    
    for line in current.splitlines():
        if TARGET_CMD in line:
            # Replace minute part
            parts: list[str] = line.split()
            if len(parts) >= 5:
                parts[0] = new_freq
                new_line = " ".join(parts)
                new_lines.append(new_line)
                found = True
                print(f"Aggiornato: {new_line}")
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
            
    if not found:
        # Append default
        cmd_path = f"/opt/ydea-toolkit/{TARGET_CMD}"
        new_line = f"{new_freq} * * * * {cmd_path} >> /var/log/ticket-monitor.log 2>&1"
        new_lines.append(new_line)
        print(f"Aggiunto: {new_line}")
        
    # Backups
    backup_file = f"/tmp/crontab.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    with open(backup_file, "w") as f: f.write(current)
    Console.log(f"Backup crontab: {backup_file}")
    
    # Write
    proc = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
    proc.communicate(input="\n".join(new_lines) + "\n")
    
    if proc.returncode == 0:
        print(f"\n{Console.GREEN}Crontab aggiornato con successo{Console.NC}")
    else:
        Console.error("Errore aggiornamento crontab")

if __name__ == "__main__":
    main()
