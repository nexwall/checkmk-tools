#!/usr/bin/env python3
"""get_ticket_by_id.py - Retrieve Ydea ticket details by ID

Retrieves and displays complete details of a Ydea ticket given its ID.

Usage:
    get_ticket_by_id.py <ticket_id>

Example:
    get_ticket_by_id.py 12345

Version: 1.0.0"""

import sys
import json
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
    """Get ticket by ID"""
    if len(sys.argv) < 2:
        print("Usage: get_ticket_by_id.py <ticket_id>", file=sys.stderr)
        print("\nExample: get_ticket_by_id.py 12345", file=sys.stderr)
        sys.exit(1)
    
    ticket_id = sys.argv[1]
    
    try:
        api = YdeaAPI()
        
        print(f" Recupero ticket ID: {ticket_id}")
        print("=" * 60)
        
        # Get ticket
        data, status_code = api.api_call("GET", f"/tickets/{ticket_id}")
        
        if status_code == 200:
            print("\n Ticket trovato:\n")
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(f"\n Errore: Status {status_code}")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            sys.exit(1)
        
    except Exception as e:
        print(f" Errore: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
