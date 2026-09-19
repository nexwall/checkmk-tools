#!/usr/bin/env python3
"""smart_deploy.py - Smart Deploy for CheckMK Scripts

Create "smart" wrappers for CheckMK scripts that handle:
- Automatic download from GitHub
- Local caching
- Resilient execution (cache fallback)
- Support notifications/plugins/local checks

Usage:
    smart_deploy.py [--auto]

Version: 1.0.0"""

import sys
import os
import shutil
import subprocess
import time
from pathlib import Path

VERSION = "1.0.0"

# --- Configuration ---
GITHUB_REPO = "nethesis/checkmk-tools"
BASE_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main"
CACHE_DIR = Path("/var/cache/checkmk-scripts")
# Adjust paths based on environment
IS_OMD = Path("/omd/sites").exists()

class Console:
    @staticmethod
    def log(msg): print(f"[INFO] {msg}")
    @staticmethod
    def warn(msg): print(f"[WARN] {msg}")
    @staticmethod
    def error(msg): print(f"[ERROR] {msg}"); sys.exit(1)

def detect_paths():
    paths = {
        "local": Path("/usr/lib/check_mk_agent/local"),
        "plugins": Path("/usr/lib/check_mk_agent/plugins"),
        "notifications": None,
        "cache": CACHE_DIR
    }
    
    if IS_OMD:
        # Find first site or default 'monitoring'
        try:
            sites = list(Path("/omd/sites").iterdir())
            if sites:
                site_root = sites[0]
                paths["notifications"] = site_root / "local/share/check_mk/notifications"
                paths["cache"] = site_root / "var/cache/checkmk-scripts"
        except: pass
        
    return paths

def create_wrapper(name, github_path, s_type, target_dir, cache_dir):
    wrapper_path = target_dir / name
    
    script_content = f"""#!/usr/bin/env python3
import os
import sys
import time
import subprocess
from pathlib import Path
import urllib.request

# Configuration
SCRIPT_NAME = "{name}"
GITHUB_URL = "{BASE_URL}/{github_path}"
CACHE_FILE = Path("{cache_dir}") / "{name}.sh"
TIMEOUT = 10

def download_file(url, target, timeout):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            content = response.read()
            # Basic sanity check (shebang)
            if content.startswith(b"#!"):
                with open(target, "wb") as f: f.write(content)
                os.chmod(target, 0o755)
                return True
    except Exception as e:
        # print(f"Download error: {{e}}", file=sys.stderr)
        return False
    return False

def main():
    # Ensure cache dir
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Try update
    tmp_file = CACHE_FILE.with_suffix(".tmp")
    if download_file(GITHUB_URL, tmp_file, TIMEOUT):
        tmp_file.replace(CACHE_FILE)
        
    # Execute cached
    if CACHE_FILE.exists() and os.access(CACHE_FILE, os.X_OK):
        try:
            # Pass all args
            subprocess.run([str(CACHE_FILE)] + sys.argv[1:], check=True)
        except subprocess.CalledProcessError as e:
            sys.exit(e.returncode)
    else:
        # If type is local, output critical
        if "{s_type}" == "local":
            print(f"2 {{SCRIPT_NAME}} - CRITICAL: No cached script found")
        sys.exit(2)

if __name__ == "__main__":
    main()"""
    
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        with open(wrapper_path, "w") as f:
            f.write(script_content)
        os.chmod(wrapper_path, 0o755)
        Console.log(f"Wrapper creato: {wrapper_path}")
        return True
    except Exception as e:
        Console.warn(f"Errore creazione wrapper {name}: {e}")
        return False

def main():
    if os.geteuid() != 0:
        Console.error("Richiesti privilegi di root")
        
    print(f"Smart Deploy Tool v{VERSION}")
    
    paths = detect_paths()
    
    # Script map to deploy
    # name -> (github_path, type)
    scripts = {
        "check_cockpit_sessions": ("script-check-ns7/check_cockpit_sessions.sh", "local"),
        "check_dovecot_status": ("script-check-ns7/check_dovecot_status.sh", "local"),
        "check_ssh_root_sessions": ("script-check-ns7/check_ssh_root_sessions.sh", "local"),
        "check_postfix_status": ("script-check-ns7/check_postfix_status.sh", "local"),
        "telegram_realip": ("script-notify-checkmk/telegram_realip", "notification")
    }
    
    deployed_count = 0
    
    for name, (gh_path, s_type) in scripts.items():
        target = paths.get(s_type + "s" if s_type != "local" else "local") # pluralize key
        if s_type == "notification" and not target:
            Console.warn(f"Skip {name}: Notification dir not found (non-OMD env?)")
            continue
            
        if not target: target = paths["local"] # fallback
        
        if create_wrapper(name, gh_path, s_type, target, paths["cache"]):
            deployed_count += 1
            
    Console.log(f"Smart Deploy completato. Wrapper creati: {deployed_count}")

if __name__ == "__main__":
    main()
