#!/usr/bin/env python3
"""check_ransomware_ns7.py - CheckMK Local Check for Ransomware detection

Scan all Samba shares for suspicious files (encrypted extensions, ransom notes).
Log findings to /var/log/ransomware_monitor.log

NethServer 7.9

Version: 1.0.0"""

import subprocess
import sys
import os
import re
from datetime import datetime

VERSION = "1.0.0"
SERVICE_NAME = "Ransomware"
LOGFILE = "/var/log/ransomware_monitor.log"
SUSPECT_EXTS = ["encrypted", "crypt", "locked", "enc", "lock", "ransom", "pay", "recover"]
RANSOM_NOTES = ["README", "DECRYPT", "HOW_TO_RECOVER", "UNLOCK", "HELP", "RESTORE"]


def get_samba_shares():
    """Get list of Samba shares from smb.conf.
    
    Returns:
        List of tuples (share_name, share_path)"""
    if not os.path.exists("/etc/samba/smb.conf"):
        return []
    
    shares = []
    current_share = None
    current_path = None
    
    try:
        with open("/etc/samba/smb.conf", "r") as f:
            for line in f:
                line = line.strip()
                
                # Share section start
                match = re.match(r'^\[([^\]]+)\]', line)
                if match:
                    # Save previous share if we have one
                    if current_share and current_path:
                        shares.append((current_share, current_path))
                    
                    share_name = match.group(1)
                    if share_name.lower() not in ["global", "homes", "printers"]:
                        current_share = share_name
                        current_path = None
                    else:
                        current_share = None
                continue
                
                # Path definition
                if current_share and line.startswith("path"):
                    parts = line.split('=', 1)
                    if len(parts) == 2:
                        current_path = parts[1].strip()
            
            # Save last share
            if current_share and current_path:
                shares.append((current_share, current_path))
    
    except IOError:
        return []
    
    return shares


def find_suspect_files(share_path):
    """Find suspicious files in share path.
    
    Args:
        share_path: Path to share
        
    Returns:
        List of suspect file paths"""
    if not os.path.exists(share_path):
        return []
    
    found = []
    
    # Search for suspect extensions
    for ext in SUSPECT_EXTS:
        try:
            result = subprocess.run(
                ["find", share_path, "-type", "f", "-name", f"*.{ext}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=60
            )
            if result.returncode == 0 and result.stdout.strip():
                found.extend(result.stdout.strip().splitlines())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    
    # Search for ransom notes
    for note in RANSOM_NOTES:
        try:
            result = subprocess.run(
                ["find", share_path, "-type", "f", "-iname", f"*{note}*"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=60
            )
            if result.returncode == 0 and result.stdout.strip():
                found.extend(result.stdout.strip().splitlines())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    
    return list(set(found))


def log_suspect_files(share_name, share_path, files):
    """Log suspect files to logfile.
    
    Args:
        share_name: Name of share
        share_path: Path to share
        files: List of suspect file paths"""
    if not files:
        return
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        with open(LOGFILE, "a") as f:
            f.write(f"[{now}] [SHARE:{share_name}] [PATH:{share_path}] Suspicious files found:\n")
            for file_path in files:
                f.write(f"  {file_path}\n")
    except IOError:
        pass


def main():
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    shares = get_samba_shares()
    
    # Scan all shares
    for share_name, share_path in shares:
        suspect_files = find_suspect_files(share_path)
        if suspect_files:
            log_suspect_files(share_name, share_path, suspect_files)
    
    # Check if logfile contains any findings
    found_suspects = False
    if os.path.exists(LOGFILE):
        try:
            with open(LOGFILE, "r") as f:
                content = f.read()
                if "Suspicious files found:" in content:
                    found_suspects = True
        except IOError:
            pass
    
    if found_suspects:
        print(f"2 {SERVICE_NAME} - CRITICAL - Ransomware: suspicious files detected. See {LOGFILE}")
    else:
        print(f"0 {SERVICE_NAME} - OK - No ransomware detected")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
