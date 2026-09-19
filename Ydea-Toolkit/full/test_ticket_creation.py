#!/usr/bin/env python3
"""test_ticket_creation.py - Test creazione ticket"""
import sys, json, importlib.util
from pathlib import Path
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))
spec = importlib.util.spec_from_file_location("ydea_toolkit", script_dir / "ydea-toolkit.py")
ydea_toolkit = importlib.util.module_from_spec(spec) if spec and spec.loader else None
if ydea_toolkit and spec and spec.loader: spec.loader.exec_module(ydea_toolkit)  # type: ignore
else: raise ImportError("Cannot load ydea-toolkit.py")
api = ydea_toolkit.YdeaAPI()
ticket = {"titolo": "Test", "descrizione": "Test ticket creation", "priorita_id": 30}
data, status = api.api_call("POST", "/tickets", ticket)
print(json.dumps(data, indent=2, ensure_ascii=False) if status in [200, 201] else f"Error: {status}")
