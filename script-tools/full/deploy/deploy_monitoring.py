#!/usr/bin/env python3
"""deploy_monitoring.py - Deploy CheckMK Local Checks

Interactive deployment of control scripts (r*.sh) from the repository
to the local CheckMK agent folder.

Features:
- Automatic system type detection (ns7, ns8, proxmox, ubuntu)
- Correct source selection in the repo
- Interactive script selection menu
- Installation in /usr/lib/check_mk_agent/local

Usage:
    deploy_monitoring.py [options]

Options:
    --repo DIR Path repository (auto-detect)
    --all Install all scripts without asking
    --system TYPE Force system type (ns7, ns8, proxmox, ubuntu)

Version: 1.0.0"""

import sys
import os
import shutil
import glob
import argparse
from pathlib import Path

# --- Configuration ---
TARGET_DIR = Path("/usr/lib/check_mk_agent/local")
DEFAULT_REPO_PATHS = [
    Path("/opt/checkmk-tools"),
    Path("/root/checkmk-tools"),
    Path.home() / "checkmk-tools"
]

class Console:
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    NC = '\033[0m'
    
    @staticmethod
    def log(msg): print(f"[INFO] {msg}")
    @staticmethod
    def warn(msg): print(f"{Console.YELLOW}[WARN] {msg}{Console.NC}")
    @staticmethod
    def error(msg, fatal=True): 
        print(f"{Console.RED}[ERROR] {msg}{Console.NC}")
        if fatal: sys.exit(1)

def find_repo(arg_repo=None):
    if arg_repo:
        p = Path(arg_repo)
        if (p / ".git").exists(): return p
        
    for p in DEFAULT_REPO_PATHS:
        if (p / ".git").exists(): return p
        
    # Search upwards
    curr = Path(__file__).resolve().parent
    while curr != curr.parent:
        if (curr / ".git").exists(): return curr
        curr = curr.parent
        
    return None

def detect_system():
    if Path("/etc/pve/version").exists(): return "proxmox"
    if Path("/etc/nethserver-release").exists(): return "ns7"
    
    try:
        with open("/etc/os-release") as f:
            data = f.read().lower()
            if "nethserver" in data:
                if 'version_id="7' in data: return "ns7"
                if 'version_id="8' in data: return "ns8"
            if "proxmox" in data: return "proxmox"
            if "ubuntu" in data or "debian" in data: return "ubuntu"
    except:
        pass
        
    return "generic"

def get_source_dir(repo: Path, system: str):
    mapping = {
        "ns7": "script-check-ns7/remote",
        "ns8": "script-check-ns8/remote",
        "proxmox": "script-check-proxmox/remote",
        "ubuntu": "script-check-ubuntu/remote",
        "generic": "script-check-ubuntu/remote"
    }
    rel = mapping.get(system)
    if rel: return repo / rel
    return None

def main():
    if os.geteuid() != 0:
        Console.error("Eseguire come root")

    parser = argparse.ArgumentParser()
    parser.add_argument("--repo")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--system")
    args = parser.parse_args()
    
    # 1. Repo
    repo = find_repo(args.repo)
    if not repo:
        Console.error("Repository non trovato")
        
    # 2. System
    system = args.system if args.system else detect_system()
    Console.log(f"Sistema rilevato: {system}")
    
    src_dir = get_source_dir(repo, system)
    if not src_dir or not src_dir.exists():
        Console.error(f"Directory sorgente non trovata per {system}: {src_dir}")
        
    Console.log(f"Sorgente: {src_dir}")
    Console.log(f"Target: {TARGET_DIR}")
    
    # 3. List Scripts
    scripts = sorted(list(src_dir.glob("r*.sh")))
    if not scripts:
        Console.error("Nessuno script trovato")
        
    selected = []
    if args.all:
        selected = scripts
    else:
        print("\nScript disponibili:")
        for i, s in enumerate(scripts, 1):
            print(f"{i:3d}) {s.name}")
            
        print("\nSeleziona numeri (es. 1 3), 'a' per tutti, 'q' per uscire")
        sel = input("Scelta: ").strip().lower()
        
        if sel in ['q', 'n']:
            sys.exit(0)
        elif sel == 'a':
            selected = scripts
        else:
            try:
                indices = [int(x) - 1 for x in sel.split()]
                for idx in indices:
                    if 0 <= idx < len(scripts):
                        selected.append(scripts[idx])
            except:
                Console.warn("Selezione non valida")
                
    if not selected:
        Console.log("Nessuno script selezionato")
        sys.exit(0)
        
    # 4. Deploy
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    ok, fail = 0, 0
    
    for s in selected:
        dest = TARGET_DIR / s.name
        try:
            shutil.copy2(s, dest)
            dest.chmod(0o755)
            print(f"  Installato: {s.name}")
            ok += 1
        except Exception as e:
            Console.warn(f"Errore {s.name}: {e}")
            fail += 1
            
    Console.log(f"Deploy completato: {ok} OK, {fail} Errori")

if __name__ == "__main__":
    main()
