#!/usr/bin/env python3
"""scan_nmap.py - Interactive Nmap Scanner

Interactive wrapper for Nmap.
Features:
- Target selection (Host/Range/CIDR or File)
- Port Scan (default 1-1024) or Discovery (-sn) mode
- Verbose/Debug levels
- Output organized with Timestamp
- Automatic summary generation

Usage:
    scan_nmap.py

Version: 1.0.0"""

import sys
import os
import shutil
import subprocess
import re
from datetime import datetime
from pathlib import Path

VERSION = "1.0.0"

# --- Configuration ---
DEFAULT_OUTDIR = Path("./scans")
DEFAULT_PORTS = "1-1024"

class Console:
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    NC = '\033[0m'
    
    @staticmethod
    def error(msg): print(f"{Console.RED}[ERROR] {msg}{Console.NC}"); sys.exit(1)

    @staticmethod
    def input_sel(prompt, choices, default=None):
        while True:
            res = input(f"{prompt} [{'|'.join(choices)}] (def: {default}): ").strip().lower()
            if not res and default: return default
            if res in choices: return res
            print("Scelta non valida")

    @staticmethod
    def input_val(prompt, default=None):
        res = input(f"{prompt} [{default}]: ").strip()
        return res if res else default

def sanitize(name):
    return re.sub(r'[^a-zA-Z0-9._-]', '_', name)

def main():
    if not shutil.which("nmap"):
        Console.error("Nmap non trovato")
        
    print(f"NMAP INTERACTIVE SCANNER v{VERSION}")
    
    # 1. Target
    mode = Console.input_sel("Target Mode: (1) Host/Range, (2) File", ["1", "2"], "1")
    target_args = []
    label = ""
    
    if mode == "1":
        target = input("Host/Range/CIDR (es. 192.168.1.0/24): ").strip()
        if not target: Console.error("Target obbligatorio")
        target_args.append(target)
        label = sanitize(target)
    else:
        fpath = input("File targets: ").strip()
        if not Path(fpath).exists(): Console.error("File non trovato")
        target_args = ["-iL", fpath]
        label = sanitize(Path(fpath).name)

    # 2. Scan Type
    stype = Console.input_sel("Scan Type: (1) Port Scan, (2) Discovery (-sn)", ["1", "2"], "1")
    
    ports = DEFAULT_PORTS
    if stype == "1":
        ports = Console.input_val("Porte (es. 22,80 or 1-65535)", DEFAULT_PORTS)
        
    # 3. Verbosity
    vlevel = Console.input_sel("Verbose: (0) None, (1) -v, (2) -vv, (3) -d", ["0", "1", "2", "3"], "0")
    
    # 4. Outputs
    outdir = Console.input_val("Output Dir", str(DEFAULT_OUTDIR))
    outdir_path = Path(outdir)
    outdir_path.mkdir(parents=True, exist_ok=True)
    
    timing = Console.input_sel("Timing Template (0-5)", [str(i) for i in range(6)], "3")

    # Command construction
    cmd = ["nmap", f"-T{timing}", "--reason"]
    
    if vlevel == "1": cmd.append("-v")
    elif vlevel == "2": cmd.append("-vv")
    elif vlevel == "3": cmd.extend(["-d", "--packet-trace"])
    
    if stype == "1":
        if os.geteuid() == 0:
            cmd.append("-sS") # Updates SYN Stealth
        else:
            cmd.append("-sT") # Connect
        cmd.extend(["-p", ports])
    else:
        cmd.append("-sn") # Ping scan / Discovery
    
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    outbase = outdir_path / f"nmap-{ts}_{label}"
    outtxt = f"{outbase}.txt"
    outsum = f"{outbase}_summary.txt"
    
    cmd.extend(target_args)
    cmd.extend(["-oN", outtxt])
    
    print("\nComando:")
    print(" ".join(cmd))
    
    if input("Procedere? [y/N]: ").strip().lower() not in ['y', 'yes', 's']:
        sys.exit(0)
        
    print("\nScansione in corso...\n")
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\nInterrotto")
        sys.exit(130)

    # Summary Generation
    print("\nGenerazione Summary...")
    with open(outtxt, "r") as f:
        lines = f.readlines()
        
    summary_lines = []
    host = ""
    for line in lines:
        if "Nmap scan report for" in line:
            host = line.strip()
        if "open" in line and "/" in line: # simplistic port check
             summary_lines.append(f"{host} | {line.strip()}")
        elif stype == "2" and ("Host is up" in line or "MAC Address" in line):
             summary_lines.append(f"{host} | {line.strip()}")
             
    with open(outsum, "w") as f:
        f.write("\n".join(summary_lines))
        
    print(f"Output salvato in: {outtxt}")
    print(f"Summary salvato in: {outsum}")

if __name__ == "__main__":
    main()
