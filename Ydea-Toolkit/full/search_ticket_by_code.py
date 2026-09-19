#!/usr/bin/env python3
"""search_ticket_by_code.py - Search Ydea tickets by code

Search for Ydea tickets using the ticket code (e.g. TK26/000123).

Usage:
    search_ticket_by_code.py <ticket_code>

Example:
    search_ticket_by_code.py TK26/000123

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
    """Search ticket by code"""
    if len(sys.argv) < 2:
        print("Usage: search_ticket_by_code.py <ticket_code>", file=sys.stderr)
        print("\nExample: search_ticket_by_code.py TK26/000123", file=sys.stderr)
        sys.exit(1)
    
    ticket_code = sys.argv[1]
    
    try:
        api = YdeaAPI()
        
        print(f" Ricerca ticket: {ticket_code}")
        print("=" * 60)
        
        # Search ticket by code
        data, status_code = api.api_call("GET", "/tickets", {"codice": ticket_code})
        
        if status_code == 200:
            tickets = data.get("objs", [])
            if tickets:
                print(f"\n Trovati {len(tickets)} ticket:\n")
                for ticket in tickets:
                    print(f"ID: {ticket.get('id')}")
                    print(f"Codice: {ticket.get('codice')}")
                    print(f"Titolo: {ticket.get('titolo')}")
                    print(f"Stato: {ticket.get('stato')}")
                    print("-" * 60)
                
                print("\nDettagli completi:")
                print(json.dumps(tickets, indent=2, ensure_ascii=False))
            else:
                print(f"\n  Nessun ticket trovato con codice: {ticket_code}")
        else:
            print(f"\n Errore: Status {status_code}")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            sys.exit(1)
        
    except Exception as e:
        print(f" Errore: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
