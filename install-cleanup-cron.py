#!/usr/bin/env python3
"""install-cleanup-cron.py - Installs cron job for cleanup-checkmk-retention

Install a cron job that runs cleanup-checkmk-retention.sh from GitHub,
removing obsolete CheckMK data (RRD >180 days, nagios archives >180 days,
notify backups >30 days).

Usage:
  python3 install-cleanup-cron.py # Interactive mode
  python3 install-cleanup-cron.py --yes # Auto-confirm (default 03:00)
  python3 install-cleanup-cron.py --yes --time "0 2 * * *"
  python3 install-cleanup-cron.py --yes --email admin@example.com

Version: 1.0.0"""

import argparse
import os
import re
import subprocess
import sys
import urllib.request
from typing import Optional

VERSION = "1.0.0"

SCRIPT_URL = (
    "https://raw.githubusercontent.com/nethesis/checkmk-tools/main/"
    "script-tools/full/backup_restore/cleanup-checkmk-retention.py"
)
LOG_FILE = "/var/log/cleanup-checkmk-retention.log"
CRON_PATTERN = "cleanup-checkmk-retention"
DEFAULT_CRON_TIME = "0 3 * * *"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def info(msg: str) -> None:
    print(f"\n\033[1;34m[INFO]\033[0m {msg}")


def ok(msg: str) -> None:
    print(f"\033[1;32m[OK]\033[0m {msg}")


def warn(msg: str) -> None:
    print(f"\033[1;33m[WARN]\033[0m {msg}")


def die(msg: str) -> None:
    print(f"\033[1;31m[ERROR]\033[0m {msg}", file=sys.stderr)
    sys.exit(1)


def ask(prompt: str, default: str = "") -> str:
    """Pipe-compatible interactive input (use /dev/tty if necessary)."""
    if not sys.stdin.isatty():
        try:
            with open("/dev/tty", "r") as tty:
                sys.stdout.write(prompt)
                sys.stdout.flush()
                return tty.readline().rstrip("\n") or default
        except OSError:
            return default
    val = input(prompt)
    return val.strip() or default


def require_root() -> None:
    if os.geteuid() != 0:
        die("Questo script deve essere eseguito come root. Usa: sudo python3 install-cleanup-cron.py")


def check_curl_or_wget() -> None:
    import shutil
    if not shutil.which("curl") and not shutil.which("wget"):
        die("curl o wget non trovati. Installa con: apt install curl")


def test_script_url() -> None:
    info(f"Verifica accessibilità script da GitHub...")
    try:
        urllib.request.urlopen(SCRIPT_URL, timeout=10).close()
        ok("Script accessibile da GitHub")
    except Exception as exc:
        die(f"Impossibile accedere allo script: {exc}")


