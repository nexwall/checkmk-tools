#!/usr/bin/env python3
"""analyze_custom_attributes.py - Analizza custom attributes ticket"""
import sys, json, importlib.util
from pathlib import Path
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))
spec = importlib.util.spec_from_file_location("ydea_toolkit", script_dir / "ydea-toolkit.py")
ydea_toolkit = importlib.util.module_from_spec(spec) if spec and spec.loader else None
if ydea_toolkit and spec and spec.loader: spec.loader.exec_module(ydea_toolkit)  # type: ignore
else: raise ImportError("Cannot load ydea-toolkit.py")
api = ydea_toolkit.YdeaAPI()
data, status = api.api_call("GET", "/tickets", {"limit": 50})
if status == 200:
    for ticket in data.get("objs", []):
        custom_attrs = ticket.get("customAttributes") or ticket.get("custom_attributes")
        if custom_attrs:
            print(f"Ticket {ticket.get('id')}: {json.dumps(custom_attrs, ensure_ascii=False)}")
