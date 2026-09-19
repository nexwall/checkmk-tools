from __future__ import annotations

import shutil
from pathlib import Path

from lib.common import log_header, log_info, log_success, log_warn
from lib.config import InstallerConfig


def _find_repo_root() -> Path | None:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "script-notify-checkmk" / "full").exists():
            return parent
    return None


def run_step(cfg: InstallerConfig) -> None:
    log_header("65-NOTIFY-SCRIPTS")

    repo_root = _find_repo_root()
    if repo_root is None:
        log_warn("Repository root non trovato (script-notify-checkmk/full mancante). Skip.")
        return

    src_dir = repo_root / "script-notify-checkmk" / "full"
    dest_dir = Path(f"/omd/sites/{cfg.site_name}/local/share/check_mk/notifications")

    if not dest_dir.exists():
        # If the OMD site exists, we create the directory (it is not created automatically by omd create)
        site_dir = Path(f"/omd/sites/{cfg.site_name}")
        if not site_dir.exists():
            log_warn(f"Sito OMD non trovato: {site_dir}. CheckMK non installato? Skip.")
            return
        log_info(f"Creazione directory notifiche: {dest_dir}")
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Imposta ownership al sito OMD
        import subprocess
        subprocess.run(["chown", "-R", f"{cfg.site_name}:{cfg.site_name}", str(dest_dir)], check=False)

    # Copy only files without .py extension (the actual CheckMK notification scripts)
    # Skip __pycache__ and .py helper files
    copied = 0
    for src_file in src_dir.iterdir():
        if src_file.is_dir():
            continue
        if src_file.suffix == ".py":
            continue
        if src_file.name.startswith("__"):
            continue

        dest_file = dest_dir / src_file.name
        shutil.copy2(src_file, dest_file)
        dest_file.chmod(0o755)
        log_info(f"  Copiato: {src_file.name} → {dest_dir}/")
        copied += 1

    # Also deploy ydea_cache_validator.py as helper (needed by ydea_ag / ydea_la)
    cache_validator = src_dir / "ydea_cache_validator.py"
    if cache_validator.exists():
        helper_dest = Path("/usr/local/lib/checkmk-notify")
        helper_dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cache_validator, helper_dest / cache_validator.name)
        log_info(f"  Copiato helper: {cache_validator.name} → {helper_dest}/")

    if copied == 0:
        log_warn("Nessuno script di notifica trovato da copiare.")
    else:
        log_success(f"{copied} script di notifica copiati in {dest_dir}")


def run(cfg: InstallerConfig) -> None:
    run_step(cfg)
