from __future__ import annotations

import subprocess
from pathlib import Path

from lib.common import log_header, log_info, log_success, log_warn
from lib.config import InstallerConfig

_SCRIPT_REL = "script-tools/full/backup_restore/checkmk_config_backup.py"


def _find_script() -> Path | None:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        candidate = parent / _SCRIPT_REL
        if candidate.exists():
            return candidate
    return None


def run(cfg: InstallerConfig) -> None:
    log_header("105-CONFIG-BACKUP")

    script = _find_script()
    if script is None:
        log_warn(f"Script non trovato: {_SCRIPT_REL}. Skip.")
        return

    log_info("Esegui backup DR completo configurazione CheckMK (upload su rclone remote).")
    log_info("Richiede rclone configurato per l'utente del site OMD.")
    try:
        choice = input("Eseguire backup DR completo adesso? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        choice = ""

    if choice != "y":
        log_warn("Skip backup DR completo.")
        return

    log_info("Avvio backup DR...")
    result = subprocess.run(["python3", str(script)], check=False)
    if result.returncode == 0:
        log_success("Backup DR completato con successo")
    else:
        log_warn(f"Backup terminato con codice {result.returncode} (verificare output sopra)")
