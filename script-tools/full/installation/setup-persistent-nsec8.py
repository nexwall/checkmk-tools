#!/usr/bin/env python3
"""setup-persistent-nsec8.py — CheckMK Persistent Setup (NO agent install)

Configure everything needed for CheckMK persistence on
NethSecurity 8 / OpenWrt, WITHOUT installing or touching the agent.

Use when the CheckMK agent is already installed and you just want to:
  - Install prerequisites (wget, socat, ar, tar, gzip)
  - Download sync-checks.py and populate /opt/checkmk-checks/
  - Deploy local checks from /opt/checkmk-checks/
  - Configure cron sync every 5 minutes
  - Protect installation in sysupgrade.conf
  - Create automatic post-upgrade recovery scripts
  - Install autocheck on startup (persistent-startup-check.py)

Usage:
  python3 setup-persistent-nsec8.py [--uninstall] [--help]

Environment Variables:
  OPENWRT_REPO_BASE OpenWrt base repository for dynamic download
  OPENWRT_REPO_PACKAGES OpenWrt packages repository for dynamic download

Version: 1.0.0"""

import gzip as _gzip
import io
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------
CHECKS_DIR = "/opt/checkmk-checks"               # Script check (NO git clone)
LOCAL_DIR = "/usr/lib/check_mk_agent/local"
PLUGINS_DIR = "/usr/lib/check_mk_agent/plugins"
SYSUPGRADE_CONF = "/etc/sysupgrade.conf"
CRON_FILE = "/etc/crontabs/root"
SYNC_SCRIPT = "/opt/checkmk-backups/sync-checks.py"
POST_UPGRADE_SCRIPT = "/etc/checkmk-post-upgrade.py"
RC_LOCAL = "/etc/rc.local"
AUTOCHECK_SCRIPT = "/opt/checkmk-backups/persistent-startup-check.py"
AUTOCHECK_URL = (
    "https://raw.githubusercontent.com/nethesis/checkmk-tools/main"
    "/script-tools/full/upgrade_maintenance/persistent-startup-check.py"
)
SYNC_SCRIPT_URL = (
    "https://raw.githubusercontent.com/nethesis/checkmk-tools/main"
    "/script-tools/full/upgrade_maintenance/sync-checks.py"
)

