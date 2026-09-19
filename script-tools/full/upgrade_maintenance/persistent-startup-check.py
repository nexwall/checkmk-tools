#!/usr/bin/env python3
"""persistent-startup-check.py - PERSISTENT Startup Verification

Automatically checks and restores critical CheckMK services
after a major upgrade of NethSecurity 8 / OpenWrt.

Executed by rc.local at every system startup.

Version: 2.0.0"""

import gzip as _gzip
import io
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

VERSION = "2.2.0"

LOG_FILE = "/var/log/persistent-startup.log"
POST_UPGRADE_SCRIPT = "/etc/checkmk-post-upgrade.py"
SYSUPGRADE_CONF = "/etc/sysupgrade.conf"
CHECKS_SRC = "/opt/checkmk-checks"           # Script check (NO git clone)
SYNC_SCRIPT = "/opt/checkmk-backups/sync-checks.py"
SYNC_SCRIPT_URL = (
    "https://raw.githubusercontent.com/nethesis/checkmk-tools/main"
    "/script-tools/full/upgrade_maintenance/sync-checks.py"
)
LOCAL_DIR = "/usr/lib/check_mk_agent/local"
PLUGINS_DIR = "/usr/lib/check_mk_agent/plugins"
AGENT_PKG_URL_FILE = "/opt/checkmk-backups/agent-pkg-url.conf"

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
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _run(cmd: list, check: bool = False, timeout: int = 30) -> int:
    """Run a command, return exit code."""
    try:
        return subprocess.run(cmd, timeout=timeout).returncode
    except Exception:
        return 1


def _run_capture(cmd: list, timeout: int = 30) -> Tuple[int, str]:
    """Run command, return (rc, combined stdout+stderr)."""
    try:
        r = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return r.returncode, r.stdout + r.stderr
    except Exception as exc:
        return 1, str(exc)


def cmd_exists(name: str) -> bool:
    return shutil.which(name) is not None


def is_elf(path: str) -> bool:
    """Return True if the file starts with the ELF magic bytes."""
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == b"\x7fELF"
    except OSError:
        return False


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Dynamic download of OpenWrt packages
# ---------------------------------------------------------------------------

def download_openwrt_package(package_name: str, repo_url: str, output_file: str) -> bool:
    """Download an OpenWrt package dynamically from the Packages.gz index.
    Avoid fragile static URLs: find the filename from the updated list."""
    log(f"Download dinamico pacchetto: {package_name}")
    packages_url = f"{repo_url}/Packages.gz"

    try:
        with urllib.request.urlopen(packages_url, timeout=30) as resp:
            raw = resp.read()
    except Exception as exc:
        log(f"[WARN] Download Packages.gz fallito [{repo_url}]: {exc}")
        return False

    try:
        with _gzip.open(io.BytesIO(raw)) as fh:
            text = fh.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log(f"[WARN] Decompressione Packages.gz fallita: {exc}")
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
        log(f"[WARN] Pacchetto '{package_name}' non trovato nell'index OpenWrt")
        return False

    log(f"Trovato nell'index: {package_file}")
    try:
        urllib.request.urlretrieve(f"{repo_url}/{package_file}", output_file)
        log(f"Download completato: {package_file}")
        return True
    except Exception as exc:
        log(f"[WARN] Download fallito [{package_file}]: {exc}")
        return False


# ---------------------------------------------------------------------------
# Section 0.5: Node.js + Nginx (Web UI NethSecurity)
# ---------------------------------------------------------------------------

