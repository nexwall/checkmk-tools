#!/usr/bin/env python3
"""search_anagrafica.py - Search registry by name

Usage:
    search_anagrafica.py <search_term>

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
        print("Usage: search_anagrafica.py <search_term>", file=sys.stderr)
        sys.exit(1)
    
    search_term = sys.argv[1]
    
    try:
        api = YdeaAPI()
        
        print(f" Ricerca anagrafica: {search_term}")
        print("=" * 60)
        
        data, status = api.api_call("GET", "/anagrafica", {"search": search_term})
        
        if status == 200:
            results = data.get("objs", [])
            print(f"\n Trovati {len(results)} risultati\n")
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            print(f"\n Errore: Status {status}")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            sys.exit(1)
    except Exception as e:
        print(f" Errore: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
