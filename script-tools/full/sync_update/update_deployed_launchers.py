#!/usr/bin/env python3
"""update_deployed_launchers.py - Updates launchers deployed from the repository.

Version: 1.0.0"""

import os
import shutil
import stat
import sys
from pathlib import Path

VERSION = "1.0.0"
REPO_PATH = Path("/omd/sites/monitoring/checkmk-tools")


def is_root() -> bool:
    return os.geteuid() == 0


def destination_for(repo_launcher: Path) -> Path | None:
    path_str = str(repo_launcher)
    launcher_name = repo_launcher.name

    if "Ydea-Toolkit" in path_str:
        return Path("/opt/ydea-toolkit") / launcher_name
    if "script-notify-checkmk" in path_str:
        return Path("/usr/local/bin/notify-checkmk") / launcher_name
    if "script-tools" in path_str:
        return Path("/opt/scripts") / launcher_name
    return None


def set_executable(path: Path) -> None:
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main() -> int:
    print(f"=== UPDATE DEPLOYED LAUNCHERS v{VERSION} ===\n")

    if not is_root():
        print(" Eseguire come root", file=sys.stderr)
        return 1

    if not REPO_PATH.exists():
        print(f" Repository non trovato: {REPO_PATH}")
        return 1

    updated = 0
    failed = 0

    for repo_launcher in REPO_PATH.rglob("r*.sh"):
        if not repo_launcher.is_file():
            continue

        dest = destination_for(repo_launcher)
        if dest is None:
            continue

        dest_dir = dest.parent
        if not dest_dir.exists():
            print(f" Creating directory: {dest_dir}")
            dest_dir.mkdir(parents=True, exist_ok=True)

        print(f" Updating: {repo_launcher.name} -> {dest}")
        try:
            shutil.copy2(repo_launcher, dest)
            set_executable(dest)
            print("   Updated")
            updated += 1
        except Exception as exc:
            print(f"   Failed: {exc}")
            failed += 1

    print("\n=== RIEPILOGO ===")
    print(f"Updated: {updated}")
    print(f"Failed:  {failed}")

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