def verify_webui() -> None:
    log("[Node.js] Verifica in corso...")
    if not cmd_exists("node"):
        log("[Node.js] MANCANTE - Reinstallazione automatica...")
        if cmd_exists("wget"):
            rc, out = _run_capture(["opkg", "list-installed"])
            if "libcares" not in out:
                log("[Node.js] Installazione dipendenza libcares...")
                _run(["opkg", "update"], timeout=60)
                _run(["opkg", "install", "libcares"], timeout=60)

            if download_openwrt_package("node", REPO_PACKAGES, "/tmp/node.ipk"):
                log("[Node.js] Installazione pacchetto...")
                _run(["opkg", "install", "/tmp/node.ipk"], timeout=60)
                _unlink("/tmp/node.ipk")
                if cmd_exists("node"):
                    rc, v = _run_capture(["node", "--version"])
                    log(f"[Node.js] RIPRISTINATO: {v.strip()}")
                else:
                    log("[Node.js] ERRORE: Installazione fallita")
            else:
                log("[Node.js] ERRORE: Download dinamico fallito")
        else:
            log("[Node.js] ERRORE: wget non disponibile")
    else:
        rc, v = _run_capture(["node", "--version"])
        log(f"[Node.js] OK - Presente: {v.strip()}")

    log("[Web UI] Verifica servizi...")
    if cmd_exists("nginx"):
        # Restore symlink uci.conf if missing (deleted during upgrade)
        uci_conf = Path("/etc/nginx/uci.conf")
        uci_target = Path("/var/lib/nginx/uci.conf")
        if not uci_conf.is_symlink() and uci_target.is_file():
            log("[Nginx] Ripristino symlink uci.conf...")
            try:
                uci_conf.symlink_to(str(uci_target))
            except OSError as exc:
                log(f"[Nginx] ERRORE symlink: {exc}")

        # Remove luci.module if it causes conflict with ngx_http_ubus.module (upgrade from previous version)
        luci_mod = Path("/etc/nginx/module.d/luci.module")
        ubus_mod = Path("/etc/nginx/module.d/ngx_http_ubus.module")
        if luci_mod.is_file() and ubus_mod.is_file():
            try:
                luci_mod.unlink()
                log("[Nginx] Rimosso luci.module duplicato (conflitto con ngx_http_ubus.module)")
            except OSError as exc:
                log(f"[Nginx] ERRORE rimozione luci.module: {exc}")

        rc, _ = _run_capture(["pgrep", "-f", "nginx.*master"])
        if rc != 0:
            log("[Nginx] Servizio non attivo, avvio...")
            _run(["/etc/init.d/nginx", "enable"])
            _run(["/etc/init.d/nginx", "restart"])
            time.sleep(2)
            rc, _ = _run_capture(["pgrep", "-f", "nginx.*master"])
            if rc == 0:
                log("[Nginx] Servizio riavviato")
            else:
                log("[Nginx] ERRORE: Impossibile avviare nginx")
        else:
            log("[Nginx] OK - Servizio attivo")

        # Check port 9090 (Web UI NethSecurity)
        rc, out = _run_capture(["netstat", "-tlnp"], timeout=10)
        if ":9090" not in out:
            log("[Web UI] Porta 9090 non attiva, riconfigurazione...")
            ns_ui = Path("/usr/sbin/ns-ui")
            if ns_ui.is_file() and os.access(str(ns_ui), os.X_OK):
                _run([str(ns_ui)])
                _run(["/etc/init.d/nginx", "restart"])
                time.sleep(2)
                rc, out = _run_capture(["netstat", "-tlnp"], timeout=10)
                if ":9090" in out:
                    log("[Web UI] Porta 9090 attiva dopo riconfigurazione")
                else:
                    log("[Web UI] ERRORE: Porta 9090 non disponibile")
            else:
                log("[Web UI] ERRORE: /usr/sbin/ns-ui non disponibile")
        else:
            log("[Web UI] OK - Porta 9090 attiva")


# ---------------------------------------------------------------------------
# Section 1: CheckMK Agent
# ---------------------------------------------------------------------------