def get_crontab() -> str:
    result = subprocess.run(
        ["crontab", "-l"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout or ""


def set_crontab(content: str) -> None:
    proc = subprocess.run(
        ["crontab", "-"],
        input=content,
        text=True,
        check=True,
    )


def crontab_has_pattern(cron_text: str) -> bool:
    return CRON_PATTERN in cron_text


def remove_cron_pattern(cron_text: str) -> str:
    lines = [l for l in cron_text.splitlines() if CRON_PATTERN not in l]
    return "\n".join(lines) + "\n" if lines else ""


def cron_desc(cron_time: str) -> str:
    mapping = {
        "0 3 * * *": "03:00 AM daily",
        "0 2 * * *": "02:00 AM daily",
        "0 4 * * *": "04:00 AM daily",
    }
    return mapping.get(cron_time, f"custom: {cron_time}")


def validate_cron_syntax(cron_time: str) -> bool:
    parts = cron_time.strip().split()
    if len(parts) != 5:
        return False
    pattern = re.compile(r'^[0-9*/,\-]+$')
    return all(pattern.match(p) for p in parts)


def validate_email(email: str) -> bool:
    return bool(re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', email))


# ─── Logic ────────────────────────────────────────────────────────────────────

def handle_existing_cron(auto_yes: bool) -> None:
    cron_text = get_crontab()
    if not crontab_has_pattern(cron_text):
        return

    warn("Cron job già presente!")
    print()
    print("Configurazione attuale:")
    print("─" * 60)
    for line in cron_text.splitlines():
        if CRON_PATTERN in line:
            print(line)
    print("─" * 60)
    print()

    if not auto_yes:
        ans = ask("Vuoi SOSTITUIRLO? [y/N]: ", default="n").lower()
        if ans not in ("y", "s", "yes", "si"):
            info("Installazione annullata.")
            sys.exit(0)
    else:
        info("Auto-confirm abilitato - sostituzione cron esistente")

    info("Rimozione cron esistente...")
    new_cron = remove_cron_pattern(cron_text)
    set_crontab(new_cron)
    ok("Cron esistente rimosso")


def ask_schedule(auto_yes: bool, cron_time: str) -> str:
    if auto_yes:
        return cron_time

    print()
    info("Configura orario esecuzione")
    print()
    print(f"Default: 03:00 AM ogni giorno (0 3 * * *)")
    print()
    print("Orari comuni:")
    print("  1) 03:00 AM giornaliero (consigliato)")
    print("  2) 02:00 AM giornaliero")
    print("  3) 04:00 AM giornaliero")
    print("  4) Orario personalizzato")
    print()

    choice = ask("Seleziona orario [1-4, default: 1]: ", default="1")

    schedules = {
        "1": "0 3 * * *",
        "2": "0 2 * * *",
        "3": "0 4 * * *",
    }

    if choice in schedules:
        return schedules[choice]
    elif choice == "4":
        print()
        print("Formato cron: MIN HOUR DAY MONTH WEEKDAY")
        print("Esempi:")
        print("  0 3 * * *    → 03:00 ogni giorno")
        print("  30 2 * * *   → 02:30 ogni giorno")
        print("  0 3 * * 0    → 03:00 ogni domenica")
        print()
        while True:
            custom = ask("Orario personalizzato: ").strip()
            if validate_cron_syntax(custom):
                return custom
            warn("Sintassi cron non valida. Formato: MIN HOUR DAY MONTH WEEKDAY")
    else:
        return "0 3 * * *"


def ask_email(auto_yes: bool, email: str) -> str:
    if auto_yes or email:
        return email

    print()
    info("Configurazione email report (opzionale)")
    print()
    print("Vuoi ricevere report via email dopo ogni cleanup?")
    print()

    addr = ask("Indirizzo email (invio = salta): ", default="").strip()
    if not addr:
        return ""

    if not validate_email(addr):
        warn(f"Email non valida: {addr}")
        ans = ask("Continuare comunque? [y/N]: ", default="n").lower()
        if ans not in ("y", "s"):
            return ""

    ok(f"Email configurata: {addr}")
    return addr


def build_cron_cmd(cron_time: str, email: str) -> str:
    import shutil
    downloader = "curl -fsSL" if shutil.which("curl") else "wget -qO-"
    py3 = shutil.which("python3") or "python3"
    if email:
        cmd = f"{cron_time} {downloader} {SCRIPT_URL} | {py3} - --email {email} >> {LOG_FILE} 2>&1"
    else:
        cmd = f"{cron_time} {downloader} {SCRIPT_URL} | {py3} - >> {LOG_FILE} 2>&1"
    return cmd


def show_summary(cron_time: str, email: str, cron_cmd: str) -> None:
    print()
    info("Riepilogo installazione:")
    print("─" * 60)
    print(f"Orario:       {cron_desc(cron_time)}")
    print(f"Email report: {email if email else 'disabilitata'}")
    print(f"Log file:     {LOG_FILE}")
    print(f"Cron entry:   {cron_cmd}")
    print("─" * 60)
    print()


def install_cron(cron_cmd: str) -> None:
    info("Installazione cron job...")
    existing = get_crontab()
    new_crontab = existing.rstrip("\n") + "\n" + cron_cmd + "\n"
    set_crontab(new_crontab)
    ok("Cron job installato!")


def verify_installation() -> None:
    print()
    info("Verifica installazione...")
    cron_text = get_crontab()
    if crontab_has_pattern(cron_text):
        ok("Cron job verificato nel crontab")
        print()
        print("Configurazione attuale:")
        print("─" * 60)
        for line in cron_text.splitlines():
            if CRON_PATTERN in line:
                print(line)
        print("─" * 60)
    else:
        die("Installazione cron job fallita!")


def run_dry_run(auto_yes: bool) -> None:
    if auto_yes:
        return
    print()
    ans = ask("Eseguire lo script di cleanup ora (dry-run)? [y/N]: ", default="n").lower()
    if ans not in ("y", "s"):
        return

    info("Esecuzione cleanup in modalità dry-run...")
    print("─" * 60)
    import shutil
    py3 = shutil.which("python3") or "python3"
    subprocess.run(
        f"curl -fsSL {SCRIPT_URL} | {py3} - --dry-run",
        shell=True,
        check=False,
    )
    print("─" * 60)
    print()

    ans2 = ask("Eseguire cleanup REALE ora (non dry-run)? [y/N]: ", default="n").lower()
    if ans2 in ("y", "s"):
        info("Esecuzione cleanup reale...")
        import shutil
        py3 = shutil.which("python3") or "python3"
        subprocess.run(
            f"curl -fsSL {SCRIPT_URL} | {py3} -",
            shell=True,
            check=False,
        )


# ─── Main ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=f"install-cleanup-cron.py v{VERSION} - Installa cron job cleanup-checkmk-retention",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Esempi:
  python3 install-cleanup-cron.py                          # Interattivo
  python3 install-cleanup-cron.py --yes                    # Auto-confirm (03:00)
  python3 install-cleanup-cron.py --yes --time "0 2 * * *"
  python3 install-cleanup-cron.py --yes --email admin@example.com""",
    )
    p.add_argument("--yes", "-y", action="store_true", help="Auto-confirm (non-interattivo)")
    p.add_argument("--time", "-t", default=DEFAULT_CRON_TIME,
                   help=f'Orario cron (default: "{DEFAULT_CRON_TIME}")')
    p.add_argument("--email", "-e", default="", help="Email per report cleanup")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    require_root()

    # Banner
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║                                                              ║")
    print("║      CLEANUP CHECKMK RETENTION - CRON INSTALLER             ║")
    print(f"║                                       v{VERSION}                ║")
    print("║                                                              ║")
    print("║  Automated cleanup per CheckMK data retention:              ║")
    print("║  • RRD files: 180 giorni                                    ║")
    print("║  • Nagios archives: 180 giorni (compressi dopo 30)          ║")
    print("║  • Notify backups: 30 giorni (compressi dopo 1 giorno)      ║")
    print("║                                                              ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    info(f"Script URL: {SCRIPT_URL}")
    info(f"Log file: {LOG_FILE}")

    check_curl_or_wget()
    test_script_url()

    # Cron esistente?
    handle_existing_cron(args.yes)

    # Schedule
    cron_time = ask_schedule(args.yes, args.time)

    # Email
    email = ask_email(args.yes, args.email)

    # Build cron command
    cron_cmd = build_cron_cmd(cron_time, email)

    # Summary + confirm
    show_summary(cron_time, email, cron_cmd)

    if not args.yes:
        ans = ask("Procedere con l'installazione? [y/N]: ", default="n").lower()
        if ans not in ("y", "s"):
            info("Installazione annullata.")
            return 0
    else:
        info("Auto-confirm abilitato - procedo con installazione")

    install_cron(cron_cmd)
    verify_installation()
    run_dry_run(args.yes)

    print()
    ok(f"Installazione completata! Il cleanup verrà eseguito: {cron_desc(cron_time)}")
    print(f"     Log: tail -f {LOG_FILE}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
