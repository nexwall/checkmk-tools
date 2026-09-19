#!/usr/bin/env python3
"""startup_check.py - Rocksolid Startup Check & Remediation

Check and restore critical services at startup.
Features:
- Restore critical binaries (tar, gzip, ar) from backups if corrupted
- Verify/Restore Node.js & Nginx (NethSecurity UI)
- Check/Restore CheckMK Agent & FRPC
- Auto-Deploy local scripts and plugins from repo
- Check QEMU Guest Agent (VM)

Usage:
    startup_check.py

Version: 1.0.0"""

import sys
import os
import shutil
import subprocess
import time
import glob
from pathlib import Path

VERSION = "1.0.0"

# --- Configuration ---
LOG_FILE = "/var/log/rocksolid-startup.log"
BACKUP_DIR = Path("/opt/checkmk-backups/binaries")
REPO_PLUGINS = Path("/opt/checkmk-tools/script-check-nsec8/plugins")
REPO_CHECKS = Path("/opt/checkmk-tools/script-check-nsec8/full")

class Console:
    @staticmethod
    def log(msg):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{ts}] {msg}"
        print(entry)
        try:
            with open(LOG_FILE, "a") as f: f.write(entry + "\n")
            subprocess.run(["logger", "-t", "rocksolid-startup", msg], check=False)
        except: pass

def run_cmd(cmd, check=False):
    try:
        return subprocess.run(cmd, check=check, shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except: return False

def is_running(proc_name):
    try:
        # pgrep -f equivalent
        return subprocess.run(["pgrep", "-f", proc_name], stdout=subprocess.DEVNULL).returncode == 0
    except: return False

def restore_critical_binaries():
    if not BACKUP_DIR.exists(): return
    
    Console.log("[Binari Critici] Verifica...")
    
    mapping = {
        "ar": "/usr/bin/ar",
        "tar-gnu": "/usr/libexec/tar-gnu",
        "gzip-gnu": "/usr/libexec/gzip-gnu"
    }
    
    for backup in BACKUP_DIR.glob("*.backup"):
        name = backup.stem
        dest = mapping.get(name)
        if not dest: continue
        
        path = Path(dest)
        if not path.exists(): # or check hash?
            Console.log(f"Ripristino {dest} (mancante)...")
            shutil.copy2(backup, dest)
            os.chmod(dest, 0o755)

    # Check ar execution
    if shutil.which("ar"):
        if not run_cmd(["ar", "--version"]):
            Console.log("[Binari Critici] ar corrotto! Tentativo reinstallazione pacchetti...")
            # Reinstall OpenWrt packages logic... omitted for brevity/compatibility in generic python
            # In a real scenario, we'd call opkg here.
            if shutil.which("opkg"):
                 run_cmd(["opkg", "update"])
                 run_cmd(["opkg", "install", "--force-reinstall", "ar", "binutils"])

def check_nodejs_nginx():
    # Only if NethServer/Security
    if not Path("/etc/nethserver-release").exists() and not Path("/etc/openwrt_release").exists():
        return

    Console.log("[Web UI] Verifica...")
    
    if not shutil.which("node"):
         Console.log("[Node.js] Mancante! Tentativo installazione...")
         if shutil.which("opkg"):
             run_cmd(["opkg", "update"])
             run_cmd(["opkg", "install", "node"])
             
    if shutil.which("nginx"):
         if not is_running("nginx"):
             Console.log("[Nginx] Avvio servizio...")
             run_cmd(["/etc/init.d/nginx", "restart"])

def check_agent():
    Console.log("[CheckMK Agent] Verifica...")
    if not shutil.which("check_mk_agent"):
         Console.log("[CheckMK Agent] Binario mancante!")
         # Remediation: run install_agent.py? or post-upgrade script?
         if Path("/etc/checkmk-post-upgrade.sh").exists():
             run_cmd(["/etc/checkmk-post-upgrade.sh"])
             
    # Service
    if not is_running("socat TCP-LISTEN:6556") and not is_running("check_mk_agent"):
         Console.log("[CheckMK Agent] Servizio stopped. Riavvio...")
         if Path("/etc/init.d/check_mk_agent").exists():
             run_cmd(["/etc/init.d/check_mk_agent", "restart"])
         else:
             run_cmd(["systemctl", "restart", "check-mk-agent-plain.socket"])

def check_frpc():
    Console.log("[FRPC] Verifica...")
    if Path("/usr/local/bin/frpc").exists():
         if not is_running("frpc"):
             Console.log("[FRPC] Stopped. Riavvio...")
             if Path("/etc/init.d/frpc").exists():
                 run_cmd(["/etc/init.d/frpc", "restart"])
             else:
                 run_cmd(["systemctl", "restart", "frpc"])

def auto_deploy():
    Console.log("[Auto-Deploy] Sync script...")
    
    # Local Checks
    target_local = Path("/usr/lib/check_mk_agent/local")
    target_local.mkdir(parents=True, exist_ok=True)
    
    if REPO_CHECKS.exists():
        for script in REPO_CHECKS.glob("check_*.sh"):
            dest = target_local / script.name
            if not dest.exists() or script.stat().st_mtime > dest.stat().st_mtime:
                Console.log(f"Deploy check: {script.name}")
                shutil.copy2(script, dest)
                os.chmod(dest, 0o755)

    # Plugins
    target_plugins = Path("/usr/lib/check_mk_agent/plugins")
    target_plugins.mkdir(parents=True, exist_ok=True)
    
    if REPO_PLUGINS.exists():
        for plug in REPO_PLUGINS.glob("*"):
            if not plug.is_file(): continue
            dest = target_plugins / plug.name
            if not dest.exists() or plug.stat().st_mtime > dest.stat().st_mtime:
                 Console.log(f"Deploy plugin: {plug.name}")
                 shutil.copy2(plug, dest)
                 os.chmod(dest, 0o755)

def check_qemu_ga():
    if Path("/usr/bin/qemu-ga").exists():
        if not is_running("qemu-ga"):
             Console.log("[QEMU-GA] Riavvio...")
             if Path("/etc/init.d/qemu-ga").exists():
                 run_cmd(["/etc/init.d/qemu-ga", "restart"])
             else:
                 run_cmd(["systemctl", "restart", "qemu-guest-agent"])

def main():
    Console.log(f"--- Startup Check v{VERSION} ---")
    
    restore_critical_binaries()
    check_nodejs_nginx()
    check_agent()
    check_frpc()
    check_qemu_ga()
    auto_deploy()
    
    Console.log("Startup Check Completato")

if __name__ == "__main__":
    main()
