#!/usr/bin/env python3
"""explore_ydea_api.py - Explore available Ydea API endpoints

Test various API endpoints to discover available functionality.

Usage:
    explore_ydea_api.py

Version: 1.0.0"""

import sys
import json
import importlib.util
from pathlib import Path

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


def test_endpoint(api: 'YdeaAPI', endpoint: str, params: dict = None):
    """Test singolo endpoint"""
    print(f"\n Testing: {endpoint}")
    try:
        data, status = api.api_call("GET", endpoint, params or {})
        if status == 200:
            if isinstance(data, dict) and "objs" in data:
                count = len(data.get("objs", []))
                print(f"    OK - {count} items")
            else:
                print(f"    OK - Response keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
        else:
            print(f"     Status: {status}")
    except Exception as e:
        print(f"    Error: {e}")


def main():
    print("=" * 60)
    print(" EXPLORE YDEA API ENDPOINTS")
    print("=" * 60)
    
    try:
        api = YdeaAPI()
        
        # List of endpoints to test
        endpoints = [
            ("/tickets", {"limit": 5}),
            ("/categories", {}),
            ("/priorities", {}),
            ("/users", {"limit": 5}),
            ("/sla", {}),
            ("/stati", {}),
            ("/tipi", {}),
            ("/fonti", {}),
        ]
        
        for endpoint, params in endpoints:
            test_endpoint(api, endpoint, params)
        
        print("\n" + "=" * 60)
        print(" Esplorazione completata")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n Errore: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
