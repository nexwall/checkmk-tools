#!/usr/bin/env python3
"""checkmk_compress_native_backup.py

Version: 1.0.0"""

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0"

BACKUP_DIR = Path("/var/backups/checkmk")
TMP_DIR = Path("/opt/checkmk-backup/tmp")
RCLONE_REMOTE = os.environ.get("RCLONE_REMOTE", "do:testmonbck")
RCLONE_PATH = os.environ.get("RCLONE_PATH", "checkmk-backups/monitoring-compressed")

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
NC = "\033[0m"

REMOVE_PATHS = [
    "monitoring/var/nagios",
    "monitoring/checkmk-tools",
    "monitoring/monitoring",
    "monitoring/var/check_mk/crashes",
    "monitoring/var/check_mk/rest_api",
    "monitoring/var/check_mk/precompiled_checks",
    "monitoring/var/check_mk/logwatch",
    "monitoring/var/check_mk/wato/snapshots",
    "monitoring/var/check_mk/wato/log",
    "monitoring/var/check_mk/inventory_archive",
    "monitoring/var/check_mk/background_jobs",
    "monitoring/var/tmp",
    "monitoring/tmp",
]


def log(message: str) -> None:
    now = dt.datetime.now().strftime("%H:%M:%S")
    print(f"{GREEN}[{now}]{NC} {message}")


def warn(message: str) -> None:
    print(f"{YELLOW}[WARN]{NC} {message}")


def error(message: str) -> None:
    print(f"{RED}[ERROR]{NC} {message}", file=sys.stderr)


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def find_complete_backup() -> tuple[Path, bool]:
    log(f"Cerco backup 'complete' in {BACKUP_DIR}...")

    complete = sorted(
        [p for p in BACKUP_DIR.glob("*-complete") if p.is_dir() and "-complete-" not in p.name],
        reverse=True,
    )

    if complete:
        return complete[0], False

    warn("Nessun backup 'complete' trovato, cerco backup più recente con timestamp...")
    renamed = sorted([p for p in BACKUP_DIR.glob("Check_MK-*-complete-*") if p.is_dir()], reverse=True)
    if renamed:
        return renamed[0], True

    raise FileNotFoundError(f"Nessun backup CheckMK trovato in {BACKUP_DIR}")


def human_size(path: Path) -> str:
    size = path.stat().st_size
    for unit in ["B", "K", "M", "G", "T"]:
        if size < 1024 or unit == "T":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return "0B"


def compress_site_tar(site_tar: Path, site: str) -> tuple[str, int]:
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    work_targz = TMP_DIR / f"site-{site}.tar.gz"
    work_tar = TMP_DIR / f"site-{site}.tar"

    shutil.copy2(site_tar, work_targz)

    log("Decomprimo tar.gz...")
    run(["gunzip", "-f", str(work_targz)])

    log("Rimuovo componenti pesanti con tar --delete (preserva metadati)...")
    for path in REMOVE_PATHS:
        log(f"   Rimuovo: {path}")
        run(["tar", "--delete", "-f", str(work_tar), path], check=False)

    log("Ricomprimo tar...")
    run(["gzip", "-f", str(work_tar)])

    compressed_bytes = work_targz.stat().st_size
    original_bytes = site_tar.stat().st_size
    reduction = 100 - (compressed_bytes * 100 // original_bytes)
    compressed_size = human_size(work_targz)

    log(f" Riduzione dimensione: {reduction}%")
    log("Sostituisco file originale con versione compressa...")

    shutil.move(str(work_targz), str(site_tar))

    chown_res = run(["chown", "monitoring:monitoring", str(site_tar)], check=False)
    if chown_res.returncode != 0:
        run(["chown", f"{site}:{site}", str(site_tar)], check=False)

    run(["chmod", "600", str(site_tar)], check=False)
    log(f" File sostituito: {site_tar} ({compressed_size})")

    return compressed_size, reduction


def rename_backup_if_needed(backup_path: Path, already_renamed: bool) -> Path:
    if already_renamed:
        return backup_path

    timestamp = dt.datetime.now().strftime("%Y-%m-%d-%Hh%M")
    new_name = f"{backup_path.name}-{timestamp}"
    new_path = backup_path.parent / new_name

    log(f"Rinomino directory con timestamp: {new_name}")
    backup_path.rename(new_path)
    log(" Directory rinominata")
    return new_path


def upload_backup(site: str, backup_path: Path, compressed_size: str) -> None:
    backup_name = backup_path.name
    log(f"Upload su {RCLONE_REMOTE}/{RCLONE_PATH}/{backup_name}/...")

    parent_dir = backup_path.parent
    command = (
        f"rclone copy '{parent_dir}/{backup_name}' '{RCLONE_REMOTE}/{RCLONE_PATH}/{backup_name}/' "
        f"--progress --s3-no-check-bucket --config=$HOME/.config/rclone/rclone.conf"
    )

    result = run(["su", "-", site, "-c", command], check=False)
    if result.returncode != 0:
        error("Upload fallito!")
        raise SystemExit(1)

    log(" Upload completato")
    log("   - mkbackup.info")
    log(f"   - site-{site}.tar.gz ({compressed_size})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compressione backup nativi CheckMK")
    parser.add_argument("site", nargs="?", default="monitoring", help="Nome site OMD (default: monitoring)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    site = args.site

    try:
        backup_path, already_renamed = find_complete_backup()
    except FileNotFoundError as exc:
        error(str(exc))
        return 1

    backup_name = backup_path.name
    site_tar = backup_path / f"site-{site}.tar.gz"

    if not site_tar.is_file():
        error(f"File {site_tar} non trovato!")
        return 1

    log(" Backup trovato, procedo con compressione")
    original_size = human_size(site_tar)
    log(f" Backup trovato: {backup_name}")
    log(f"   Dimensione originale: {original_size}")

    compressed_size, reduction = compress_site_tar(site_tar, site)
    backup_path = rename_backup_if_needed(backup_path, already_renamed)
    backup_name = backup_path.name

    upload_backup(site, backup_path, compressed_size)

    print()
    log("=== RIEPILOGO ===")
    log(f"Backup originale:    {original_size}")
    log(f"Backup compresso:    {compressed_size}")
    log(f"Riduzione:           {reduction}%")
    log(f"Directory locale:    {backup_path}/")
    log("  - mkbackup.info")
    log(f"  - site-{site}.tar.gz")
    log(f"Cloud:               {RCLONE_REMOTE}/{RCLONE_PATH}/{backup_name}/")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
