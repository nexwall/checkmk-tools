#!/usr/bin/env python3
"""checkmk_config_backup_ultra_minimal.py - CheckMK ultra-minimal backup.

Version: 1.0.0"""

import argparse
import datetime as dt
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

VERSION = "1.0.0"

BACKUP_BASE = Path("/opt/checkmk-backup")
TMP_DIR = BACKUP_BASE / "tmp"
LOG_FILE = BACKUP_BASE / "backup-ultra-minimal.log"

RCLONE_REMOTE = os.getenv("RCLONE_REMOTE", "do:testmonbck")
RCLONE_PATH = os.getenv("RCLONE_PATH", "checkmk-backups/monitoring-minimal")
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "90"))


def log(message: str) -> None:
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def run_cmd(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def run_site_cmd(site: str, command: str, check: bool = True) -> subprocess.CompletedProcess:
    return run_cmd(["su", "-", site, "-c", command], check=check)


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def detect_site(site_arg: str = "") -> str:
    if site_arg:
        return site_arg

    if not command_exists("omd"):
        print("ERRORE: comando 'omd' non trovato. CheckMK non installato?", file=sys.stderr)
        sys.exit(1)

    result = run_cmd(["omd", "sites"], check=False)
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip() and not line.startswith("SITE")]
    if not lines:
        print("ERRORE: Nessun site CheckMK trovato", file=sys.stderr)
        sys.exit(1)

    site = lines[0].split()[0]
    if len(lines) == 1:
        print(f"[AUTO-DETECT] Rilevato site: {site}")
    else:
        print(f"[AUTO-DETECT] Trovati {len(lines)} site, uso: {site}")
    return site


def ensure_remote(site: str) -> None:
    log("[INFO] Verifica configurazione rclone...")
    remote_name = RCLONE_REMOTE.split(":", 1)[0] + ":"
    result = run_site_cmd(site, "rclone listremotes 2>/dev/null", check=False)
    remotes = result.stdout or ""
    if remote_name not in remotes:
        log(f"ERRORE: Remote rclone '{RCLONE_REMOTE}' non configurato per utente {site}")
        raise SystemExit(1)
    log(f"[OK] Remote rclone configurato: {RCLONE_REMOTE}")


def collect_metadata(site: str, site_base: Path, metadata_path: Path) -> None:
    version = "N/A"
    dot_version = site_base / ".version"
    if dot_version.is_file():
        import re as _re
        raw = dot_version.read_text(encoding="utf-8", errors="ignore")
        m = _re.search(r'CMK_VERSION="([^"]+)"', raw)
        version = m.group(1) if m else raw.strip()
    else:
        result = run_site_cmd(site, "omd version", check=False)
        if result.returncode == 0:
            version = result.stdout.strip()

    metadata = f"""=== CHECKMK ULTRA-MINIMAL BACKUP ===
Backup date: {dt.datetime.now()}
Site: {site}
CheckMK Version: {version}

=== BACKUP STRATEGY ===
Type: ULTRA-MINIMAL
Includes: conf.d, multisite.d, backup.mk, notifications, web, wato, version, ydea-toolkit
Excluded: historical WATO snapshots, web users, RRD, inventory, bakery, cache"""
    metadata_path.write_text(metadata, encoding="utf-8")
    log("[OK] Metadati raccolti")


