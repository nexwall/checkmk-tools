#!/usr/bin/env python3
"""setup-auto-upgrade-checkmk.py

Configure cron auto-upgrade using upgrade-checkmk.py (not shell).
Version: 1.1.0"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

VERSION = "1.1.0"
LOG_FILE = "/var/log/auto-upgrade-checkmk.log"


def run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def require_root() -> None:
    if os.geteuid() != 0:
        print("ERROR: eseguire come root", file=sys.stderr)
        raise SystemExit(1)


def choose_schedule() -> tuple[str, str]:
    print("Seleziona frequenza upgrade:")
    print("1) Settimanale (domenica 02:00)")
    print("2) Mensile (1° del mese 02:00)")
    print("3) Personalizzato")
    print("4) Annulla")
    choice = input("Scelta [1-4]: ").strip()

    if choice == "1":
        return "0 2 * * 0", "Settimanale (domenica 02:00)"
    if choice == "2":
        return "0 2 1 * *", "Mensile (1° del mese 02:00)"
    if choice == "3":
        cron = input("Inserisci cron (5 campi): ").strip()
        if len(cron.split()) != 5:
            print("ERROR: cron non valido", file=sys.stderr)
            raise SystemExit(1)
        return cron, f"Personalizzato: {cron}"
    raise SystemExit(0)


def ask_email() -> str:
    use_email = input("Vuoi notifiche email? [s/N]: ").strip().lower()
    if use_email != "s":
        return ""
    email = input("Inserisci email: ").strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        print("ERROR: email non valida", file=sys.stderr)
        raise SystemExit(1)
    return email


def detect_upgrade_script() -> str:
    candidates = [
        Path("/usr/local/bin/upgrade-checkmk.py"),
        Path("/opt/checkmk-tools/script-tools/full/upgrade_maintenance/upgrade-checkmk.py"),
        Path(__file__).with_name("upgrade-checkmk.py"),
    ]
    for path in candidates:
        if path.exists():
            return f"python3 {path}"
    print("ERROR: upgrade-checkmk.py non trovato", file=sys.stderr)
    raise SystemExit(1)


def read_crontab() -> str:
    result = run(["crontab", "-l"])
    return result.stdout if result.returncode == 0 else ""


def write_crontab(content: str) -> None:
    proc = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
    proc.communicate(content)
    if proc.returncode != 0:
        print("ERROR: scrittura crontab fallita", file=sys.stderr)
        raise SystemExit(1)


def main() -> int:
    print(f"setup-auto-upgrade-checkmk.py v{VERSION}")
    require_root()

    cron, description = choose_schedule()
    email = ask_email()
    upgrade_cmd = detect_upgrade_script()

    email_arg = f" --email {email}" if email else ""
    command = (
        f"(echo \"[$(date)] Starting CheckMK auto-upgrade\" && "
        f"{upgrade_cmd}{email_arg}; rc=$?; "
        f"if [ $rc -eq 0 ]; then "
        f"echo \"[$(date)] Upgrade check completed (no update or success)\"; "
        f"elif [ $rc -eq 2 ]; then "
        f"echo \"[$(date)] Upgrade failed, rollback executed\"; "
        f"else "
        f"echo \"[$(date)] Upgrade failed (rollback not executed)\"; "
        f"fi) >> {LOG_FILE} 2>&1"
    )
    cron_entry = f"{cron} {command}"

    old = read_crontab()
    backup = Path(f"/root/crontab_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    backup.write_text(old, encoding="utf-8")
    print(f"Backup crontab: {backup}")

    filtered = []
    for line in old.splitlines():
        if "upgrade-checkmk" in line:
            continue
        filtered.append(line)

    filtered.append(f"# Auto-upgrade CheckMK: {description}")
    filtered.append(cron_entry)

    print("Nuova entry cron:")
    print(cron_entry)
    confirm = input("Confermi? [s/N]: ").strip().lower()
    if confirm != "s":
        print("Annullato")
        return 0

    write_crontab("\n".join(filtered) + "\n")
    Path(LOG_FILE).touch()
    print("Configurazione completata")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
