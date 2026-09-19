from __future__ import annotations

import subprocess
from pathlib import Path

from lib.common import log_header, log_info, log_success, log_warn
from lib.config import InstallerConfig

_SCRIPT_REL = "script-tools/full/upgrade_maintenance/setup_auto_updates.py"


def _find_script() -> Path | None:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        candidate = parent / _SCRIPT_REL
        if candidate.exists():
            return candidate
    return None


def run(cfg: InstallerConfig) -> None:
    log_header("85-SYSTEM-AUTO-UPDATES")

    script = _find_script()
    if script is None:
        log_warn(f"Script non trovato: {_SCRIPT_REL}. Skip.")
        return

    log_info("Configura aggiornamenti automatici di sistema (apt update/upgrade via cron).")
    try:
        choice = input("Configurare auto-aggiornamenti sistema adesso? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        choice = ""

    if choice != "y":
        log_warn("Skip configurazione auto-aggiornamenti sistema.")
        return

    log_info(f"Avvio configurazione (interattivo)...")
    result = subprocess.run(["python3", str(script)], check=False)
    if result.returncode == 0:
        log_success("Auto-aggiornamenti sistema configurati")
    else:
        log_warn(f"Setup terminato con codice {result.returncode} (verificare output sopra)")