def create_archive(site: str, site_base: Path, archive_path: Path) -> Tuple[str, int]:
    log("[INFO] Creazione backup ULTRA-MINIMALE")

    backup_items = [
        "etc/check_mk/conf.d",
        "etc/check_mk/multisite.d",
        "etc/check_mk/backup.mk",
        "local/share/check_mk/notifications",
        "var/check_mk/wato",
        "var/check_mk/web",
        "version",
        "../../../ydea-toolkit",
    ]

    exclude_patterns = [
        "var/check_mk/wato/snapshots/*.tar",
        "var/check_mk/wato/snapshots/workdir",
        "var/check_mk/wato/log/*.log",
        "var/check_mk/wato/*/replication_changes*",
        "var/check_mk/wato/*/activation_state*",
        "../../../ydea-toolkit/cache/*",
    ]

    include_args: List[str] = []
    for item in backup_items:
        full_path = (site_base / item).resolve()
        if full_path.exists():
            include_args.append(item)
            size = run_cmd(["bash", "-lc", f"du -sh '{full_path}' 2>/dev/null | cut -f1"], check=False)
            size_text = (size.stdout or "N/A").strip() or "N/A"
            log(f"   Include: {item} ({size_text})")
        else:
            log(f"    Skip: {item} (non esiste)")

    if not include_args:
        log("ERRORE: Nessun file da backuppare trovato")
        raise SystemExit(1)

    cmd = ["tar", "czf", str(archive_path)]
    for pattern in exclude_patterns:
        cmd.append(f"--exclude={pattern}")
    cmd.extend(include_args)

    result = subprocess.run(
        cmd,
        cwd=str(site_base),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        log(f"ERRORE: Creazione archivio fallita: {result.stderr.strip()}")
        raise SystemExit(1)

    size_bytes = archive_path.stat().st_size
    size_h = run_cmd(["bash", "-lc", f"du -h '{archive_path}' | cut -f1"], check=False)
    size_human = (size_h.stdout or "").strip() or f"{size_bytes} bytes"
    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()

    log(f"[OK] Archivio creato: {archive_path.name} ({size_human})")
    log(f"[OK] SHA256: {checksum}")
    return checksum, size_bytes


def upload(site: str, local_path: Path, remote_target: str) -> None:
    cmd = (
        f"rclone copy '{local_path}' '{remote_target}' "
        "--s3-no-check-bucket --config=$HOME/.config/rclone/rclone.conf"
    )
    result = run_site_cmd(site, cmd, check=False)
    if result.returncode != 0:
        log(f"ERRORE upload {local_path.name}: {result.stderr.strip()}")
        raise SystemExit(1)


def apply_retention(site: str) -> None:
    log(f"[INFO] Applicazione retention remota ({RETENTION_DAYS} giorni)")
    cutoff = dt.date.today() - dt.timedelta(days=RETENTION_DAYS)

    ls = run_site_cmd(
        site,
        f"rclone lsf '{RCLONE_REMOTE}/{RCLONE_PATH}/' --format 'tp' --s3-no-check-bucket --config=$HOME/.config/rclone/rclone.conf",
        check=False,
    )

    for line in (ls.stdout or "").splitlines():
        if "checkmk-ULTRA-MINIMAL" not in line or not line.endswith(".tgz"):
            continue

        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        mtime, filename = parts[0].strip(), parts[1].strip()

        match = re.match(r"(\d{4}-\d{2}-\d{2})", mtime)
        if not match:
            continue

        file_date = dt.datetime.strptime(match.group(1), "%Y-%m-%d").date()
        if file_date < cutoff:
            age_days = (dt.date.today() - file_date).days
            log(f"    Cancello backup vecchio ({age_days} giorni): {filename}")
            run_site_cmd(
                site,
                f"rclone delete '{RCLONE_REMOTE}/{RCLONE_PATH}/{filename}' --s3-no-check-bucket --config=$HOME/.config/rclone/rclone.conf",
                check=False,
            )
            metadata = filename.replace(".tgz", ".metadata.txt")
            run_site_cmd(
                site,
                f"rclone delete '{RCLONE_REMOTE}/{RCLONE_PATH}/{metadata}' --s3-no-check-bucket --config=$HOME/.config/rclone/rclone.conf",
                check=False,
            )


def create_restore_file(path: Path) -> None:
    text = """=== RESTORE INSTRUCTIONS FROM ULTRA-MINIMAL BACKUP ===

1) omd stop <site>
2) cd /opt/omd/sites/<site>
3) tar xzf /tmp/<backup.tgz>
4) chown -R <site>:<site> /opt/omd/sites/<site>
5) chown -R root:root /opt/ydea-toolkit
6) omd start <site>
7) cmk -R

Restored: hosts/rules, dashboard, custom notifications, ydea-toolkit.
To recreate: web users, custom SSL certificates."""
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup ultra-minimale CheckMK")
    parser.add_argument("site", nargs="?", default="", help="Nome site CheckMK (opzionale)")
    args = parser.parse_args()

    site = detect_site(args.site)
    site_base = Path(f"/opt/omd/sites/{site}")

    if not site_base.exists():
        log(f"ERRORE: site {site} non trovato in {site_base}")
        return 1
    if not command_exists("rclone"):
        log("ERRORE: rclone non installato")
        return 1

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    log(f"=== INIZIO BACKUP ULTRA-MINIMALE per site {site} (v{VERSION}) ===")
    ensure_remote(site)

    date_token = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive_name = f"checkmk-ULTRA-MINIMAL-{site}-{date_token}.tgz"
    metadata_name = f"checkmk-ULTRA-MINIMAL-{site}-{date_token}.metadata.txt"

    archive_path = TMP_DIR / archive_name
    metadata_path = TMP_DIR / metadata_name
    restore_path = TMP_DIR / "RESTORE_INSTRUCTIONS_ULTRA_MINIMAL.txt"

    collect_metadata(site, site_base, metadata_path)
    checksum, size_bytes = create_archive(site, site_base, archive_path)

    with metadata_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n=== VERIFICA INTEGRITÀ ===\nSHA256: {checksum}\nDimensione: {size_bytes} bytes\n")

    remote_dir = f"{RCLONE_REMOTE}/{RCLONE_PATH}/"
    log(f"[INFO] Upload su storage remoto {remote_dir}")
    upload(site, archive_path, remote_dir)
    upload(site, metadata_path, remote_dir)

    create_restore_file(restore_path)
    upload(site, restore_path, f"{RCLONE_REMOTE}/{RCLONE_PATH}/")

    for path in [archive_path, metadata_path, restore_path]:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    apply_retention(site)

    log("=== BACKUP ULTRA-MINIMALE COMPLETATO CON SUCCESSO ===")
    log(f"Archivio: {archive_name}")
    log(f"Dimensione: {size_bytes} bytes")
    log(f"Checksum: {checksum}")
    log(f"Destinazione: {remote_dir}")
    log(f"Retention: {RETENTION_DAYS} giorni")
    log("=== FINE SCRIPT ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
