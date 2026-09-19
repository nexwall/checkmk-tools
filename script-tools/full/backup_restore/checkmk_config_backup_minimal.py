#!/usr/bin/env python3
"""checkmk_config_backup_minimal.py - CheckMK configuration minimal backup.

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
LOG_FILE = BACKUP_BASE / "backup-minimal.log"

RCLONE_REMOTE = os.getenv("RCLONE_REMOTE", "do:testmonbck")
RCLONE_PATH = os.getenv("RCLONE_PATH", "checkmk-backups/monitoring-minimal")
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "30"))


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


def safe_cmd(command: List[str], default: str = "N/A") -> str:
    result = run_cmd(command, check=False)
    output = (result.stdout or "").strip()
    return output if output else default


def safe_site(site: str, command: str, default: str = "N/A") -> str:
    result = run_site_cmd(site, command, check=False)
    output = (result.stdout or "").strip()
    return output if output else default


def ensure_remote(site: str) -> None:
    log("[INFO] Verifica configurazione rclone...")
    remote_name = RCLONE_REMOTE.split(":", 1)[0] + ":"
    remotes = safe_site(site, "rclone listremotes 2>/dev/null", "")
    if remote_name not in remotes:
        log(f"ERRORE: Remote rclone '{RCLONE_REMOTE}' non configurato per utente {site}")
        raise SystemExit(1)
    log(f"[OK] Remote rclone configurato: {RCLONE_REMOTE}")


def collect_metadata(site: str, site_base: Path, metadata_path: Path) -> None:
    version_text = ""
    try:
        version_text = (site_base / ".version").read_text(encoding="utf-8", errors="ignore")
    except Exception:
        pass
    edition_match = re.search(r'CMK_VERSION="([^"]+)"', version_text)
    edition = edition_match.group(1) if edition_match else "N/A"

    metadata = f"""=== CHECKMK MINIMAL BACKUP (CONFIG ONLY) ===
Backup date: {dt.datetime.now()}
Hostname: {safe_cmd(['hostname', '-f'])}
Site: {site}
CheckMK Version: {safe_cmd(['bash', '-lc', f"cat {site_base}/version 2>/dev/null || echo N/A"])}
CheckMK Edition: {edition}
OMD Version: {safe_cmd(['omd', 'version'])}
Python Version: {safe_site(site, 'python3 --version')}

=== MONITORED HOSTS ===
Host count: {safe_site(site, 'cmk --list-hosts 2>/dev/null | wc -l')}

=== BACKUP STRATEGY ===
Type: MINIMAL (configuration only)
Excluded: RRD, inventory, bakery, MKP"""
    metadata_path.write_text(metadata, encoding="utf-8")
    log("[OK] Metadati raccolti")


def create_archive(site_base: Path, archive_path: Path) -> Tuple[str, int]:
    log("[INFO] Creazione backup MINIMALE (solo config essenziale)")

    backup_items = [
        "etc/check_mk", "etc/omd", "etc/apache", "etc/ssl", "etc/htpasswd",
        "etc/auth.secret", "etc/auth.serials", "etc/environment", "var/check_mk/web",
        "var/check_mk/wato", "local/share/check_mk/notifications",
        "local/lib/check_mk/notifications", "version", ".version",
    ]
    exclude_patterns = [
        "local/share/check_mk/notifications/backup-giornaliero",
        "local/share/check_mk/notifications/__pycache__",
    ]

    tar_items = []
    for item in backup_items:
        if (site_base / item).exists():
            tar_items.append(item)
            log(f"   Includo: {item}")
        else:
            log(f"    Skip (non presente): {item}")

    if not tar_items:
        log("ERRORE: nessun file da backuppare trovato")
        raise SystemExit(1)

    cmd = ["tar", "czf", str(archive_path), "-C", str(site_base)]
    for pattern in exclude_patterns:
        cmd.append(f"--exclude={pattern}")
    cmd.extend(tar_items)

    result = run_cmd(cmd, check=False)
    if result.returncode != 0:
        log(f"ERRORE: tar fallito: {result.stderr.strip()}")
        raise SystemExit(1)

    verify = run_cmd(["tar", "tzf", str(archive_path)], check=False)
    if verify.returncode != 0:
        log("ERRORE: Archivio corrotto")
        raise SystemExit(1)

    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    size_bytes = archive_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    log(f"[OK] Dimensione archivio: {size_mb:.2f} MB")
    log(f"[INFO] SHA256: {checksum}")
    return checksum, size_bytes


def create_restore_instructions(path: Path) -> None:
    path.write_text(
        """=== MINIMAL RESTORE BACKUP INSTRUCTIONS ===

