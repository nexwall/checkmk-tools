#!/usr/bin/env python3
"""Wrapper deprecated variant.
Use checkmk-tuning-interactive.py
Version: 1.0.0"""

import subprocess
import sys
from pathlib import Path


def usage() -> None:
    print(
        "Usage:\n"
        "  checkmk-tuning-interactive-v5.py [args]\n\n"
        "Deprecated wrapper to checkmk-tuning-interactive.py"
    )


def main() -> int:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        usage()
        return 0

    script = Path(__file__).with_name("checkmk-tuning-interactive.py")
    if not script.exists():
        print(f"ERROR: missing target script: {script}", file=sys.stderr)
        return 1
    result = subprocess.run([sys.executable, str(script), *sys.argv[1:]])
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
