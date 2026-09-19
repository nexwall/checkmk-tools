#!/usr/bin/env python3
"""update_checkmk_agent.py - Automatically update CheckMK Agent

Check if the local agent is aligned with the CheckMK server version.
If the server is newer → download and install the new agent from the server itself.
If the server is not yet updated → skip (available version == local version).

This ensures that the agent is never updated before the server.

Usage:
    # Auto-detect server from local OMD installation
    python3 update_checkmk_agent.py

    # Specify server manually (override or host without local OMD)
    python3 update_checkmk_agent.py --server-url https://<your-checkmk-server>/monitoring
    python3 update_checkmk_agent.py --server-url https://<your-checkmk-server>/monitoring --dry-run
    python3 update_checkmk_agent.py --server-url https://<your-checkmk-server>/monitoring --force

Version: 0.3.0"""

# Python 3.6 compatibility: 'text' alias for 'universal_newlines'
import sys as _sys
if _sys.version_info < (3, 7):
    import subprocess as _subprocess
    _orig_check_output = _subprocess.check_output
    def _compat_check_output(*args, **kwargs):
        if 'text' in kwargs:
            kwargs['universal_newlines'] = kwargs.pop('text')
        return _orig_check_output(*args, **kwargs)
    _subprocess.check_output = _compat_check_output

    _orig_run = _subprocess.run
    def _compat_run(*args, **kwargs):
        if 'text' in kwargs:
            kwargs['universal_newlines'] = kwargs.pop('text')
        if 'capture_output' in kwargs:
            capture = kwargs.pop('capture_output')
            if capture:
                kwargs['stdout'] = _subprocess.PIPE
                kwargs['stderr'] = _subprocess.PIPE
        return _orig_run(*args, **kwargs)
    _subprocess.run = _compat_run

import argparse
import json
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Tuple

VERSION = "0.7.3"

# ─── OS Detection ─────────────────────────────────────────────────────────────

def detect_pkg_type() -> str:
    """Detects the type of package required for this OS.

    Returns:
        'deb', 'rpm', or 'openwrt'"""
    if Path("/etc/openwrt_release").exists():
        return "openwrt"
    if shutil.which("dpkg"):
        return "deb"
    if shutil.which("rpm"):
        return "rpm"
    print("[ERROR] OS non supportato (nessun dpkg/rpm/openwrt rilevato)", file=sys.stderr)
    sys.exit(1)


# ─── Local Agent Version ────────────────────────── ──────────────────────────

