#!/usr/bin/env python3
"""checkmk_config_backup.py - Full DR backup of CheckMK configuration.

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
LOG_FILE = BACKUP_BASE / "backup-dr.log"

RCLONE_REMOTE = os.getenv("RCLONE_REMOTE", "do:testmonbck")
RCLONE_PATH = os.getenv("RCLONE_PATH", "checkmk-backups/monitoring")
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "30"))
INCLUDE_RRD = os.getenv("INCLUDE_RRD", "false").lower() == "true"


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
    site_count = len(lines)

    if site_count == 1:
        print(f"[AUTO-DETECT] Rilevato site: {site}")
    else:
        print(f"[AUTO-DETECT] Trovati {site_count} site, uso: {site}")
        print(f"Per usare altro site: {Path(sys.argv[0]).name} <site_name>")

    return site


def read_file(path: Path, default: str = "N/A") -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return default


def safe_cmd_output(cmd: List[str], default: str = "N/A") -> str:
    result = run_cmd(cmd, check=False)
    output = (result.stdout or "").strip()
    return output if output else default


def safe_site_output(site: str, command: str, default: str = "N/A") -> str:
    result = run_site_cmd(site, command, check=False)
    output = (result.stdout or "").strip()
    return output if output else default


def ensure_remote_configured(site: str) -> None:
    log("[INFO] Verifica configurazione rclone...")
    remote_name = RCLONE_REMOTE.split(":", 1)[0] + ":"
    result = run_site_cmd(site, "rclone listremotes 2>/dev/null", check=False)
    remotes = result.stdout or ""

    if remote_name not in remotes:
        log(f"ERRORE: Remote rclone '{RCLONE_REMOTE}' non configurato per utente {site}")
        raise SystemExit(1)

    log(f"[OK] Remote rclone configurato: {RCLONE_REMOTE}")


def collect_metadata(site: str, site_base: Path, metadata_path: Path) -> None:
    log("[INFO] Raccolta metadati sistema")

    os_release = "N/A"
    for line in Path("/etc/os-release").read_text(encoding="utf-8", errors="ignore").splitlines() if Path("/etc/os-release").exists() else []:
        if line.startswith("PRETTY_NAME="):
            os_release = line.split("=", 1)[1].strip().strip('"')
            break

    edition = "N/A"
    version_raw = read_file(site_base / ".version", "")
    match = re.search(r'CMK_VERSION="([^"]+)"', version_raw)
    if match:
        edition = match.group(1)

    metadata = f"""=== CHECKMK DISASTER RECOVERY BACKUP ===
Backup date: {dt.datetime.now()}
Hostname: {safe_cmd_output(['hostname', '-f'])}
Site: {site}
CheckMK Version: {read_file(site_base / 'version')}
CheckMK Edition: {edition}
OS: {os_release}
Kernel: {safe_cmd_output(['uname', '-r'])}
OMD Version: {safe_cmd_output(['omd', 'version'])}
Python Version: {safe_site_output(site, 'python3 --version')}

=== DISK SPACE ===
{safe_cmd_output(['bash', '-lc', f"df -h {site_base} | tail -1"]) }

=== COMPONENT DIMENSIONS ===
Site directory: {safe_cmd_output(['bash', '-lc', f"du -sh {site_base} 2>/dev/null | cut -f1"])}
Config (etc/): {safe_cmd_output(['bash', '-lc', f"du -sh {site_base}/etc 2>/dev/null | cut -f1"])}
Local extensions: {safe_cmd_output(['bash', '-lc', f"du -sh {site_base}/local 2>/dev/null | cut -f1"])}
Var data: {safe_cmd_output(['bash', '-lc', f"du -sh {site_base}/var/check_mk 2>/dev/null | cut -f1"])}

=== MONITORED HOSTS ===
Host count: {safe_site_output(site, 'cmk --list-hosts 2>/dev/null | wc -l')}

=== ACTIVE SERVICES ===
{safe_site_output(site, 'omd status')}"""

    metadata_path.write_text(metadata, encoding="utf-8")
    log("[OK] Metadati raccolti")


def create_archive(site: str, site_base: Path, archive_path: Path) -> Tuple[str, int]:
    log("[INFO] Creazione backup DR completo")

    backup_items = [
        "etc/check_mk", "etc/omd", "etc/apache", "etc/ssl", "etc/htpasswd",
        "etc/auth.secret", "etc/auth.serials", "etc/environment", "var/check_mk/web",
        "var/check_mk/wato", "var/check_mk/agents", "var/check_mk/packages",
        "var/check_mk/inventory_archive", "local/share/check_mk/notifications",
        "local/lib/check_mk/notifications", "local/share/check_mk/checks",
        "local/share/check_mk/web/plugins", "local", "version", ".version",
    ]

    if INCLUDE_RRD:
        log("[WARNING] Backup RRD abilitato - il backup sarà molto grande!")
        backup_items.extend(["var/check_mk/rrd", "var/pnp4nagios/perfdata"])

    tar_items: List[str] = []
    for item in backup_items:
        if (site_base / item).exists():
            tar_items.append(item)
            log(f"  + Includo: {item}")
        else:
            log(f"  - Skip (non presente): {item}")

    if not tar_items:
        log("ERRORE: nessun elemento valido da includere nel backup")
        raise SystemExit(1)

    cmd = ["tar", "czf", str(archive_path), "-C", str(site_base)] + tar_items
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
    log(f"[INFO] SHA256: {checksum}")
    return checksum, size_bytes


def create_restore_instructions(path: Path, site: str) -> None:
    text = f"""=== DISASTER RECOVERY RESTORE INSTRUCTIONS ===

