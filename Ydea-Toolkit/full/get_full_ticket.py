#!/usr/bin/env python3
"""get_full_ticket.py - Retrieve full ticket with all details

Usage:
    get_full_ticket.py <ticket_id>

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
        print("Usage: get_full_ticket.py <ticket_id>", file=sys.stderr)
        sys.exit(1)
    
    ticket_id = sys.argv[1]
    
    try:
        api = YdeaAPI()
        data, status = api.api_call("GET", f"/tickets/{ticket_id}")
        
        if status == 200:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(f"Error: Status {status}", file=sys.stderr)
            print(json.dumps(data, indent=2, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