def get_local_agent_version(pkg_type: str) -> Optional[str]:
    """Reads the version of the locally installed CheckMK agent.

    Returns:
        String version e.g. '2.4.0p23' or None if not installed."""
    if pkg_type == "deb":
        try:
            out = subprocess.check_output(
                ["dpkg-query", "-W", "-f=${Version}", "check-mk-agent"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            # formato: 2.4.0p23-1 → strip suffisso debian
            return out.split("-")[0] if out else None
        except subprocess.CalledProcessError:
            return None

    if pkg_type == "rpm":
        try:
            out = subprocess.check_output(
                ["rpm", "-q", "--queryformat", "%{VERSION}", "check-mk-agent"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            return out if out and "not installed" not in out else None
        except subprocess.CalledProcessError:
            return None

    if pkg_type == "openwrt":
        # On OpenWrt the agent is a standalone binary, not a managed package
        # Try reading the version from the agent output
        try:
            out = subprocess.check_output(
                ["/usr/bin/check_mk_agent", "--version"],
                stderr=subprocess.STDOUT,
                text=True,
                timeout=5,
            )
            m = re.search(r"(\d+\.\d+\.\d+(?:p\d+)?)", out)
            return m.group(1) if m else None
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return None

    return None

# ─── Auto-detect Server URL ───────────────────────────── ──────────────────────────────

def detect_local_server_url() -> Optional[str]:
    """Auto-detect CheckMK server URL from local OMD installation.

    Search for the OMD site name, then try reaching the REST API at:
      1. http://localhost/{site}
      2. https://localhost/{site}
      3. https://{fqdn}/{site}
    Returns the first URL that responds or None if OMD is not installed."""
    # Trova sito OMD
    site: Optional[str] = None

    omd_sites_dir = Path("/omd/sites")
    if omd_sites_dir.exists():
        sites = sorted(d.name for d in omd_sites_dir.iterdir() if d.is_dir())
        if sites:
            site = sites[0]

    if not site:
        try:
            result = subprocess.run(
                ["omd", "sites", "--bare"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                found = [s.strip() for s in result.stdout.splitlines() if s.strip()]
                if found:
                    site = found[0]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    if not site:
        return None

    # Use hostname -f to get the FQDN of the current machine
    try:
        hostname = subprocess.check_output(
            ["hostname", "-f"], text=True, timeout=5
        ).strip()
    except Exception:
        hostname = socket.gethostname()

    return f"https://{hostname}/{site}"


def normalize_server_url(url: str) -> str:
    """It ensures that the URL has https:// scheme and is well-formed."""
    url = url.strip()
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def parse_server_url(server_url: str) -> Tuple[str, str]:
    """Extracts hostname and site name from the server URL.

    Args:
        server_url: e.g. 'https://<your-checkmk-server>/monitoring'

    Returns:
        Tuple (hostname, site) e.g. ('<your-checkmk-server>', 'monitoring')"""  
    parsed = urllib.parse.urlparse(server_url)
    hostname = parsed.netloc
    site = parsed.path.strip('/').split('/')[0] if parsed.path.strip('/') else ''
    return hostname, site

# ─── Agent version on the Server ──────────────────────── ────────────────────────

def get_server_agent_version(server_url: str, pkg_type: str) -> Optional[str]:
    """Query the CheckMK server to get the available agent version.

    Strategies in order:
      1. Direct reading symlink /omd/sites/{site}/version (only if local OMD,
         zero HTTP, zero authentication — most reliable method)
      2. REST API /check_mk/api/1.0/version (requires reachable server, no auth)
      3. Scraping page /check_mk/agents/ (final fallback)

    Args:
        server_url: base URL of the CheckMK site (e.g. https://<your-checkmk-server>/monitoring)
        pkg_type: Package type (to build download URL)

    Returns:
        String version e.g. '2.4.0p23' or None if unreachable."""
    import json, ssl

    # Strategy 1: local symlink OMD reading (when the script runs on the server itself)
    # /omd/sites/{site}/version -> ../../versions/2.4.0p23.cre
    _, site = parse_server_url(server_url)
    if site:
        version_link = Path(f"/omd/sites/{site}/version")
        if version_link.is_symlink():
            target = version_link.resolve().name  # es. "2.4.0p23.cre"
            m = re.match(r"(\d+\.\d+\.\d+(?:p\d+)?)", target)
            if m:
                return m.group(1)

    # Strategy 2: REST API (does not require authentication for /version on external servers)
    # Use SSLContext which accepts self-signed for localhost
    api_url = f"{server_url.rstrip('/')}/check_mk/api/1.0/version"
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request(api_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as resp:
            data = json.loads(resp.read().decode())
            ver = data.get("version", "")
            if ver:
                m = re.match(r"(\d+\.\d+\.\d+(?:p\d+)?)", ver)
                return m.group(1) if m else ver
    except Exception:
        pass

    # Strategia 3: scraping pagina agents (fallback)
    agents_url = f"{server_url.rstrip('/')}/check_mk/agents/"
    try:
        with urllib.request.urlopen(agents_url, timeout=10, context=ssl_ctx) as resp:
            html = resp.read().decode(errors="replace")
        pattern = r'check-mk-agent[_-](\d+\.\d+\.\d+p\d+)'
        m = re.search(pattern, html)
        if m:
            return m.group(1)
    except Exception:
        pass

    return None


# ─── Download Agent ───────────────────────────────────────────────────────────

def build_download_url(server_url: str, server_ver: str, pkg_type: str) -> Tuple[str, str]:
    """Constructs download URL and filename of the agent package dynamically,
    starting from the version already obtained via REST API.

    Does not make any HTTP calls: URL and filename are deterministic.

    Args:
        server_url: CheckMK site base URL
        server_ver: Agent version on the server (e.g. '2.4.0p23')
        pkg_type: Package type ('deb', 'rpm', 'openwrt')

    Returns:
        Tuple (full_url, filename)"""
    agents_base = f"{server_url.rstrip('/')}/check_mk/agents/"
    if pkg_type in ("deb", "openwrt"):
        filename = f"check-mk-agent_{server_ver}-1_all.deb"
    elif pkg_type == "rpm":
        filename = f"check-mk-agent-{server_ver}-1.noarch.rpm"
    else:
        raise ValueError(f"Tipo pacchetto non supportato: {pkg_type}")
    return f"{agents_base}{filename}", filename


def download_agent(server_url: str, server_ver: str, pkg_type: str, dest_dir: Path) -> Optional[Path]:
    """Download the agent package from the CheckMK server.

    The URL is built dynamically from the already known version (no HTML scraping).

    Args:
        server_url: CheckMK site base URL
        server_ver: Agent version on the server (already obtained via REST API)
        pkg_type: Package type
        dest_dir: Temporary directory where to save the file

    Returns:
        Path to the downloaded file or None in case of error."""
    url, filename = build_download_url(server_url, server_ver, pkg_type)
    dest = dest_dir / filename

    print(f"[INFO] Download: {url}")
    try:
        urllib.request.urlretrieve(url, str(dest))
        print(f"[OK]   Scaricato: {dest}")
        return dest
    except Exception as e:
        print(f"[ERROR] Download fallito: {e}", file=sys.stderr)
        return None


# ─── Agent installation ─────────────────────────── ───────────────────────────

def install_agent_deb(pkg_path: Path) -> bool:
    """Install .deb package and fix dependencies."""
    print(f"[INFO] Installazione {pkg_path.name}...")
    ret = subprocess.run(["dpkg", "-i", str(pkg_path)]).returncode
    if ret != 0:
        # fix dipendenze rotte
        subprocess.run(["apt-get", "install", "-f", "-y"])
    # Disable cmk-agent-ctl-daemon (due to port 6556 conflict)
    subprocess.run(["systemctl", "stop", "cmk-agent-ctl-daemon.service"],
                   stderr=subprocess.DEVNULL)
    subprocess.run(["systemctl", "disable", "cmk-agent-ctl-daemon.service"],
                   stderr=subprocess.DEVNULL)
    subprocess.run(["systemctl", "reset-failed", "cmk-agent-ctl-daemon.service"],
                   stderr=subprocess.DEVNULL)
    return ret == 0


def install_agent_rpm(pkg_path: Path) -> bool:
    """Install .rpm package."""
    print(f"[INFO] Installazione {pkg_path.name}...")
    ret = subprocess.run(["rpm", "-Uvh", "--replacepkgs", str(pkg_path)]).returncode
    return ret == 0


def install_agent_openwrt(pkg_path: Path) -> bool:
    """Install agent on OpenWrt by extracting the binary from the .deb manually
    (ar + tar, no dpkg available)."""
    print(f"[INFO] Estrazione binario da {pkg_path.name} (OpenWrt)...")
    tmpdir = Path(tempfile.mkdtemp())
    try:
        subprocess.run(["ar", "x", str(pkg_path)], cwd=str(tmpdir), check=True)
        data_tars = list(tmpdir.glob("data.tar.*"))
        if not data_tars:
            print("[ERROR] data.tar.* non trovato nel .deb", file=sys.stderr)
            return False
        subprocess.run(["tar", "-xf", str(data_tars[0]), "-C", str(tmpdir)], check=True)
        for candidate in (tmpdir / "usr/bin/check_mk_agent",
                          tmpdir / "usr/bin/check-mk-agent"):
            if candidate.exists():
                subprocess.run(["install", "-m", "0755", str(candidate),
                                "/usr/bin/check_mk_agent"], check=True)
                print("[OK] check_mk_agent aggiornato")
                return True
        print("[ERROR] Binario agent non trovato nel .deb", file=sys.stderr)
        return False
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Estrazione fallita: {e}", file=sys.stderr)
        return False
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


# ─── Comparazione Versioni ────────────────────────────────────────────────────

def parse_version(ver: str) -> Tuple[int, int, int, int]:
    """Converts CheckMK version string to comparable tuple.
    Ex: '2.4.0p23' → (2, 4, 0, 23)
        '2.4.0' → (2, 4, 0, 0)"""
    m = re.match(r"(\d+)\.(\d+)\.(\d+)(?:p(\d+))?", ver.strip())
    if not m:
        return (0, 0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4) or 0))


# ─── Main ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=f"update_checkmk_agent.py v{VERSION} - Aggiornamento automatico agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Auto-detect server from local OMD installation (machine with CheckMK server)
  python3 update_checkmk_agent.py
  python3 update_checkmk_agent.py --dry-run

  # Specify server manually (monitored hosts without local OMD)
  python3 update_checkmk_agent.py --server-url https://<your-checkmk-server>/monitoring
  python3 update_checkmk_agent.py --server-url https://<your-checkmk-server>/monitoring --dry-run
  python3 update_checkmk_agent.py --server-url https://<your-checkmk-server>/monitoring --force""",
    )
    p.add_argument("--server-url", required=False, default=None,
                   help="URL sito CheckMK es. https://hostname/site. "
                        "Se omesso, auto-rilevato dall'installazione OMD locale.")
    p.add_argument("--dry-run", action="store_true",
                   help="Mostra cosa farebbe senza eseguire modifiche")
    p.add_argument("--force", action="store_true",
                   help="Forza reinstallazione anche se versione già aggiornata")
    p.add_argument("--install-cron", action="store_true",
                   help="Installa un cron job per aggiornamento automatico periodico")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if os.geteuid() != 0:
        print("[ERROR] Richiesto root", file=sys.stderr)
        return 1

    # Resolve URL server: if passed via CLI use it directly (normalized),
    # otherwise ALWAYS ask the user (auto-detect as a hint)
    server_url = normalize_server_url(args.server_url) if args.server_url else None
    if not server_url:
        if sys.stdin.isatty():
            detected = detect_local_server_url()
            det_host, det_site = parse_server_url(detected) if detected else ("", "")
            if detected:
                print(f"[INFO] Server rilevato localmente: {detected}")

            # Chiedi hostname
            h_prompt = f"[INPUT] Hostname server CheckMK [{det_host}]: " if det_host \
                       else "[INPUT] CheckMK server hostname: "
            try:
                h_answer = input(h_prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[ERROR] Input interrotto.", file=sys.stderr)
                return 1
            server_hostname_input = h_answer if h_answer else det_host
            if not server_hostname_input:
                print("[ERROR] Hostname non fornito.", file=sys.stderr)
                return 1

            # Chiedi site
            s_prompt = f"[INPUT] Site name [{det_site}]: " if det_site \
                       else "[INPUT] Site name (es. monitoring): "
            try:
                s_answer = input(s_prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[ERROR] Input interrotto.", file=sys.stderr)
                return 1
            server_site_input = s_answer if s_answer else det_site
            if not server_site_input:
                print("[ERROR] Site name non fornito.", file=sys.stderr)
                return 1

            server_url = f"https://{server_hostname_input}/{server_site_input}"
            print(f"[INFO] URL costruito: {server_url}")
        else:
            print("[ERROR] --server-url non fornito e sessione non interattiva.", file=sys.stderr)
            print("[ERROR] Fornire: --server-url https://hostname/site", file=sys.stderr)
            return 1

    # Hostname of the local machine (the one we are updating)
    try:
        local_hostname = subprocess.check_output(
            ["hostname", "-f"], text=True, timeout=5
        ).strip()
    except Exception:
        local_hostname = socket.gethostname()

    # From the server_url we extract only the information for display; the URL remains unchanged
    # for network operations (version query + download)
    server_hostname, server_site = parse_server_url(server_url)

    print(f"{'='*55}")
    print(f"  update_checkmk_agent.py v{VERSION}")
    print(f"  Questo host: {local_hostname}")
    print(f"  Server:      {server_hostname}/{server_site}")
    print(f"{'='*55}")

    # Install-cron mode: Configure cron job and exit
    if args.install_cron:
        return install_cron_job(server_url)

    # 1. Detect OS
    pkg_type = detect_pkg_type()
    print(f"[INFO] Tipo pacchetto: {pkg_type}")

    # 2. Local version
    local_ver = get_local_agent_version(pkg_type)
    if local_ver:
        print(f"[INFO] Agent locale:   {local_ver}")
    else:
        print("[INFO] Agent locale:   non installato")

    # 3. Version available on the server
    print(f"[INFO] Query server ({server_hostname}/{server_site})...")
    server_ver = get_server_agent_version(server_url, pkg_type)
    if not server_ver:
        print("[ERROR] Impossibile ottenere versione dal server. "
              "Server non raggiungibile o non ancora aggiornato.", file=sys.stderr)
        return 1
    print(f"[INFO] Agent su server: {server_ver}")

    # 4. Confronto versioni
    local_tuple = parse_version(local_ver) if local_ver else (0, 0, 0, 0)
    server_tuple = parse_version(server_ver)

    if server_tuple < local_tuple:
        # Agent newer than the server → the server is not yet updated
        print(f"[WARN] Agent locale ({local_ver}) è più nuovo del server ({server_ver}).")
        print("[WARN] Il server non è ancora stato aggiornato. Skip.")
        return 0

    if server_tuple == local_tuple and not args.force:
        print(f"[OK] Agent già aggiornato alla versione {local_ver}. Niente da fare.")
        return 0

    if args.force and server_tuple == local_tuple:
        print(f"[INFO] --force: reinstallo la versione {server_ver}")
    else:
        print(f"[INFO] Aggiornamento disponibile: {local_ver or 'N/A'} → {server_ver}")

    if args.dry_run:
        print("[DRY-RUN] Nessuna modifica eseguita.")
        return 0

    # 5. Download
    tmpdir = Path(tempfile.mkdtemp(prefix="cmk-agent-update-"))
    try:
        pkg_path = download_agent(server_url, server_ver, pkg_type, tmpdir)
        if not pkg_path:
            return 1

        # 6. Installation
        if pkg_type == "deb":
            ok = install_agent_deb(pkg_path)
        elif pkg_type == "rpm":
            ok = install_agent_rpm(pkg_path)
        elif pkg_type == "openwrt":
            ok = install_agent_openwrt(pkg_path)
        else:
            ok = False

        if ok:
            new_ver = get_local_agent_version(pkg_type)
            print(f"[OK] Aggiornamento completato → {new_ver or server_ver}")
            return 0
        else:
            print("[ERROR] Installazione fallita", file=sys.stderr)
            return 1
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


def install_cron_job(server_url: str) -> int:
    """Install a cron job for periodic automatic updating."""
    script_path = os.path.abspath(__file__)
    log_file = "/var/log/update_checkmk_agent.log"

    print("\n[CRON] Configurazione aggiornamento automatico")
    print("  1) Ogni giorno  (alle 03:00)")
    print("  2) Ogni settimana (domenica alle 03:00)")
    print("  3) Personalizzato (espressione cron manuale)")
    print("  0) Annulla")
    try:
        choice = input("[INPUT] Scegli frequenza [1]: ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        print("\n[ERROR] Input interrotto.", file=sys.stderr)
        return 1

    if choice == "0":
        print("[INFO] Installazione cron annullata.")
        return 0
    elif choice == "1":
        schedule = "0 3 * * *"
        desc = "ogni giorno alle 03:00"
    elif choice == "2":
        schedule = "0 3 * * 0"
        desc = "ogni domenica alle 03:00"
    elif choice == "3":
        try:
            schedule = input("[INPUT] Espressione cron (es. '0 3 * * *'): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[ERROR] Input interrotto.", file=sys.stderr)
            return 1
        if not schedule:
            print("[ERROR] Espressione cron non fornita.", file=sys.stderr)
            return 1
        desc = schedule
    else:
        print("[ERROR] Scelta non valida.", file=sys.stderr)
        return 1

    cron_line = (f"{schedule} root python3 {script_path} "
                 f"--server-url {server_url} >> {log_file} 2>&1")
    cron_file = "/etc/cron.d/update-checkmk-agent"

    print(f"\n[INFO] Cron job che verrà installato:")
    print(f"  File:      {cron_file}")
    print(f"  Frequenza: {desc}")
    print(f"  Comando:   {cron_line}")
    print(f"  Log:       {log_file}")
    try:
        confirm = input("[INPUT] Confermi installazione? [S/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n[ERROR] Input interrotto.", file=sys.stderr)
        return 1
    if confirm in ("n", "no"):
        print("[INFO] Installazione annullata.")
        return 0

    with open(cron_file, "w") as f:
        f.write("# CheckMK Agent auto-update\n")
        f.write(f"# Installato da update_checkmk_agent.py v{VERSION}\n")
        f.write(f"{cron_line}\n")
    os.chmod(cron_file, 0o644)
    print(f"[OK] Cron job installato in {cron_file}")
    print(f"[OK] Log in {log_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
