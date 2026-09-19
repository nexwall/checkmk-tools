#!/usr/bin/env python3
"""test_curl.py - Basic Ydea API connection test with curl-like output

Test the basic connection to the Ydea API by showing headers and responses.
Python equivalent of the original test-curl.sh.

Usage:
    test_curl.py

Version: 1.0.0"""

import sys
import importlib.util
from pathlib import Path

# Import ydea-toolkit
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

ydea_toolkit_path = script_dir / "ydea-toolkit.py"
spec = importlib.util.spec_from_file_location("ydea_toolkit", ydea_toolkit_path)
if spec and spec.loader:
    ydea_toolkit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ydea_toolkit)  # type: ignore
else:
    raise ImportError("Cannot load ydea-toolkit.py")

YdeaAPI = ydea_toolkit.YdeaAPI


def main():
    """API connection test"""
    print("=" * 60)
    print(" Test Connessione Ydea API")
    print("=" * 60)
    print()
    
    try:
        api = YdeaAPI()
        
        # Test login
        print(" Test autenticazione...")
        if api.ensure_token():
            print(" Autenticazione OK")
            print(f"   Token: {api.token[:20]}..." if api.token else "   Token: N/A")
        else:
            print(" Autenticazione fallita")
            sys.exit(1)
        
        print()
        
        # Test chiamata API base
        print(" Test chiamata API /tickets...")
        data, status_code = api.api_call("GET", "/tickets", {"limit": 1})
        
        print(f"   Status: {status_code}")
        print(f"   Response keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
        
        if status_code == 200:
            print(" API funzionante")
        else:
            print(f"  Status code: {status_code}")
        
        print()
        print("=" * 60)
        print(" Test completato")
        print("=" * 60)
        
    except Exception as e:
        print(f" Errore: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
