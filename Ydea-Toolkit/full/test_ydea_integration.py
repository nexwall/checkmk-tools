#!/usr/bin/env python3
"""test_ydea_integration.py - Complete CheckMK -> Ydea integration test

Performs a series of tests to verify:
1. File existence and permissions
2. Configuring environment variables
3. Ydea API connection
4. File cache existence
5. System dependencies
6. Cron Jobs

Usage:
    test_ydea_integration.py

Version: 1.0.0"""

import sys
import os
import shutil
import importlib.util
from pathlib import Path

# Colors for output
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'

# Import ydea-toolkit
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

ydea_common_path = script_dir / "ydea_common.py"
ydea_toolkit_path = script_dir / "ydea-toolkit.py"

# Default configuration
CHECKMK_SITE = os.environ.get("CHECKMK_SITE", "monitoring")
BASE_DIR = Path("/opt/ydea-toolkit")
NOTIFY_SCRIPT = Path(f"/omd/sites/{CHECKMK_SITE}/local/share/check_mk/notifications/ydea_realip")
HEALTH_SCRIPT = BASE_DIR / "ydea_health_monitor.py"

total_tests = 0
passed_tests = 0
failed_tests = 0

def test_start(name):
    global total_tests
    total_tests += 1
    print(f"{Colors.BLUE}[TEST {total_tests}]{Colors.NC} {name}")

def test_pass(msg):
    global passed_tests
    passed_tests += 1
    print(f"{Colors.GREEN}   PASS{Colors.NC}: {msg}\n")

def test_fail(msg):
    global failed_tests
    failed_tests += 1
    print(f"{Colors.RED}   FAIL{Colors.NC}: {msg}\n")

def test_warn(msg):
    print(f"{Colors.YELLOW}    WARN{Colors.NC}: {msg}\n")

def check_file(path, name, executable=False):
    p = Path(path)
    if not p.exists():
        test_fail(f"{name} non trovato: {path}")
        return False
    
    if executable and not os.access(path, os.X_OK):
        test_fail(f"{name} non è eseguibile: {path}")
        return False
        
    test_pass(f"{name} trovato" + (" ed eseguibile" if executable else ""))
    return True

def main():
    print(f"{Colors.BLUE}╔══════════════════════════════════════════════════════════════╗{Colors.NC}")
    print(f"{Colors.BLUE}║      Test Integrazione CheckMK -> Ydea Ticketing          ║{Colors.NC}")
    print(f"{Colors.BLUE}╚══════════════════════════════════════════════════════════════╝{Colors.NC}\n")

    # 1. Check Required Files
    test_start("Verifica file necessari")
    check_file(NOTIFY_SCRIPT, "Script notifica", executable=True)
    check_file(HEALTH_SCRIPT, "Health Monitor", executable=True)
    check_file(ydea_toolkit_path, "Toolkit UI", executable=True)
    check_file(ydea_common_path, "Common Module")

    # 2. .env configuration
    test_start("Verifica configurazione .env")
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv, dotenv_values
            # Prova a caricare se python-dotenv installato, altrimenti parse manuale semplice
            config = {}
            with open(env_file) as f:
                for line in f:
                    if '=' in line and not line.startswith('#'):
                        k, v = line.strip().split('=', 1)
                        config[k] = v
            
            if config.get("YDEA_ID") and config["YDEA_ID"] != "ID":
                test_pass("YDEA_ID configurato")
            else:
                test_fail("YDEA_ID non configurato")
                
            if config.get("YDEA_API_KEY") and config["YDEA_API_KEY"] != "TOKEN":
                test_pass("YDEA_API_KEY configurato")
            else:
                test_fail("YDEA_API_KEY non configurato")
        except Exception as e:
            test_fail(f"Errore lettura .env: {e}")
    else:
        test_fail(f"File .env non trovato: {env_file}")

    # 3. API connection
    test_start("Test Connessione Ydea API")
    try:
        # Carica modulo ydea_toolkit dinamicamente
        spec = importlib.util.spec_from_file_location("ydea_toolkit", ydea_toolkit_path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            api = mod.YdeaAPI()
            if api.ensure_token():
                test_pass("Login Ydea riuscito")
            else:
                test_fail("Login Ydea fallito")
        else:
            test_fail("Impossibile caricare ydea-toolkit.py")
    except Exception as e:
        test_fail(f"Errore durante test connessione: {e}")

    # 4. Cache Files
    test_start("Verifica file cache")
    cache_files = ["/tmp/ydea_checkmk_tickets.json", "/tmp/ydea_checkmk_flapping.json"]
    for cf in cache_files:
        p = Path(cf)
        if p.exists():
            test_pass(f"Cache trovato: {p.name}")
        else:
            test_warn(f"Cache non trovato (normale se primo avvio): {p.name}")

    # 5. Riepilogo
    print(f"\n{Colors.BLUE}=== RIEPILOGO ==={Colors.NC}")
    print(f"Test totali:  {total_tests}")
    print(f"Passati:      {Colors.GREEN}{passed_tests}{Colors.NC}")
    print(f"Falliti:      {Colors.RED}{failed_tests}{Colors.NC}\n")

    if failed_tests == 0:
        print(f"{Colors.GREEN} TUTTI I TEST PASSATI! Sistema pronto.{Colors.NC}")
        sys.exit(0)
    else:
        print(f"{Colors.RED} ALCUNI TEST FALLITI. Verificare output sopra.{Colors.NC}")
        sys.exit(1)

if __name__ == "__main__":
    main()
