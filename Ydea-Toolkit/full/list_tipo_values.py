#!/usr/bin/env python3
"""list_tipo_values.py - List of possible values for ticket 'type' field

Usage:
    list_type_values.py

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
    try:
        api = YdeaAPI()
        
        print(" Lista valori 'tipo' ticket")
        print("=" * 60)
        
        # Get tickets e estrai valori tipo unici
        data, status = api.api_call("GET", "/tickets", {"limit": 100})
        
        if status == 200:
            tickets = data.get("objs", [])
            tipo_values = set()
            
            for ticket in tickets:
                tipo = ticket.get("tipo")
                if tipo:
                    tipo_values.add(tipo)
            
            print(f"\n Trovati {len(tipo_values)} valori unici:\n")
            for tipo in sorted(tipo_values):
                print(f"  - {tipo}")
        else:
            print(f"\n Errore: Status {status}")
            sys.exit(1)
    except Exception as e:
        print(f" Errore: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
