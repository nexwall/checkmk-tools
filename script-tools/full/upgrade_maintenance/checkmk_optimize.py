#!/usr/bin/env python3
"""checkmk_optimize.py - CheckMK Host Optimization Tool

Balanced optimizations for CheckMK hosts (Debian/Ubuntu).
Features:
- Timeshift snapshots (System backup)
- Tuning Swap/ZRAM
- Disabling non-essential services
- Tuning I/O Scheduler
- DB Tuning (MariaDB/MySQL)
- Apache Tuning (LimitNOFILE)
- Agent Cache Preparation
- FRP Tuning (compression)

Usage:
    checkmk_optimize.py [--auto]

Version: 1.0.0"""

import sys
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

VERSION = "1.0.0"

# --- Configuration ---
LOG_FILE = "/var/log/checkmk-optimize.log"
TS_LOG = "/var/log/timeshift-rotation.log"
BACKUP_DIR = Path("/var/backups/checkmk-optimize")

class Console:
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    NC = '\033[0m'
    
    @staticmethod
    def log(msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {msg}")
        with open(LOG_FILE, "a") as f: f.write(f"[{ts}] {msg}\n")
        
    @staticmethod
    def warn(msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{Console.YELLOW}[{ts}] WARN: {msg}{Console.NC}")
        with open(LOG_FILE, "a") as f: f.write(f"[{ts}] WARN: {msg}\n")

    @staticmethod
    def ask(prompt):
        if "--auto" in sys.argv: return True
        res = input(f"{prompt} [y/N]: ").strip().lower()
        return res in ['y', 'yes', 's']

def run_cmd(cmd, check=True):
    try:
        subprocess.run(cmd, check=check, shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

def backup_file(path):
    if not path.exists(): return
    dest = BACKUP_DIR / f"{path.name}.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
    shutil.copy2(path, dest)

def timeshift_snapshot(label):
    if not shutil.which("timeshift"):
        Console.warn("Timeshift non installato")
        return

    full_label = f"{label}-checkmk-optimize {datetime.now().strftime('%F_%T')}"
    Console.log(f"Timeshift: Creating snapshot {label}...")
    
    cmd = ["timeshift", "--create", "--comments", full_label, "--tags", "D"]
    if run_cmd(cmd):
        Console.log(f"Snapshot {label} OK")
        with open(TS_LOG, "a") as f: f.write(f"[{datetime.now()}] Snapshot {label} OK\n")
    else:
        Console.warn(f"Snapshot {label} Failed")
        with open(TS_LOG, "a") as f: f.write(f"[{datetime.now()}] Snapshot {label} ERROR\n")

def optimize_swap_zram():
    Console.log("Ottimizzazione SWAP/ZRAM...")
    
    # Sysctl
    conf = Path("/etc/sysctl.d/99-swap.conf")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if conf.exists(): backup_file(conf)
    
    with open(conf, "w") as f:
        f.write("vm.swappiness = 10\n")
    run_cmd(["sysctl", "-w", "vm.swappiness=10"])
    
    # ZRAM
    res = subprocess.run("dpkg-query -W -f='${Status}' zram-tools", shell=True, capture_output=True, text=True)
    if "install ok installed" not in res.stdout:
        Console.log("Installazione zram-tools...")
        run_cmd(["apt-get", "update"])
        run_cmd(["apt-get", "install", "-y", "zram-tools"])
    else:
        Console.log("zram-tools già presente")

def disable_services():
    svcs = ["snapd.service", "apport.service", "motd-news.timer"]
    for s in svcs:
        if run_cmd(["systemctl", "list-unit-files", s]): # Check existence roughly
             Console.log(f"Disabling {s}...")
             run_cmd(["systemctl", "disable", "--now", s], check=False)

def optimize_io():
    Console.log("Ottimizzazione I/O Scheduler...")
    # Find disk
    try:
        disk = subprocess.check_output("lsblk -ndo NAME,TYPE | awk '$2==\"disk\"{print $1; exit}'", shell=True, text=True).strip()
    except:
        disk = None
        
    if not disk:
        Console.warn("Nessun disco rilevato")
        return
        
    sched_file = Path(f"/sys/block/{disk}/queue/scheduler")
    if not sched_file.exists(): return
    
    content = sched_file.read_text()
    target = "mq-deadline" if "mq-deadline" in content else "deadline" if "deadline" in content else None
    
    if target:
        with open(sched_file, "w") as f: f.write(target)
        Console.log(f"I/O Scheduler /dev/{disk} -> {target}")
    else:
        Console.warn(f"Scheduler ottimizzato non disponibile per {disk}")

def optimize_db():
    Console.log("Ottimizzazione DB...")
    
    service = None
    conf_file: Path | None = None
    
    if shutil.which("mariadbd") or Path("/etc/mysql/mariadb.conf.d").exists():
        service = "mariadb"
        conf_file = Path("/etc/mysql/mariadb.conf.d/50-server.cnf")
    elif shutil.which("mysqld"):
        service = "mysql"
        conf_file = Path("/etc/mysql/mysql.conf.d/mysqld.cnf")
        
    if not service or not conf_file or not conf_file.exists():
        Console.warn("DB non trovato o config non standard")
        return
        
    backup_file(conf_file)
    
    # Read and filter old block
    assert conf_file is not None
    lines = conf_file.read_text().splitlines()
    new_lines = []
    skip = False
    for line in lines:
        if "# BEGIN CHECKMK_OPTIMIZE" in line: skip = True
        if not skip: new_lines.append(line)
        if "# END CHECKMK_OPTIMIZE" in line: skip = False
        
    # Add new block
    block = """# BEGIN CHECKMK_OPTIMIZE
# Tuning "bilanciato"
innodb_buffer_pool_size = 512M
innodb_log_file_size = 128M
query_cache_size = 32M
query_cache_type = 1
# END CHECKMK_OPTIMIZE"""
    assert conf_file is not None
    with open(conf_file, "w") as f:
        f.write("\n".join(new_lines) + block)
        
    Console.log(f"Riavvio {service}...")
    if run_cmd(["systemctl", "restart", service]):
        Console.log("DB Riavviato")
    else:
        Console.warn("Errore riavvio DB")

def optimize_apache():
    Console.log("Ottimizzazione Apache...")
    dropin = Path("/etc/systemd/system/apache2.service.d")
    dropin.mkdir(parents=True, exist_ok=True)
    
    with open(dropin / "limits.conf", "w") as f:
        f.write("[Service]\nLimitNOFILE=4096\n")
        
    run_cmd(["systemctl", "daemon-reload"])
    if run_cmd(["systemctl", "restart", "apache2"]):
        Console.log("Apache riavviato")
    else:
        Console.warn("Errore riavvio Apache")

def prepare_cache():
    d = Path("/var/lib/check_mk_agent/cache")
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    Console.log(f"Cache dir pronta: {d}")

def disable_frp_comp():
    Console.log("Disabilitazione compressione FRP...")
    for p in ["/etc/frp/frpc.toml", "/etc/frp/frps.toml"]:
        path = Path(p)
        if path.exists():
            backup_file(path)
            content = path.read_text()
            # Disable compression logic (regex replace essentially)
            import re
            content = re.sub(r'use_compression\s*=\s*true', 'use_compression = false', content, flags=re.I)
            path.write_text(content)
            
    run_cmd(["systemctl", "restart", "frpc"], check=False)
    run_cmd(["systemctl", "restart", "frps"], check=False)

def main():
    if os.geteuid() != 0:
        print("Run as root")
        sys.exit(1)
        
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"CheckMK Optimize Tool - v{VERSION}")
    print(f"Log: {LOG_FILE}")
    
    if Console.ask("Creare Snapshot PRE?"):
        timeshift_snapshot("PRE")
        
    if Console.ask("Ottimizzare SWAP/ZRAM?"):
        optimize_swap_zram()
        
    if Console.ask("Disabilitare servizi inutili?"):
        disable_services()
        
    if Console.ask("Ottimizzare I/O Scheduler?"):
        optimize_io()
        
    if Console.ask("Ottimizzare DB?"):
        optimize_db()
        
    if Console.ask("Ottimizzare Apache?"):
        optimize_apache()
        
    if Console.ask("Preparare Cache Agente?"):
        prepare_cache()
        
    if Console.ask("Disabilitare compressione FRP?"):
        disable_frp_comp()
        
    if Console.ask("Creare Snapshot POST?"):
        timeshift_snapshot("POST")
        
    Console.log("Ottimizzazione Completata")

if __name__ == "__main__":
    main()
