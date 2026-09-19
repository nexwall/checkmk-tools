from __future__ import annotations

import subprocess
from pathlib import Path

from lib.common import log_header, log_info, log_success, log_warn
from lib.config import InstallerConfig

_SCRIPT_REL = "script-tools/full/backup_restore/checkmk_config_backup_minimal.py"


def _find_script() -> Path | None:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        candidate = parent / _SCRIPT_REL
        if candidate.exists():
            return candidate
    return None


def run(cfg: InstallerConfig) -> None:
    log_header("110-CONFIG-BACKUP-MINIMAL")

    script = _find_script()
    if script is None:
        log_warn(f"Script non trovato: {_SCRIPT_REL}. Skip.")
        return

    log_info("Esegui backup minimale configurazione CheckMK (~1 MB, upload su rclone remote).")
    log_info("Richiede rclone configurato per l'utente del site OMD.")
    try:
        choice = input("Eseguire backup minimale adesso? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        choice = ""

    if choice != "y":
        log_warn("Skip backup minimale.")
        return

    log_info("Avvio backup minimale...")
    result = subprocess.run(["python3", str(script)], check=False)
    if result.returncode == 0:
        log_success("Backup minimale completato con successo")
    else:
        log_warn(f"Backup terminato con codice {result.returncode} (verificare output sopra)")
