#!/usr/bin/env python3
"""checkmk_restore_dr.py

Python entrypoint for the interactive DR restore workflow.
Delegates to the existing canonical shell implementation to preserve full behavior.
Version: 1.0.0"""

import os
import subprocess
import sys
from pathlib import Path


def usage() -> None:
    print(
        "Usage:\n"
        "  checkmk_restore_dr.py [args]\n\n"
        "Delegates to checkmk_restore_dr.sh for full interactive DR restore workflow."
    )


def main() -> int:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        usage()
        return 0

    script = Path(__file__).with_name("checkmk_restore_dr.sh")
    if not script.exists():
        print(f"ERROR: missing target script: {script}", file=sys.stderr)
        return 1

    cmd = ["bash", str(script), *sys.argv[1:]]
    result = subprocess.run(cmd, env=os.environ.copy())
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
