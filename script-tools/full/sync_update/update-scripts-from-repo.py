#!/usr/bin/env python3
"""update-scripts-from-repo.py

Python entrypoint that delegates to update-scripts-from-repo.sh.
Version: 1.0.0"""

import os
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0"


def usage() -> None:
    print(
        "Usage:\n"
        "  update-scripts-from-repo.py [args]\n\n"
        "Delegates to update-scripts-from-repo.sh for full workflow."
    )


def main() -> int:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        usage()
        return 0

    script = Path(__file__).with_name("update-scripts-from-repo.sh")
    if not script.exists():
        print(f"ERROR: missing target script: {script}", file=sys.stderr)
        return 1

    result = subprocess.run(["bash", str(script), *sys.argv[1:]], env=os.environ.copy())
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
