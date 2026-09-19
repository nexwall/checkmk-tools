#!/usr/bin/env python3
"""install-checkmk-log-optimizer.py

Python entrypoint that delegates to install-checkmk-log-optimizer.sh.
Version: 1.0.0"""

import os
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0"


def usage() -> None:
    print(
        "Usage:\n"
        "  install-checkmk-log-optimizer.py [args]\n\n"
        "Delegates to install-checkmk-log-optimizer.sh for full workflow."
    )


def main() -> int:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        usage()
        return 0

    script = Path(__file__).with_name("install-checkmk-log-optimizer.sh")
    if not script.exists():
        print(f"ERROR: missing target script: {script}", file=sys.stderr)
        return 1

    result = subprocess.run(["bash", str(script), *sys.argv[1:]], env=os.environ.copy())
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