1) omd stop <SITE_NAME>
2) tar xzf checkmk-MINIMAL-<SITE_NAME>-<DATE>.tgz -C /opt/omd/sites/<SITE_NAME>/
3) chown -R <SITE_NAME>:<SITE_NAME> /opt/omd/sites/<SITE_NAME>
4) omd start <SITE_NAME>
5) on - <SITE_NAME> -c 'cmk -R && cmk -O'
6) Regenerate Agent Bakery (cmk --bake-agents)

Note: Historical charts not included (RRD excluded).""",
        encoding="utf-8",
    )


def upload(site: str, local_path: Path, remote_dir: str) -> None:
    cfg = f"/opt/omd/sites/{site}/.config/rclone/rclone.conf"
    cmd = (
        f"rclone copy '{local_path}' '{remote_dir}' --config='{cfg}' "
        "--checksum --immutable --s3-no-check-bucket --transfers 2 --log-level INFO"
    )
    result = run_site_cmd(site, cmd, check=False)
    if result.returncode != 0:
        log(f"ERRORE upload {local_path.name}: {result.stderr.strip()}")
        raise SystemExit(1)


def verify_remote_size(site: str, archive_name: str, local_size: int) -> None:
    target = f"{RCLONE_REMOTE}/{RCLONE_PATH}/{archive_name}"
    exists = run_site_cmd(site, f"rclone lsf '{target}'", check=False)
    if exists.returncode != 0:
        log("ERRORE: File non trovato su storage remoto")
        raise SystemExit(1)

    remote_size_raw = safe_site(site, f"rclone lsf '{target}' --format s", "0")
    try:
        remote_size = int(remote_size_raw)
    except ValueError:
        remote_size = 0

    if remote_size == local_size:
        log(f"[OK] Verifica dimensione: OK ({local_size} bytes)")
    else:
        log(f"WARNING: Dimensione locale ({local_size}) != remota ({remote_size})")


def apply_retention(site: str) -> None:
    log(f"[INFO] Applico retention ({RETENTION_DAYS} giorni)")
    cutoff = dt.date.today() - dt.timedelta(days=RETENTION_DAYS)
    ls = run_site_cmd(site, f"rclone lsf '{RCLONE_REMOTE}/{RCLONE_PATH}' --format 'tp'", check=False)

    for line in (ls.stdout or "").splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        mtime, rel_path = parts[0].strip(), parts[1].strip()

        if "MINIMAL" in rel_path:
            log(f"    Skip retention: {rel_path} (contiene MINIMAL)")
            continue

        match = re.match(r"(\d{4}-\d{2}-\d{2})", mtime)
        if not match:
            continue
        file_date = dt.datetime.strptime(match.group(1), "%Y-%m-%d").date()
        if file_date < cutoff:
            log(f"  - Rimuovo file obsoleto: {rel_path} (data: {file_date})")
            run_site_cmd(site, f"rclone delete '{RCLONE_REMOTE}/{RCLONE_PATH}/{rel_path}'", check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup minimale configurazione CheckMK")
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
    log(f"=== INIZIO BACKUP MINIMALE per site {site} (v{VERSION}) ===")

    ensure_remote(site)

    date_token = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive_name = f"checkmk-MINIMAL-{site}-{date_token}.tgz"
    metadata_name = f"checkmk-MINIMAL-{site}-{date_token}.metadata.txt"

    archive_path = TMP_DIR / archive_name
    metadata_path = TMP_DIR / metadata_name
    restore_path = TMP_DIR / "RESTORE_INSTRUCTIONS.txt"

    collect_metadata(site, site_base, metadata_path)
    checksum, size_bytes = create_archive(site_base, archive_path)
    with metadata_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n=== CHECKSUM ===\nSHA256: {checksum}\nDimensione: {size_bytes} bytes\n")

    create_restore_instructions(restore_path)

    remote_dir = f"{RCLONE_REMOTE}/{RCLONE_PATH}"
    log(f"[INFO] Upload su storage remoto: {remote_dir}")
    upload(site, archive_path, remote_dir)
    upload(site, metadata_path, remote_dir)
    upload(site, restore_path, remote_dir)
    log("[OK] Upload completato")

    verify_remote_size(site, archive_name, size_bytes)
    apply_retention(site)

    for path in [archive_path, metadata_path, restore_path]:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    log("=== BACKUP MINIMALE COMPLETATO CON SUCCESSO ===")
    log(f"Archivio: {archive_name}")
    log(f"Dimensione: {size_bytes} bytes")
    log(f"Checksum: {checksum}")
    log(f"Destinazione: {remote_dir}")
    log(f"Retention: {RETENTION_DAYS} giorni")
    return 0


if __name__ == "__main__":
    sys.exit(main())
