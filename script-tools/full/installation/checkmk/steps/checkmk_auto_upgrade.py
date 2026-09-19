from __future__ import annotations

import subprocess
from pathlib import Path

from lib.common import log_header, log_info, log_success, log_warn
from lib.config import InstallerConfig

_SCRIPT_REL = "script-tools/full/upgrade_maintenance/setup-auto-upgrade-checkmk.py"


def _find_script() -> Path | None:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        candidate = parent / _SCRIPT_REL
        if candidate.exists():
            return candidate
    return None


def run(cfg: InstallerConfig) -> None:
    log_header("90-CHECKMK-AUTO-UPGRADE")

    script = _find_script()
    if script is None:
        log_warn(f"Script non trovato: {_SCRIPT_REL}. Skip.")
        return

    log_info("Configura upgrade automatico di CheckMK tramite cron.")
    try:
        choice = input("Configurare auto-upgrade CheckMK adesso? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        choice = ""

    if choice != "y":
        log_warn("Skip configurazione auto-upgrade CheckMK.")
        return

    log_info("Avvio configurazione (interattivo)...")
    result = subprocess.run(["python3", str(script)], check=False)
    if result.returncode == 0:
        log_success("Auto-upgrade CheckMK configurato")
    else:
        log_warn(f"Setup terminato con codice {result.returncode} (verificare output sopra)")
