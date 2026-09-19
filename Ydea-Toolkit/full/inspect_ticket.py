#!/usr/bin/env python3
"""inspect_ticket.py - Inspect complete Ydea ticket structure

Shows all fields and structure of a ticket for analysis.

Usage:
    inspect_ticket.py <ticket_id>

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


def main():
    if len(sys.argv) < 2:
        print("Usage: inspect_ticket.py <ticket_id>", file=sys.stderr)
        sys.exit(1)
    
    ticket_id = sys.argv[1]
    
    try:
        api = YdeaAPI()
        data, status = api.api_call("GET", f"/tickets/{ticket_id}")
        
        if status != 200:
            print(f" Errore: Status {status}", file=sys.stderr)
            sys.exit(1)
        
        print("=" * 70)
        print(f" INSPECT TICKET ID: {ticket_id}")
        print("=" * 70)
        print()
        
        print(" JSON COMPLETO:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        print()
        
        print("=" * 70)
        print(" CHIAVI DISPONIBILI:")
        print("=" * 70)
        if isinstance(data, dict):
            for key in sorted(data.keys()):
                value = data[key]
                value_type = type(value).__name__
                print(f"  {key}: {value_type}")
        print()
        
        # Save to file
        output_file = f"/tmp/ticket-{ticket_id}-inspect.json"
        Path(output_file).write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print(f" Salvato in: {output_file}")
        
    except Exception as e:
        print(f" Errore: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