# OpenWrt repository for dynamic package download
REPO_BASE = os.environ.get(
    "OPENWRT_REPO_BASE",
    "https://downloads.openwrt.org/releases/23.05.0/packages/x86_64/base",
)
REPO_PACKAGES = os.environ.get(
    "OPENWRT_REPO_PACKAGES",
    "https://downloads.openwrt.org/releases/23.05.0/packages/x86_64/packages",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    print(f"[INFO] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[WARN] {msg}", flush=True)


def die(msg: str) -> None:
    print(f"[ERR]  {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def run(cmd: List[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Execute a command, print output in real time if not capture."""
    if capture:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    result = subprocess.run(cmd)
    if check and result.returncode != 0:
        die(f"Comando fallito (exit {result.returncode}): {' '.join(cmd)}")
    return result


def cmd_exists(name: str) -> bool:
    return shutil.which(name) is not None


def is_root() -> bool:
    return os.geteuid() == 0


# ---------------------------------------------------------------------------
# Dynamic download of OpenWrt packages
# ---------------------------------------------------------------------------


def download_openwrt_package(
    package_name: str, repo_url: str, output_file: str
) -> bool:
    """Download an OpenWrt package dynamically from the Packages.gz index.
    Avoid fragile static URLs: find the filename from the updated list."""
    log(f"Download dinamico pacchetto: {package_name}")
    packages_url = f"{repo_url}/Packages.gz"

    try:
        with urllib.request.urlopen(packages_url, timeout=30) as resp:
            raw = resp.read()
    except Exception as exc:
        warn(f"Download Packages.gz fallito [{repo_url}]: {exc}")
        return False

    try:
        with _gzip.open(io.BytesIO(raw)) as fh:
            text = fh.read().decode("utf-8", errors="replace")
    except Exception as exc:
        warn(f"Decompressione Packages.gz fallita: {exc}")
        return False

    package_file: Optional[str] = None
    for line in text.splitlines():
        if line.startswith("Filename:"):
            fname = line.split(":", 1)[1].strip()
            basename = fname.split("/")[-1]
            if basename.startswith(f"{package_name}_"):
                package_file = fname
                break

    if not package_file:
        warn(f"Pacchetto '{package_name}' non trovato nell'index OpenWrt")
        return False

    log(f"Trovato nell'index: {package_file}")
    try:
        urllib.request.urlretrieve(f"{repo_url}/{package_file}", output_file)
        log(f"Download completato: {package_file}")
        return True
    except Exception as exc:
        warn(f"Download fallito [{package_file}]: {exc}")
        return False


# ---------------------------------------------------------------------------
# 1. System detection
# ---------------------------------------------------------------------------


def detect_system() -> Tuple[str, str]:
    """Detect OS version and architecture. Returns (version, arch)."""
    version = "unknown"
    arch = "x86_64"

    for path in ("/etc/os-release", "/etc/openwrt_release"):
        if os.path.exists(path):
            with open(path) as fh:
                for line in fh:
                    if line.startswith("VERSION=") or line.startswith(
                        "DISTRIB_RELEASE"
                    ):
                        version = (
                            line.split("=", 1)[1].strip().strip("'\"").split()[0]
                        )
                        break
            if version != "unknown":
                break

    r = run(["opkg", "print-architecture"], capture=True, check=False)
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] not in ("all", "noarch"):
            arch = parts[1]

    log(f"Sistema rilevato: {version} / {arch}")
    return version, arch


# ---------------------------------------------------------------------------
# 2. Prerequisiti
# ---------------------------------------------------------------------------


def install_prereqs() -> None:
    """Install necessary tools: wget, socat, ca-certificates, ar, tar, gzip."""
    if not cmd_exists("opkg"):
        die("opkg non trovato — questo script richiede OpenWrt / NethSecurity")

    log("opkg update")
    run(["opkg", "update"], check=False)

    log("Installazione pacchetti base (wget, socat, ca-certificates)...")
    run(["opkg", "install", "wget", "socat", "ca-certificates"], check=False)

    if not cmd_exists("wget"):
        die("wget non disponibile dopo installazione — impossibile continuare")
    if not cmd_exists("socat"):
        die("socat non disponibile dopo installazione — impossibile continuare")

    # ar — richiesto dalla dependency chain binutils
    if not cmd_exists("ar"):
        log(
            "Installazione catena dipendenze binutils "
            "(libbfd -> ar -> objdump -> binutils)..."
        )
        for pkg in ("libbfd", "ar", "objdump", "binutils"):
            tmp = f"/tmp/{pkg}.ipk"
            if download_openwrt_package(pkg, REPO_BASE, tmp):
                run(["opkg", "install", "--force-depends", tmp], check=False)
                Path(tmp).unlink(missing_ok=True)
        if not cmd_exists("ar"):
            die("ar non disponibile dopo installazione — impossibile continuare")

    # tar
    if not cmd_exists("tar"):
        tmp = "/tmp/tar.ipk"
        if download_openwrt_package("tar", REPO_BASE, tmp):
            run(["opkg", "install", "--force-depends", tmp], check=False)
            Path(tmp).unlink(missing_ok=True)
        if not cmd_exists("tar"):
            die("tar non disponibile dopo installazione — impossibile continuare")

    # gzip
    if not cmd_exists("gzip"):
        tmp = "/tmp/gzip.ipk"
        if download_openwrt_package("gzip", REPO_BASE, tmp):
            run(["opkg", "install", "--force-depends", tmp], check=False)
            Path(tmp).unlink(missing_ok=True)
        if not cmd_exists("gzip"):
            die("gzip non disponibile dopo installazione — impossibile continuare")

    log("Prerequisiti verificati: wget, socat, ar, tar, gzip OK")


# ---------------------------------------------------------------------------
# 3. Check scripts sync (NO git — footprint minimo)
# ---------------------------------------------------------------------------


def setup_checks_sync() -> None:
    """Download sync-checks.py from GitHub, save it in /opt/checkmk-backups/,
    then performs initial sync to populate /opt/checkmk-checks/."""
    backup_base = Path("/opt/checkmk-backups")
    backup_base.mkdir(parents=True, exist_ok=True)

    # 1. Download sync-checks.py from GitHub
    log("Download sync-checks.py da GitHub...")
    try:
        urllib.request.urlretrieve(SYNC_SCRIPT_URL, SYNC_SCRIPT)
        content = Path(SYNC_SCRIPT).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        Path(SYNC_SCRIPT).write_bytes(content)
        Path(SYNC_SCRIPT).chmod(Path(SYNC_SCRIPT).stat().st_mode | 0o111)
        log(f"sync-checks.py installato: {SYNC_SCRIPT}")
    except Exception as exc:
        warn(f"Download sync-checks.py fallito: {exc} — skip auto-sync")
        return

    # 2. Run initial sync to populate /opt/checkmk-checks/
    log("Sync iniziale script check da GitHub...")
    r = run(["python3", SYNC_SCRIPT], check=False)
    if r.returncode == 0:
        n = sum(1 for f in Path(CHECKS_DIR).glob("*.py")) if Path(CHECKS_DIR).exists() else 0
        log(f"Script check sincronizzati: {n} file in {CHECKS_DIR}")
    else:
        warn("Sync iniziale fallito — continuo senza check sincronizzati")


# ---------------------------------------------------------------------------
# 4. Local checks
# ---------------------------------------------------------------------------


def deploy_local_checks() -> None:
    """Copy local checks from /opt/checkmk-checks/ to LOCAL_DIR."""
    src = Path(CHECKS_DIR)
    dst = Path(LOCAL_DIR)
    dst.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        warn(f"Directory check non trovata: {src} — skip deploy checks")
        return

    deployed = 0
    for f in src.iterdir():
        if f.is_file() and (f.suffix in (".py", ".sh") or f.stat().st_mode & 0o111):
            dest_name = f.stem if f.suffix == ".py" else f.name
            dest_path = dst / dest_name
            shutil.copy2(f, dest_path)
            dest_path.chmod(dest_path.stat().st_mode | 0o111)
            deployed += 1

    log(f"Deploy local checks: {deployed} file in {LOCAL_DIR}")

    # Remove the old .sh files from the plugins folder
    plugins_dir = Path(PLUGINS_DIR)
    removed = 0
    if plugins_dir.is_dir():
        for f in plugins_dir.glob("*.sh"):
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    if removed:
        log(f"Rimossi {removed} vecchi .sh da {PLUGINS_DIR} (sostituiti da Python in local/)")


# ---------------------------------------------------------------------------
# 5. Cron sync-checks
# ---------------------------------------------------------------------------


def setup_cron() -> None:
    """Adds cron job every 5 minutes for sync-checks.py."""
    if not Path(SYNC_SCRIPT).exists():
        log("sync-checks.py non presente — skip configurazione cron")
        return

    cron_path = Path(CRON_FILE)
    cron_path.parent.mkdir(parents=True, exist_ok=True)
    existing = cron_path.read_text() if cron_path.exists() else ""
    lines = [
        l for l in existing.splitlines()
        if "git-auto-sync" not in l and "sync-checks" not in l
    ]
    lines.append(f"*/5 * * * * python3 {SYNC_SCRIPT} >> /var/log/auto-git-sync.log 2>&1")
    cron_path.write_text("\n".join(lines) + "\n")
    log("Cron job aggiunto (ogni 5 minuti)")

    run(["/etc/init.d/cron", "restart"], check=False)


# ---------------------------------------------------------------------------
# 6. Protezione sysupgrade (PERSISTENT)
# ---------------------------------------------------------------------------


def _add_to_sysupgrade(path: str, comment: str) -> None:
    """Adds a path to sysupgrade.conf if not already present."""
    conf = Path(SYSUPGRADE_CONF)
    if not conf.exists():
        conf.write_text("## File e directory preservati durante upgrade\n\n")
    existing = conf.read_text()
    if path not in existing:
        conf.write_text(existing + f"\n# {comment}\n{path}\n")


def setup_sysupgrade() -> None:
    """Adds all critical paths to sysupgrade.conf."""
    entries = [
        ("/usr/bin/check_mk_agent",         "CheckMK Agent - Binary"),
        ("/etc/init.d/check_mk_agent",       "CheckMK Agent - Init Script"),
        ("/etc/check_mk/",                   "CheckMK Agent - Configuration"),
        (f"{LOCAL_DIR}/",                    "CheckMK Agent Local Checks"),
        ("/usr/lib/check_mk_agent/plugins/", "CheckMK Agent Plugins"),
        (f"{CHECKS_DIR}/",                   "Script check (sync da GitHub, NO git)"),
        ("/opt/checkmk-backups/",            "Backup binari critici + sync-checks.py"),
        (CRON_FILE,                          "Cron Jobs (include sync-checks)"),
        ("/etc/cron.d/",                     "Cron Jobs Directory"),
        ("/var/spool/cron/crontabs/",        "User Crontabs"),
        ("/etc/opkg/customfeeds.conf",       "Custom package repositories"),
        (POST_UPGRADE_SCRIPT,                "Post-upgrade verification script"),
        (RC_LOCAL,                           "Boot Script (rc.local)"),
    ]

    conf = Path(SYSUPGRADE_CONF)
    if not conf.exists():
        conf.write_text("## File e directory preservati durante upgrade\n\n")

    existing = conf.read_text()
    added = 0
    for path, comment in entries:
        if path not in existing:
            existing += f"\n# {comment}\n{path}\n"
            added += 1

    conf.write_text(existing)
    log(f"sysupgrade.conf: {added} nuove entry aggiunte")


# ---------------------------------------------------------------------------
# 7. Script post-upgrade (PERSISTENT)
# ---------------------------------------------------------------------------


def create_post_upgrade_script() -> None:
    """Create /etc/checkmk-post-upgrade.py — run manually after major upgrade."""
    log(f"Creo script di ripristino post-upgrade: {POST_UPGRADE_SCRIPT}")

    script_lines = [
        '#!/usr/bin/env python3',
        '"""checkmk-post-upgrade.py - automatic recovery after major upgrade.',
        'Generated by setup-persistent-nsec8.py',
        '"""',
        'import os, subprocess, sys, time',
        '',
        '',
        'def log(msg):',
        '    print(f"[POST-UPGRADE] {msg}", flush=True)',
        '    subprocess.run(["logger", "-t", "checkmk-post-upgrade", msg], check=False)',
        '',
        '',
        'def main():',
        '    log("=== POST-UPGRADE: Inizio ripristino ===")',
        '',
        '    for check in ("/usr/bin/check_mk_agent", "/etc/init.d/check_mk_agent"):',
        '        if not os.access(check, os.X_OK):',
        '            log(f"ERRORE: {check} mancante!")',
        '            sys.exit(1)',
        '',
        '    subprocess.run(["/etc/init.d/check_mk_agent", "enable"], check=False)',
        '    subprocess.run(["/etc/init.d/check_mk_agent", "restart"], check=False)',
        '',
        '    if not os.path.islink("/etc/nginx/uci.conf") and os.path.isfile("/var/lib/nginx/uci.conf"):',
        '        log("Ripristino symlink nginx uci.conf...")',
        '        try:',
        '            os.symlink("/var/lib/nginx/uci.conf", "/etc/nginx/uci.conf")',
        '        except FileExistsError:',
        '            os.remove("/etc/nginx/uci.conf")',
        '            os.symlink("/var/lib/nginx/uci.conf", "/etc/nginx/uci.conf")',
        '        subprocess.run(["/etc/init.d/nginx", "restart"], check=False)',
        '',
        '    time.sleep(2)',
        '    r = subprocess.run(["pgrep", "-f", "socat TCP-LISTEN:6556"], capture_output=True, check=False)',
        '    if r.returncode == 0:',
        '        log("CheckMK Agent attivo su porta 6556")',
        '    else:',
        '        log("WARN: socat non in esecuzione - riavvio")',
        '        subprocess.run(["/etc/init.d/check_mk_agent", "restart"], check=False)',
        '',
        '    log("=== POST-UPGRADE: Ripristino completato ===")',
        '    return 0',
        '',
        '',
        'if __name__ == "__main__":',
        '    sys.exit(main())',
    ]

    post_path = Path(POST_UPGRADE_SCRIPT)
    post_path.write_text("\n".join(script_lines) + "\n")
    post_path.chmod(post_path.stat().st_mode | 0o111)
    _add_to_sysupgrade(POST_UPGRADE_SCRIPT, "Post-upgrade verification script")
    log(f"Script post-upgrade creato: {POST_UPGRADE_SCRIPT}")


# ---------------------------------------------------------------------------
# 8. Autocheck at startup (PERSISTENT)
# ---------------------------------------------------------------------------


def install_autocheck() -> None:
    """Download persistent-startup-check.py and configure it in rc.local."""
    log("Installazione script autocheck all'avvio")

    Path(AUTOCHECK_SCRIPT).parent.mkdir(parents=True, exist_ok=True)

    downloaded = False
    log("Download persistent-startup-check.py da GitHub...")
    try:
        urllib.request.urlretrieve(AUTOCHECK_URL, AUTOCHECK_SCRIPT)
        content = Path(AUTOCHECK_SCRIPT).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        Path(AUTOCHECK_SCRIPT).write_bytes(content)
        Path(AUTOCHECK_SCRIPT).chmod(
            Path(AUTOCHECK_SCRIPT).stat().st_mode | 0o111
        )
        log(f"Script autocheck installato: {AUTOCHECK_SCRIPT}")
        downloaded = True
    except Exception as exc:
        warn(f"Download da GitHub fallito ({exc}) — provo da repository locale")

    if not downloaded:
        warn("ATTENZIONE: download persistent-startup-check.py fallito — skip autocheck")

    # Configure rc.local
    rc_path = Path(RC_LOCAL)
    if not rc_path.exists():
        rc_path.write_text(
            "#!/bin/sh\n"
            "# Put your custom commands here that should be executed once\n"
            "# the system init finished. By default this file does nothing.\n\n"
            "exit 0\n"
        )
        rc_path.chmod(rc_path.stat().st_mode | 0o111)

    content = rc_path.read_text()
    lines = [
        l for l in content.splitlines()
        if "persistent-startup-check" not in l
        and "PERSISTENT Autocheck" not in l
        and l != "exit 0"
    ]
    lines.append(
        "# PERSISTENT Autocheck — avvio da /opt/checkmk-backups/ (upgrade-resistant)"
    )
    lines.append(
        f"[ -x {AUTOCHECK_SCRIPT} ] && python3 {AUTOCHECK_SCRIPT} "
        ">> /var/log/persistent-startup.log 2>&1 &"
    )
    lines.append("exit 0")
    rc_path.write_text("\n".join(lines) + "\n")
    log(f"Autocheck configurato in {RC_LOCAL}")

    _add_to_sysupgrade(RC_LOCAL, "Boot Script (rc.local)")

    # Test immediato
    log("Test esecuzione autocheck...")
    r = run([AUTOCHECK_SCRIPT], check=False)
    if r.returncode == 0:
        log("Test autocheck completato — log in /var/log/persistent-startup.log")
    else:
        warn(f"Test autocheck exit code {r.returncode}")


# ---------------------------------------------------------------------------
# 9. Disinstallazione
# ---------------------------------------------------------------------------


def uninstall() -> None:
    """Removes cron, sync script and post-upgrade. DO NOT touch the agent."""
    log("Rimozione configurazione persistent setup...")

    # Rimuovi cron entry
    if os.path.exists(CRON_FILE):
        lines = [
            l for l in Path(CRON_FILE).read_text().splitlines()
            if "git-auto-sync" not in l and "sync-checks" not in l
        ]
        Path(CRON_FILE).write_text("\n".join(lines) + "\n")
        run(["/etc/init.d/cron", "restart"], check=False)

    # Rimuovi script generati
    for p in (SYNC_SCRIPT, POST_UPGRADE_SCRIPT):
        if os.path.exists(p):
            os.remove(p)
            log(f"Rimosso: {p}")

    # Remove autocheck entry from rc.local
    if os.path.exists(RC_LOCAL):
        lines = [
            l for l in Path(RC_LOCAL).read_text().splitlines()
            if "persistent-startup-check" not in l
            and "PERSISTENT Autocheck" not in l
        ]
        Path(RC_LOCAL).write_text("\n".join(lines) + "\n")

    log("Rimozione completata — l'agente CheckMK NON è stato toccato")
    warn(
        f"Le entry in {SYSUPGRADE_CONF} non sono state modificate — "
        "rimuovile manualmente se desiderato"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def usage() -> None:
    print(
        f"setup-persistent-nsec8.py v{VERSION}\n\n"
        "CheckMK Persistent Setup — SENZA installazione agente\n"
        "Configura sync, cron, sysupgrade e autocheck su NethSecurity/OpenWrt\n\n"
        "Uso:\n"
        "  python3 setup-persistent-nsec8.py\n"
        "  python3 setup-persistent-nsec8.py --uninstall\n\n"
        "Variabili d'ambiente:\n"
        f"  OPENWRT_REPO_BASE      (default: downloads.openwrt.org/23.05.0 base)\n"
        f"  OPENWRT_REPO_PACKAGES  (default: downloads.openwrt.org/23.05.0 packages)\n"
    )


def main() -> int:
    args = sys.argv[1:]

    if "-h" in args or "--help" in args:
        usage()
        return 0

    if not is_root():
        die("Questo script deve essere eseguito come root")

    if "--uninstall" in args:
        uninstall()
        return 0

    print()
    print("=" * 62)
    print("  CheckMK Persistent Setup (NO agent install)")
    print(f"  v{VERSION}")
    print("  Persistente ai major upgrade NethSecurity / OpenWrt")
    print("=" * 62)
    print()

    log(f"=== setup-persistent-nsec8.py v{VERSION} ===")

    log("--- [1/6] Rilevamento sistema ---")
    detect_system()

    log("--- [2/6] Installazione prerequisiti ---")
    install_prereqs()

    log("--- [3/6] Download script check e sync ---")
    setup_checks_sync()

    log("--- [4/6] Deploy local checks ---")
    deploy_local_checks()

    log("--- [5/6] Cron sync + sysupgrade ---")
    setup_cron()
    setup_sysupgrade()

    log("--- [6/6] Script post-upgrade + autocheck ---")
    create_post_upgrade_script()
    install_autocheck()

    print()
    print("=" * 62)
    print("  SETUP COMPLETATO — PERSISTENT MODE ATTIVO")
    print("=" * 62)
    print()
    print("Protezioni attivate:")
    print(f"  [+] File critici aggiunti a {SYSUPGRADE_CONF}")
    print(f"  [+] Script post-upgrade: {POST_UPGRADE_SCRIPT}")
    print(f"  [+] Autocheck all'avvio: {AUTOCHECK_SCRIPT}")
    print()
    print("Check Scripts Sync (NO git):")
    print(f"  [+] Script check in: {CHECKS_DIR}")
    print(f"  [+] Sync ogni 5 minuti via: {SYNC_SCRIPT}")
    print("  [+] Log: /var/log/auto-git-sync.log")
    print()
    print(f"Post-upgrade manuale: python3 {POST_UPGRADE_SCRIPT}")
    print(f"Disinstallazione: python3 {sys.argv[0]} --uninstall")
    return 0


if __name__ == "__main__":
    sys.exit(main())
