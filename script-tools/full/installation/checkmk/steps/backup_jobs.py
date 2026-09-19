from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from lib.common import log_header, log_info, log_success, log_warn
from lib.config import InstallerConfig

_SCRIPT_REL = "script-tools/full/backup_restore/install-backup-jobs.py"


def _find_script() -> Path | None:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        candidate = parent / _SCRIPT_REL
        if candidate.exists():
            return candidate
    return None


def run(cfg: InstallerConfig) -> None:
    log_header("100-BACKUP-JOBS")

    script = _find_script()
    if script is None:
        log_warn(f"Script non trovato: {_SCRIPT_REL}. Skip.")
        return

    log_info("Installa systemd timers per backup automatici CheckMK (job00 giornaliero 03:00, job01 settimanale domenica 04:00).")
    try:
        choice = input("Installare backup jobs adesso? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        choice = ""

    if choice != "y":
        log_warn("Skip installazione backup jobs.")
        return

    log_info("Avvio installazione backup jobs (interattivo)...")
    # Run from the script directory so that BASH_SOURCE[0] finds the companion files
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(script.parent),
        check=False,
    )
    if result.returncode == 0:
        log_success("Backup jobs installati")
    else:
        log_warn(f"Script terminato con codice {result.returncode} (verificare output sopra)")