def verify_checkmk_agent() -> None:
    log("[CheckMK Agent] Verifica in corso...")
    agent_bin = Path("/usr/bin/check_mk_agent")
    if not (agent_bin.is_file() and os.access(str(agent_bin), os.X_OK)):
        log("[CheckMK Agent] ERRORE: Binary mancante!")
        log("[CheckMK Agent] Eseguo script post-upgrade...")
        post = Path(POST_UPGRADE_SCRIPT)
        if post.is_file() and os.access(str(post), os.X_OK):
            _run(["python3", str(post)], timeout=120)
        else:
            log("[CheckMK Agent] CRITICO: Script post-upgrade mancante!")
        # If still missing, reinstall the ns-checkmk-agent package via opkg
        if not (agent_bin.is_file() and os.access(str(agent_bin), os.X_OK)):
            log("[CheckMK Agent] Binary ancora mancante — reinstallo ns-checkmk-agent...")
            if cmd_exists("opkg"):
                # Update lists before attempting install
                _run(["opkg", "update"], timeout=60)
                rc_opkg, _ = _run_capture(["opkg", "install", "ns-checkmk-agent"], timeout=120)
                # Fallback: URL diretto salvato dall'installer
                if not (agent_bin.is_file() and os.access(str(agent_bin), os.X_OK)):
                    url_file = Path(AGENT_PKG_URL_FILE)
                    if url_file.is_file():
                        agent_url = url_file.read_text().strip()
                        if agent_url:
                            log(f"[CheckMK Agent] Provo URL diretto: {agent_url}")
                            _run(["opkg", "install", agent_url], timeout=120)
                if agent_bin.is_file():
                    log("[CheckMK Agent] ns-checkmk-agent reinstallato con successo")
                    _run(["/etc/init.d/check_mk_agent", "enable"])
                    _run(["/etc/init.d/check_mk_agent", "restart"])
                else:
                    log("[CheckMK Agent] CRITICO: reinstallazione ns-checkmk-agent fallita")
            else:
                log("[CheckMK Agent] CRITICO: opkg non disponibile")
    else:
        rc, _ = _run_capture(["pgrep", "-f", "socat TCP-LISTEN:6556"])
        if rc != 0:
            log("[CheckMK Agent] Servizio non attivo, avvio...")
            _run(["/etc/init.d/check_mk_agent", "enable"])
            _run(["/etc/init.d/check_mk_agent", "restart"])
            time.sleep(2)
            rc, _ = _run_capture(["pgrep", "-f", "socat TCP-LISTEN:6556"])
            if rc == 0:
                log("[CheckMK Agent] Servizio riavviato con successo")
            else:
                log("[CheckMK Agent] ERRORE: Impossibile avviare servizio")
        else:
            log("[CheckMK Agent] OK - Servizio attivo")


# ---------------------------------------------------------------------------
# Section 2.7: Sync script check (sostituisce git)
# ---------------------------------------------------------------------------

def verify_sync() -> None:
    """Check sync-checks.py and update script checks if necessary."""
    log("[Sync] Verifica sync-checks.py...")

    sync = Path(SYNC_SCRIPT)

    # If missing, try downloading from GitHub
    if not sync.exists():
        log("[Sync] sync-checks.py non trovato — tentativo download da GitHub...")
        try:
            urllib.request.urlretrieve(SYNC_SCRIPT_URL, SYNC_SCRIPT)
            content = sync.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            sync.write_bytes(content)
            sync.chmod(sync.stat().st_mode | 0o111)
            log("[Sync] sync-checks.py scaricato con successo")
        except Exception as exc:
            log(f"[Sync] ERRORE: download sync-checks.py fallito: {exc}")
            return

    # Run sync to update script check
    log("[Sync] Aggiornamento script check da GitHub...")
    rc, out = _run_capture(["python3", SYNC_SCRIPT], timeout=60)
    if rc == 0:
        if out.strip():
            log(f"[Sync] {out.strip()}")
        else:
            log("[Sync] Script check gia' aggiornati")
    else:
        log(f"[Sync] WARN: sync fallito (no network?) — continuo con check locali")


# ---------------------------------------------------------------------------
# Section 2.8: Auto-deploy local checks and plugins from repository
# ---------------------------------------------------------------------------

