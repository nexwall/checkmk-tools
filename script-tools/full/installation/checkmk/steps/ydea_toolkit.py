from __future__ import annotations

from pathlib import Path

from lib.common import log_header, log_info, log_success, log_warn, run as run_cmd
from lib.config import InstallerConfig


def _find_repo_root() -> Path | None:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "Ydea-Toolkit" / "full").exists():
            return parent
    return None


def run_step(cfg: InstallerConfig) -> None:
    log_header("70-YDEA-TOOLKIT")

    repo_root = _find_repo_root()
    if repo_root is None:
        log_warn("Repository root non trovato (Ydea-Toolkit/full mancante). Skip.")
        return

    installer = repo_root / "Ydea-Toolkit" / "full" / "install_ydea_checkmk_integration.py"
    if not installer.exists():
        log_warn(f"install_ydea_checkmk_integration.py non trovato in: {installer}. Skip.")
        return

    print("")
    log_info("Ydea-Toolkit: integrazione CheckMK → Ydea disponibile.")
    print("")
    ans = input("Configurare integrazione Ydea adesso? [y/N]: ").strip().lower()
    if ans not in {"y", "yes"}:
        log_info("Integrazione Ydea saltata. Esegui manualmente quando pronto:")
        log_info(f"  sudo python3 {installer}")
        return

    log_info("Avvio installer integrazione Ydea (interattivo)...")
    run_cmd(["python3", str(installer)], check=False)
    log_success("Ydea-Toolkit: installer completato (verificare output sopra)")


def run(cfg: InstallerConfig) -> None:
    run_step(cfg)
