#!/usr/bin/env python3
"""esempi_ydea.py - Esempi uso API Ydea"""
import sys, json, importlib.util
from pathlib import Path
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))
spec = importlib.util.spec_from_file_location("ydea_toolkit", script_dir / "ydea-toolkit.py")
ydea_toolkit = importlib.util.module_from_spec(spec) if spec and spec.loader else None
if ydea_toolkit and spec and spec.loader: spec.loader.exec_module(ydea_toolkit)  # type: ignore
else: raise ImportError("Cannot load ydea-toolkit.py")
api = ydea_toolkit.YdeaAPI()
print("Esempi API Ydea:")
print("1. Get tickets:", api.api_call("GET", "/tickets", {"limit": 5})[1])
print("2. Get categories:", api.api_call("GET", "/categories")[1])
