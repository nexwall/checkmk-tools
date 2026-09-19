#!/usr/bin/env python3
"""update_scripts.py - Update CheckMK Scripts from Repo

Update the scripts installed on the system by copying them from the local repository.
Performs git pull and overwrites only existing files in known targets.
Replaces files only if VERSION or content hash changes.

Supported destinations:
- /opt/omd/sites/monitoring/local/bin
- /usr/lib/check_mk_agent/plugins
- /usr/lib/check_mk_agent/local
- /opt/ydea-toolkit

Usage:
    update_scripts.py [repo_dir]

Version: 1.2.1"""

import hashlib
import gzip
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

VERSION = "1.2.1"
DEFAULT_REPO_DIR = "/opt/checkmk-tools"
BACKUP_BASE = "/tmp/scripts-backup"
LOG_FILE = Path(os.getenv("CHECKMK_AUTOHEAL_LOG_FILE", "/var/log/checkmk_server_autoheal.log"))
MAX_LOG_SIZE_BYTES = int(os.getenv("CHECKMK_AUTOHEAL_LOG_MAX_BYTES", "10485760"))

MAPPINGS = [
    ("script-notify-checkmk", "/opt/omd/sites/monitoring/local/share/check_mk/notifications"),
    ("script-check-ns7", "/usr/lib/check_mk_agent/plugins"),
    ("script-check-ns7", "/usr/lib/check_mk_agent/local"),
    ("script-check-ns8", "/usr/lib/check_mk_agent/plugins"),
    ("script-check-ns8", "/usr/lib/check_mk_agent/local"),
    ("script-check-ubuntu", "/usr/lib/check_mk_agent/plugins"),
    ("script-check-ubuntu", "/usr/lib/check_mk_agent/local"),
    ("script-check-proxmox", "/usr/lib/check_mk_agent/plugins"),
    ("script-check-proxmox", "/usr/lib/check_mk_agent/local"),
    ("script-tools/full", "/opt/omd/sites/monitoring/local/bin"),
    ("Ydea-Toolkit", "/opt/ydea-toolkit"),
]


class Console:
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    RED = "\033[0;31m"
    NC = "\033[0m"

    @staticmethod
    def _rotate_log_if_needed() -> None:
        try:
            if not LOG_FILE.exists():
                return
            size = LOG_FILE.stat().st_size
            if size < MAX_LOG_SIZE_BYTES:
                return

            rotated = LOG_FILE.with_suffix(LOG_FILE.suffix + ".1")
            rotated_gz = Path(str(rotated) + ".gz")

            if rotated_gz.exists():
                rotated_gz.unlink()
            if rotated.exists():
                rotated.unlink()

            shutil.move(str(LOG_FILE), str(rotated))
            with rotated.open("rb") as source_file, gzip.open(rotated_gz, "wb") as target_file:
                shutil.copyfileobj(source_file, target_file)
            rotated.unlink(missing_ok=True)

            LOG_FILE.touch(exist_ok=True)
            LOG_FILE.chmod(0o666)
        except OSError:
            pass

    @staticmethod
    def _write_log(level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {message}\n"
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            Console._rotate_log_if_needed()
            with LOG_FILE.open("a", encoding="utf-8") as file_obj:
                file_obj.write(line)
        except OSError:
            pass

    @staticmethod
    def log(message: str) -> None:
        print(f"[INFO] {message}")
        Console._write_log("INFO", message)

    @staticmethod
    def warn(message: str) -> None:
        print(f"{Console.YELLOW}[WARN] {message}{Console.NC}")
        Console._write_log("WARN", message)

    @staticmethod
    def error(message: str) -> None:
        print(f"{Console.RED}[ERROR] {message}{Console.NC}")
        Console._write_log("ERROR", message)

    @staticmethod
    def success(message: str) -> None:
        print(f"{Console.GREEN}[OK] {message}{Console.NC}")
        Console._write_log("OK", message)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        while True:
            chunk = file_obj.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def extract_version(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""

    for raw in content.splitlines():
        line = raw.strip()
        if not line.startswith("VERSION"):
            continue
        if "=" not in line:
            continue
        _, value = line.split("=", 1)
        return value.strip().strip('"').strip("'")
    return ""


def run_cmd(cmd: list[str], cwd: Optional[Path] = None) -> bool:
    try:
        subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def update_repo(repo_dir: Path) -> None:
    Console.log(f"Aggiorno repository: {repo_dir}")
    if not (repo_dir / ".git").exists():
        Console.error(f"Non è un repository git: {repo_dir}")
        raise SystemExit(1)

    run_cmd(["git", "stash"], cwd=repo_dir)

    if run_cmd(["git", "pull", "--rebase", "origin", "main"], cwd=repo_dir):
        Console.success("Git pull completato")
    else:
        Console.warn("Git pull fallito (proseguo con versione locale)")


def resolve_src(repo_dir: Path, src_rel: str) -> Optional[Path]:
    direct_path = repo_dir / src_rel
    if direct_path.exists():
        return direct_path
    full_path = repo_dir / src_rel / "full"
    if full_path.exists():
        return full_path
    return None


def update_files(repo_dir: Path, src_rel: str, dest_dir: str, backup_dir: Path) -> int:
    update_count = 0
    destination = Path(dest_dir)
    if not destination.exists():
        return 0

    source_root = resolve_src(repo_dir, src_rel)
    if not source_root:
        Console.warn(f"Sorgente non trovata nel repo: {src_rel}")
        return 0

    Console.log(f"Aggiorno {destination} da {src_rel}...")

    for existing in destination.iterdir():
        if not existing.is_file() or existing.name.startswith("."):
            continue

        source_file = source_root / existing.name
        if not source_file.exists():
            continue

        src_hash = file_sha256(source_file)
        dst_hash = file_sha256(existing)
        src_version = extract_version(source_file)
        dst_version = extract_version(existing)

        hash_changed = src_hash != dst_hash
        version_changed = src_version != dst_version
        if not hash_changed and not version_changed:
            continue

        rel_path = existing.relative_to("/")
        backup_path = backup_dir / str(rel_path).replace(os.sep, "_")
        shutil.copy2(existing, backup_path)

        try:
            file_stat = existing.stat()
            shutil.copy2(source_file, existing)
            os.chown(existing, file_stat.st_uid, file_stat.st_gid)
            os.chmod(existing, file_stat.st_mode)
            update_count += 1

            reasons: list[str] = []
            if version_changed:
                reasons.append(f"version {dst_version or 'n/a'} -> {src_version or 'n/a'}")
            if hash_changed:
                reasons.append("hash changed")
            reason_text = ", ".join(reasons) if reasons else "content changed"
            Console.log(f"Updated: {existing.name} ({reason_text})")
        except Exception as exc:
            Console.error(f"Errore aggiornamento {existing.name}: {exc}")

    return update_count


def main() -> None:
    Console.log(f"update_scripts.py v{VERSION}")
    Console.log(f"Server autoheal log: {LOG_FILE}")

    repo_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_REPO_DIR)
    if not repo_dir.exists():
        Console.error(f"Repository path not found: {repo_dir}")
        raise SystemExit(1)

    backup_timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = Path(BACKUP_BASE) / backup_timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    update_repo(repo_dir)

    total_updated = 0
    for source_rel, destination in MAPPINGS:
        total_updated += update_files(repo_dir, source_rel, destination, backup_dir)

    Console.success(f"Totale file aggiornati: {total_updated}")
    Console.log(f"Backup salvato in: {backup_dir}")


if __name__ == "__main__":
    main()