1) omd stop <SITE_NAME>
2) tar xzf checkmk-DR-<SITE_NAME>-<DATE>.tgz -C /opt/omd/sites/<SITE_NAME>/
3) chown -R <SITE_NAME>:<SITE_NAME> /opt/omd/sites/<SITE_NAME>
4) omd start <SITE_NAME>
5) on - <SITE_NAME> -c 'cmk -R && cmk -O'

NOTES:
- Reinstall Ydea integration and cronjob if necessary.
- INCLUDE_RRD={str(INCLUDE_RRD).lower()} in source backup."""
    path.write_text(text, encoding="utf-8")


def upload_file(site: str, local_path: Path, remote_dir: str, immutable: bool = True) -> None:
    cfg = f"/opt/omd/sites/{site}/.config/rclone/rclone.conf"
    imm = "--immutable" if immutable else ""
    cmd = (
        f"rclone copy '{local_path}' '{remote_dir}' --config='{cfg}' "
        f"--checksum --s3-no-check-bucket {imm} --transfers 2 --log-level INFO"
    )
    result = run_site_cmd(site, cmd, check=False)
    if result.returncode != 0:
        log(f"ERRORE upload {local_path.name}: {result.stderr.strip()}")
        raise SystemExit(1)


def verify_remote_size(site: str, archive_name: str, local_size: int) -> None:
    target = f"{RCLONE_REMOTE}/{RCLONE_PATH}/{archive_name}"
    check = run_site_cmd(site, f"rclone lsf '{target}'", check=False)
    if check.returncode != 0:
        log("ERRORE: File non trovato su storage remoto")
        raise SystemExit(1)

    size_res = run_site_cmd(site, f"rclone lsf '{target}' --format s", check=False)
    remote_size = int((size_res.stdout or "0").strip() or "0")
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
        mtime_raw, rel_path = parts[0].strip(), parts[1].strip()
        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", mtime_raw)
        if not date_match:
            continue
        file_date = dt.datetime.strptime(date_match.group(1), "%Y-%m-%d").date()
        if file_date < cutoff:
            log(f"  - Rimuovo file obsoleto: {rel_path} (data: {file_date})")
            run_site_cmd(site, f"rclone delete '{RCLONE_REMOTE}/{RCLONE_PATH}/{rel_path}'", check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup DR completo configurazione CheckMK")
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
    log(f"=== INIZIO BACKUP DR per site {site} (v{VERSION}) ===")

    ensure_remote_configured(site)

    date_token = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive_name = f"checkmk-DR-{site}-{date_token}.tgz"
    metadata_name = f"checkmk-DR-{site}-{date_token}.metadata.txt"

    archive_path = TMP_DIR / archive_name
    metadata_path = TMP_DIR / metadata_name
    restore_path = TMP_DIR / "RESTORE_INSTRUCTIONS.txt"

    collect_metadata(site, site_base, metadata_path)
    checksum, local_size = create_archive(site, site_base, archive_path)
    with metadata_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n=== CHECKSUM ===\nSHA256: {checksum}\n")

    create_restore_instructions(restore_path, site)

    remote_dir = f"{RCLONE_REMOTE}/{RCLONE_PATH}"
    log(f"[INFO] Upload su storage remoto: {remote_dir}")
    upload_file(site, archive_path, remote_dir)
    upload_file(site, metadata_path, remote_dir)
    upload_file(site, restore_path, remote_dir)
    log("[OK] Upload completato")

    verify_remote_size(site, archive_name, local_size)
    apply_retention(site)

    for path in [archive_path, metadata_path, restore_path]:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    size_human = f"{local_size} bytes"
    log("=== BACKUP DR COMPLETATO CON SUCCESSO ===")
    log(f"Archivio: {archive_name}")
    log(f"Dimensione: {size_human}")
    log(f"Checksum: {checksum}")
    log(f"Destinazione: {remote_dir}")
    log(f"Include RRD: {str(INCLUDE_RRD).lower()}")
    log(f"Retention: {RETENTION_DAYS} giorni")
    return 0


if __name__ == "__main__":
    sys.exit(main())
