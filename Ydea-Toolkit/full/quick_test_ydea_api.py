#!/usr/bin/env python3
"""quick_test_ydea_api.py - Quick test Ydea API

Test rapido funzionalità base API Ydea: login, get tickets, get categories.

Usage:
    quick_test_ydea_api.py

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
    """Quick test API"""
    print(" Quick Test Ydea API")
    print("=" * 60)
    
    try:
        api = YdeaAPI()
        
        # Test 1: Login
        print("\n1⃣  Test Login...")
        if api.ensure_token():
            print("    Login OK")
        else:
            print("    Login fallito")
            sys.exit(1)
        
        # Test 2: Get Tickets
        print("\n2⃣  Test GET /tickets...")
        tickets_data, status = api.api_call("GET", "/tickets", {"limit": 5})
        if status == 200:
            ticket_count = len(tickets_data.get("objs", []))
            print(f"    Tickets recuperati: {ticket_count}")
        else:
            print(f"     Status: {status}")
        
        # Test 3: Get Categories
        print("\n3⃣  Test GET /categories...")
        cat_data, status = api.api_call("GET", "/categories")
        if status == 200:
            cat_count = len(cat_data.get("objs", []))
            print(f"    Categorie recuperate: {cat_count}")
        else:
            print(f"     Status: {status}")
        
        # Test 4: Get Priorities
        print("\n4⃣  Test GET /priorities...")
        prio_data, status = api.api_call("GET", "/priorities")
        if status == 200:
            prio_count = len(prio_data.get("objs", []))
            print(f"    Priorità recuperate: {prio_count}")
        else:
            print(f"     Status: {status}")
        
        print("\n" + "=" * 60)
        print(" Quick test completato con successo!")
        
    except Exception as e:
        print(f"\n Errore: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
