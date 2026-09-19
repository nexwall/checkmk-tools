from __future__ import annotations

import subprocess
from pathlib import Path

from lib.common import log_header, log_info, log_success, log_warn
from lib.config import InstallerConfig

_SCRIPT_REL = "script-tools/full/backup_restore/checkmk_rclone_space_dyn.py"


def _find_script() -> Path | None:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        candidate = parent / _SCRIPT_REL
        if candidate.exists():
            return candidate
    return None


def run(cfg: InstallerConfig) -> None:
    log_header("102-RCLONE-SETUP")

    script = _find_script()
    if script is None:
        log_warn(f"Script non trovato: {_SCRIPT_REL}. Skip.")
        return

    log_info("Configura rclone per backup cloud (DigitalOcean Spaces / S3) del sito CheckMK.")
    log_info("Installa rclone se mancante, configura remote e systemd timer per backup automatici.")
    try:
        choice = input("Configurare rclone e backup cloud adesso? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        choice = ""

    if choice != "y":
        log_warn("Skip configurazione rclone.")
        return

    log_info("Avvio setup rclone (interattivo)...")
    result = subprocess.run(["python3", str(script), "setup"], check=False)
    if result.returncode == 0:
        log_success("rclone configurato e backup cloud attivato")
    else:
        log_warn(f"Setup terminato con codice {result.returncode} (verificare output sopra)")