def auto_deploy_checks() -> None:
    checks_src = Path(CHECKS_SRC)
    if checks_src.is_dir():
        log("[Auto-Deploy] Verifica nuovi script locali...")
        local_dir = Path(LOCAL_DIR)
        local_dir.mkdir(parents=True, exist_ok=True)
        deployed = 0
        for script in sorted(checks_src.iterdir()):
            if not script.is_file() or script.name.startswith("."):
                continue
            if script.suffix not in (".py", ".sh") and not (script.stat().st_mode & 0o111):
                continue
            # Deploy .py without extension, .sh with extension
            dest_name = script.stem if script.suffix == ".py" else script.name
            dest = local_dir / dest_name
            if not dest.exists() or script.stat().st_mtime > dest.stat().st_mtime:
                log(f"[Auto-Deploy] Deploy: {dest_name}")
                try:
                    shutil.copy2(str(script), str(dest))
                    dest.chmod(dest.stat().st_mode | 0o111)
                    deployed += 1
                except OSError as exc:
                    log(f"[Auto-Deploy] ERRORE deploy {dest_name}: {exc}")
        log(
            f"[Auto-Deploy] Deployed {deployed} local check(s)"
            if deployed
            else "[Auto-Deploy] Local checks già aggiornati"
        )

        # Remove old .sh from plugins/ (installed from ns-checkmk-agent package, obsolete duplicates)
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
            log(f"[Auto-Deploy] Rimossi {removed} vecchi .sh da {PLUGINS_DIR}")


# ---------------------------------------------------------------------------
# Section 3: Check sysupgrade.conf protections
# ---------------------------------------------------------------------------

def verify_sysupgrade() -> None:
    log("[Protezioni] Verifica sysupgrade.conf...")
    sysupgrade = Path(SYSUPGRADE_CONF)
    if not sysupgrade.is_file():
        log("[Protezioni] WARN: sysupgrade.conf non trovato")
        return
    count = 0
    try:
        with open(str(sysupgrade), errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and line.startswith("/"):
                    count += 1
    except OSError as exc:
        log(f"[Protezioni] ERRORE lettura sysupgrade.conf: {exc}")
        return
    log(f"[Protezioni] File protetti: {count}")
    if count < 5:
        log("[Protezioni] WARN: Poche protezioni attive (attese almeno 5)")


# ---------------------------------------------------------------------------
# Section 4: Riepilogo finale
# ---------------------------------------------------------------------------

def print_summary() -> None:
    log("=========================================")
    log("RIEPILOGO STATO SERVIZI:")
    log("=========================================")

    rc, _ = _run_capture(["pgrep", "-f", "socat TCP-LISTEN:6556"])
    log(f"  CheckMK Agent:  {'[OK]' if rc == 0 else '[FAIL]'}")

    cron = Path("/etc/crontabs/root")
    if cron.is_file():
        try:
            content = cron.read_text(errors="replace")
            has_sync = "sync-checks" in content or "git-auto-sync" in content
        except OSError:
            has_sync = False
        log(f"  Check Sync:     {'[OK]' if has_sync else '[N/A]'}")
    else:
        log("  Check Sync:     [N/A]")

    local_dir = Path(LOCAL_DIR)
    checks = (
        [p for p in local_dir.iterdir() if p.is_file() and p.name.startswith("check")]
        if local_dir.is_dir()
        else []
    )
    log(f"  Local Checks:   [OK] ({len(checks)} scripts)" if checks else "  Local Checks:   [N/A]")

    plugins_dir = Path(PLUGINS_DIR)
    plugins = [p for p in plugins_dir.iterdir() if p.is_file()] if plugins_dir.is_dir() else []
    log(f"  Plugins:        [OK] ({len(plugins)} plugins)" if plugins else "  Plugins:        [N/A]")

    log("=========================================")
    log("PERSISTENT Startup Check - COMPLETATO")
    log("=========================================")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print(f"persistent-startup-check.py v{VERSION}")
        print("Verifica e ripristina servizi critici CheckMK dopo major upgrade NethSecurity 8.")
        print(f"Log: {LOG_FILE}")
        return 0

    log("=========================================")
    log(f"PERSISTENT Startup Check v{VERSION} - AVVIO")
    log("=========================================")

    verify_webui()
    verify_checkmk_agent()
    verify_sync()
    auto_deploy_checks()
    verify_sysupgrade()
    print_summary()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
