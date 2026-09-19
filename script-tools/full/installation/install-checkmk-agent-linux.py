#!/usr/bin/env python3
"""install-checkmk-agent-linux.py - CheckMK unified installer

Execute in sequence:
  STEP A  → CheckMK Agent install (download from CMK server, TCP 6556)
              + cmk-agent-ctl native plain pull (allow_legacy_pull + ip_allowlist,
                no TLS/stunnel - IP(s) autorizzati chiesti interattivamente,
                supporta piu' di un IP)
              + optional FRPC (tunnel to FRP server)
  STEP 1  → auto-git-sync (automatic git pull every N seconds)
  STEP 2  → checkmk-python-full-sync (deploy check Python every 5 minutes)
  STEP 3  → checkmk-agent-sync (daily agent version verification, verify-only)

Compatibility:
  - Debian/Ubuntu → deb + systemd socket
  - RHEL/Rocky/NethServer → rpm + systemd socket
  - OpenWrt / NethSecurity 8 → manual .deb extraction + socat/procd
  - Cron-only systems → cron jobs fallback for git-sync/py-sync

Replaces:
  - install-agent-interactive.sh / install-agent-interactive.py
  - install-auto-git-sync.sh
  - install-python-full-sync.py

Version: 2.0.0"""

import argparse
import ipaddress
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

VERSION = "2.5.0"

# Global SSL verify flag (set to False via --no-verify-ssl)
SSL_VERIFY = True

# ─── Costanti ─────────────────────────────────────────────────────────────────

REPO_DEFAULT_PATH = Path("/opt/checkmk-tools")
REPO_URL_DEFAULT = "https://github.com/nethesis/checkmk-tools.git"
SYSTEMD_DIR = Path("/etc/systemd/system")
LOCAL_TARGET_DEFAULT = "/usr/lib/check_mk_agent/local"

# CheckMK Agent
CHECKMK_BASE_URL_DEFAULT = os.environ.get("CMK_AGENTS_URL", "https://monitor.nethlab.it/monitoring/check_mk/agents")

# cmk-agent-ctl native plain pull (allow_legacy_pull + ip_allowlist, no TLS/stunnel)
CMK_AGENT_DIR = Path("/var/lib/cmk-agent")
CMK_AGENT_CTL_TOML = CMK_AGENT_DIR / "cmk-agent-ctl.toml"
CMK_AGENT_ALLOW_LEGACY_PULL = CMK_AGENT_DIR / "allow-legacy-pull"
CMK_AGENT_SOCKET_NAME = "check-mk-agent.socket"
CMK_AGENT_CTL_DAEMON_NAME = "cmk-agent-ctl-daemon.service"
DEFAULT_ALLOWED_IPS = ["127.0.0.1"]
# Legacy units possibly left over from an older classic-socket install - always cleaned up
LEGACY_UNITS_TO_DISABLE = (
    "stunnel-checkmk", "stunnel4",
    "check-mk-agent-plain.socket", "check-mk-agent-plain@.service",
)

# FRPC
FRP_VERSION_DEFAULT = "0.64.0"
FRPC_BIN = "/usr/local/bin/frpc"
FRPC_CONF_DIR = Path("/etc/frp")
FRPC_CONF_FILE = FRPC_CONF_DIR / "frpc.toml"

# auto-git-sync
GIT_SYNC_SERVICE_NAME = "auto-git-sync.service"
GIT_SYNC_TIMER_NAME = "auto-git-sync.timer"
GIT_SYNC_LOG = "/var/log/auto-git-sync.log"
GIT_SYNC_CRON_MARKER = "git-auto-sync"

# checkmk-python-full-sync
PYTHON_SYNC_SERVICE_NAME = "checkmk-python-full-sync.service"
PYTHON_SYNC_TIMER_NAME = "checkmk-python-full-sync.timer"
PYTHON_SYNC_LOG = "/var/log/checkmk-python-full-sync.log"
PYTHON_SYNC_CRON_MARKER = "sync-python-full-checks"

OPENWRT_CRONTAB = Path("/etc/crontabs/root")

# checkmk-agent-sync (agent auto-update verification)
AGENT_SYNC_SERVICE_NAME = "checkmk-agent-sync.service"
AGENT_SYNC_TIMER_NAME = "checkmk-agent-sync.timer"
AGENT_SYNC_ENV_DIR = Path("/etc/checkmk-agent-sync")
AGENT_SYNC_ENV_FILE = AGENT_SYNC_ENV_DIR / "checkmk-agent-sync.env"
AGENT_SYNC_SCRIPT = "/opt/checkmk-tools/script-tools/full/agent_maintenance/checkmk-agent-autoupdate-linux.py"



# ─── Utilities ────────────────────────────────────────────────────────────────

def run(cmd: List[str], **kwargs) -> None:
    """Execute command, raise exception if failed."""
    subprocess.run(cmd, check=True, **kwargs)


def run_capture(cmd: List[str], cwd: str = "") -> subprocess.CompletedProcess:
    """Execute command and capture output (does not raise exception)."""
    return subprocess.run(
        cmd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        cwd=cwd or None,
    )


def unlink_safe(path: Path) -> None:
    """Path.unlink(missing_ok=True) equivalent - missing_ok needs Python 3.8+,
    NethServer 7 hosts still run 3.6."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def require_root() -> None:
    if os.geteuid() != 0:
        print("[ERROR] Eseguire come root", file=sys.stderr)
        sys.exit(1)


def is_openwrt() -> bool:
    return Path("/etc/openwrt_release").exists()


def has_systemd() -> bool:
    return shutil.which("systemctl") is not None and SYSTEMD_DIR.exists()


def detect_pkg_manager() -> str:
    for name, cmd in [("apt", "apt-get"), ("dnf", "dnf"), ("yum", "yum"), ("opkg", "opkg")]:
        if shutil.which(cmd):
            return name
    return ""


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def get_repo_owner(repo_path: Path) -> str:
    result = run_capture(["stat", "-c", "%U", str(repo_path)])
    owner = (result.stdout or "root").strip()
    return owner if owner else "root"


def cron_update(lines_to_keep_filter: str, new_line: str, openwrt: bool = False) -> None:
    """Update crontab: remove lines with markers, add new line."""
    if openwrt:
        current = []
        if OPENWRT_CRONTAB.exists():
            current = [
                l for l in OPENWRT_CRONTAB.read_text(encoding="utf-8").splitlines()
                if lines_to_keep_filter not in l
            ]
        current.append(new_line)
        OPENWRT_CRONTAB.write_text("\n".join(current) + "\n", encoding="utf-8")
        run_capture(["sh", "-c", "/etc/init.d/cron restart 2>/dev/null || true"])
    else:
        existing = run_capture(["crontab", "-l"])
        current = [
            l for l in (existing.stdout or "").splitlines()
            if lines_to_keep_filter not in l and l.strip()
        ]
        current.append(new_line)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cron", delete=False) as f:
            f.write("\n".join(current) + "\n")
            tmp = f.name
        run(["crontab", tmp])
        unlink_safe(Path(tmp))


# ─── STEP A: CheckMK Agent + FRPC ─────────────────────────────────────────────

# agente – rilevamento OS ─────────────────────────────────────────────────────

def detect_os_info() -> Dict[str, str]:
    """Detects OS and returns a dictionary with keys:
      os_id, os_ver, pkg_type (deb|rpm|openwrt), pkg_manager (apt|dnf|yum|opkg)"""
    info: Dict[str, str] = {
        "os_id": "", "os_ver": "", "pkg_type": "", "pkg_manager": "",
    }

    # OpenWrt / NethSecurity 8
    if (
        Path("/etc/openwrt_release").exists()
        or (
            Path("/etc/os-release").exists()
            and "openwrt" in Path("/etc/os-release").read_text(errors="ignore").lower()
        )
    ):
        info["os_id"] = "openwrt"
        if Path("/etc/openwrt_release").exists():
            for line in Path("/etc/openwrt_release").read_text(errors="ignore").splitlines():
                if line.startswith("DISTRIB_RELEASE="):
                    info["os_ver"] = line.split("'")[1] if "'" in line else line.split("=", 1)[1].strip()
                    break
        info["pkg_type"] = "openwrt"
        info["pkg_manager"] = "opkg"
        print(f"[INFO] Sistema: openwrt {info['os_ver']}")
        return info

    # Linux standard (/etc/os-release)
    if Path("/etc/os-release").exists():
        for line in Path("/etc/os-release").read_text(errors="ignore").splitlines():
            if line.startswith("ID="):
                info["os_id"] = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("VERSION_ID="):
                info["os_ver"] = line.split("=", 1)[1].strip().strip('"')

    if Path("/etc/nethserver-release").exists():
        info["os_id"] = "nethserver"

    if info["os_id"] in ("debian", "ubuntu"):
        info["pkg_type"] = "deb"
        info["pkg_manager"] = "apt"
    elif info["os_id"] in ("rocky", "rhel", "centos", "almalinux", "fedora",
                           "nethserver", "nethserver-enterprise"):
        info["pkg_type"] = "rpm"
        info["pkg_manager"] = "dnf" if shutil.which("dnf") else "yum"
    else:
        print(f"[WARN] OS non riconosciuto: '{info['os_id']}'. Tentativo con apt...", file=sys.stderr)
        info["pkg_type"] = "deb"
        info["pkg_manager"] = "apt"

    print(f"[INFO] Sistema: {info['os_id']} {info['os_ver']} ({info['pkg_type']})")
    return info


# agente – download ───────────────────────────────────────────────────────────

def fetch_text(url: str, timeout: int = 15) -> str:
    """Download text from URL (no external dependencies).

    Raises: RuntimeError if it fails."""
    try:
        ctx = None
        if not SSL_VERIFY:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(url, timeout=timeout, context=ctx) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        raise RuntimeError(f"fetch_text({url}): {exc}") from exc


def download_file(url: str, outpath: str) -> None:
    """Download binary file with curl or wget."""
    if shutil.which("curl"):
        cmd = ["curl", "-fsSL"]
        if not SSL_VERIFY:
            cmd.append("-k")
        cmd += [url, "-o", outpath]
        run(cmd)
    elif shutil.which("wget"):
        cmd = ["wget", "-q"]
        if not SSL_VERIFY:
            cmd.append("--no-check-certificate")
        cmd += ["-O", outpath, url]
        run(cmd)
    else:
        raise RuntimeError("né curl né wget trovati per il download")


def latest_agent_filename(base_url: str, pkg_type: str) -> str:
    """Gets the file name of the latest agent version from the HTML listing."""
    try:
        html = fetch_text(base_url + "/")
    except RuntimeError as exc:
        raise RuntimeError(f"Impossibile leggere listing agenti: {exc}") from exc

    if pkg_type in ("deb", "openwrt"):
        pattern = r'check-mk-agent_[\d.]+p[\d]+-[\d]+_all\.deb'
    else:
        pattern = r'check-mk-agent-[\d.]+p[\d]+-[\d]+\.noarch\.rpm'

    matches = sorted(re.findall(pattern, html))
    if not matches:
        raise RuntimeError(f"Nessun pacchetto trovato in: {base_url}/")
    return matches[-1]


# agent – Linux installation ──────────────────────── ────────────────────────

def _pkg_install(pkg_mgr: str, *packages: str) -> None:
    """Install packages with the specified package manager."""
    if pkg_mgr == "apt":
        run(["apt-get", "install", "-y", *packages])
    elif pkg_mgr == "dnf":
        run(["dnf", "install", "-y", *packages])
    elif pkg_mgr == "yum":
        run(["yum", "install", "-y", *packages])
    elif pkg_mgr == "opkg":
        run(["opkg", "install", *packages])
    else:
        raise RuntimeError(f"Package manager non supportato: {pkg_mgr}")


def install_agent_linux(base_url: str, pkg_type: str, pkg_mgr: str) -> None:
    """Install CheckMK agent on Debian/Ubuntu/RHEL via deb or rpm."""
    fname = latest_agent_filename(base_url, pkg_type)
    url = f"{base_url}/{fname}"
    tmp = f"/tmp/{fname}"
    print(f"[INFO] Download agente: {url}")
    download_file(url, tmp)
    print(f"[INFO] Installazione: {fname}")
    if pkg_type == "deb":
        result = run_capture(["dpkg", "-i", tmp])
        if result.returncode != 0:
            # fix broken dependencies (common on Ubuntu)
            run_capture([pkg_mgr == "apt" and "apt-get" or "apt-get",
                         "install", "-f", "-y"])
    else:
        if not shutil.which("rpm"):
            raise RuntimeError("rpm non trovato")
        run(["rpm", "-Uvh", "--replacepkgs", tmp])
    unlink_safe(Path(tmp))


def install_agent_openwrt(base_url: str) -> None:
    """Install CheckMK agent on OpenWrt: Extract the binary from the .deb manually."""
    # installs dependencies needed to extract .deb
    run_capture(["opkg", "update"])
    for pkg in ("ca-certificates", "wget", "tar", "gzip", "socat", "binutils"):
        run_capture(["opkg", "install", pkg])

    if not shutil.which("ar") or not shutil.which("tar"):
        raise RuntimeError("ar e tar obbligatori per estrarre il .deb su OpenWrt")

    fname = latest_agent_filename(base_url, "openwrt")
    url = f"{base_url}/{fname}"
    tmpdir = tempfile.mkdtemp()
    deb = f"{tmpdir}/{fname}"

    print(f"[INFO] Download agente (deb): {url}")
    download_file(url, deb)

    run(["ar", "x", deb], cwd=tmpdir)
    data_tars = list(Path(tmpdir).glob("data.tar.*"))
    if not data_tars:
        raise RuntimeError("data.tar.* non trovato nel .deb")
    run(["tar", "-xf", str(data_tars[0]), "-C", tmpdir])

    for candidate in (
        f"{tmpdir}/usr/bin/check_mk_agent",
        f"{tmpdir}/usr/bin/check-mk-agent",
    ):
        if Path(candidate).exists():
            run(["install", "-m", "0755", candidate, "/usr/bin/check_mk_agent"])
            break
    else:
        raise RuntimeError("Binario agente non trovato nel .deb")

    shutil.rmtree(tmpdir, ignore_errors=True)
    print("[OK] check_mk_agent installato in /usr/bin/check_mk_agent")


def install_agent(base_url: str, os_info: Dict[str, str]) -> None:
    """Agent installation dispatcher based on OS."""
    if os_info["pkg_type"] == "openwrt":
        install_agent_openwrt(base_url)
    else:
        # assicura curl/wget disponibili
        run_capture([
            os_info["pkg_manager"] if os_info["pkg_manager"] in ("apt", "dnf", "yum")
            else "apt-get",
            "install", "-y", "ca-certificates", "curl", "wget",
        ])
        # update cache before installing
        if os_info["pkg_manager"] == "apt":
            run_capture(["apt-get", "update", "-y"])
        install_agent_linux(base_url, os_info["pkg_type"], os_info["pkg_manager"])


# agent – socket configuration ─────────────────────── ───────────────────────

_AGENT_OPENWRT_INITD = """\
#!/bin/sh /etc/rc.common
START=98
STOP=10
USE_PROCD=1

PROG=/usr/bin/check_mk_agent

start_service() {
    procd_open_instance
    procd_set_param command socat TCP-LISTEN:6556,bind=127.0.0.1,reuseaddr,fork,keepalive EXEC:$PROG
    procd_set_param respawn
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}

stop_service() {
    killall socat >/dev/null 2>&1 || true
}"""


def configure_agent_plain_pull(allowed_ips: List[str]) -> None:
    """Configure the agent's own cmk-agent-ctl for native plain-text pull,
    restricted to allowed_ips via ip_allowlist - no TLS, no stunnel, no custom
    socket unit. Port 6556 stays open to plain connections only from the
    given IPs (typically 127.0.0.1 when reached through an frpc tunnel, plus
    any additional host that needs direct access)."""
    run_capture(["cmk-agent-ctl", "delete-all"])

    CMK_AGENT_DIR.mkdir(parents=True, exist_ok=True)
    CMK_AGENT_ALLOW_LEGACY_PULL.touch(exist_ok=True)
    run_capture(["chown", "cmk-agent:cmk-agent", str(CMK_AGENT_ALLOW_LEGACY_PULL)])

    ip_array = ", ".join(f'"{ip}"' for ip in allowed_ips)
    write_text(CMK_AGENT_CTL_TOML, f"allowed_ip = [{ip_array}]\n")
    run_capture(["chown", "cmk-agent:cmk-agent", str(CMK_AGENT_CTL_TOML)])
    CMK_AGENT_CTL_TOML.chmod(0o640)

    # Clean up any leftover classic-socket/stunnel setup from older installs
    for unit in LEGACY_UNITS_TO_DISABLE:
        run_capture(["systemctl", "stop", unit])
        run_capture(["systemctl", "disable", unit])

    run(["systemctl", "enable", "--now", CMK_AGENT_SOCKET_NAME])
    run(["systemctl", "enable", "--now", CMK_AGENT_CTL_DAEMON_NAME])
    # Restart explicitly: enable --now is a no-op if the units were already
    # active under a stale/conflicting config (e.g. port still held by stunnel).
    run_capture(["systemctl", "restart", CMK_AGENT_SOCKET_NAME])
    run_capture(["systemctl", "restart", CMK_AGENT_CTL_DAEMON_NAME])
    print(f"[OK] cmk-agent-ctl in modalita' plain pull nativa (porta 6556, allowed_ip={allowed_ips})")


def configure_agent_openwrt() -> None:
    """Configure agent via procd + socat on OpenWrt, bound to 127.0.0.1."""
    initd = Path("/etc/init.d/check_mk_agent")
    write_text(initd, _AGENT_OPENWRT_INITD)
    initd.chmod(0o755)
    run_capture([str(initd), "enable"])
    run_capture([str(initd), "restart"])
    print("[OK] Agente avviato via procd + socat (127.0.0.1:6556)")


def configure_agent(os_info: Dict[str, str], allowed_ips: List[str]) -> None:
    if os_info["pkg_type"] == "openwrt":
        configure_agent_openwrt()
    else:
        configure_agent_plain_pull(allowed_ips)


# agente – uninstall ──────────────────────────────────────────────────────────

def uninstall_agent(os_info: Dict[str, str]) -> None:
    """Removes CheckMK agent and its socket configuration."""
    print("[INFO] Rimozione agente CheckMK...")
    if os_info["pkg_type"] == "openwrt":
        initd = Path("/etc/init.d/check_mk_agent")
        run_capture([str(initd), "stop"])
        run_capture([str(initd), "disable"])
        unlink_safe(initd)
        unlink_safe(Path("/usr/bin/check_mk_agent"))
        shutil.rmtree("/etc/check_mk", ignore_errors=True)
    else:
        run_capture(["systemctl", "stop", CMK_AGENT_CTL_DAEMON_NAME])
        run_capture(["systemctl", "stop", CMK_AGENT_SOCKET_NAME])
        run_capture(["systemctl", "disable", CMK_AGENT_CTL_DAEMON_NAME])
        run_capture(["systemctl", "disable", CMK_AGENT_SOCKET_NAME])
        run_capture(["cmk-agent-ctl", "delete-all"])
        shutil.rmtree(str(CMK_AGENT_DIR), ignore_errors=True)
        for unit in LEGACY_UNITS_TO_DISABLE:
            run_capture(["systemctl", "stop", unit])
            run_capture(["systemctl", "disable", unit])
        run_capture(["systemctl", "daemon-reload"])
        if os_info["pkg_type"] == "deb":
            run_capture(["dpkg", "-r", "check-mk-agent"])
        elif os_info["pkg_type"] == "rpm":
            run_capture(["rpm", "-e", "check-mk-agent"])
        unlink_safe(Path("/usr/bin/check_mk_agent"))
        shutil.rmtree("/etc/check_mk", ignore_errors=True)
    print("[OK] Agente rimosso")


# FRPC – installation ──────────────────────────── ────────────────────────────

def install_frpc(frp_version: str) -> None:
    """Download and install the frpc binary."""
    import platform
    machine = platform.machine().lower()
    arch = "amd64"
    if "aarch64" in machine or "arm64" in machine:
        arch = "arm64"
    elif "arm" in machine:
        arch = "arm"

    url = (
        f"https://github.com/fatedier/frp/releases/download"
        f"/v{frp_version}/frp_{frp_version}_linux_{arch}.tar.gz"
    )
    tmpdir = tempfile.mkdtemp()
    tgz = f"{tmpdir}/frp.tgz"
    print(f"[INFO] Download FRPC v{frp_version} ({arch}): {url}")
    download_file(url, tgz)
    run(["tar", "-xzf", tgz, "-C", tmpdir])
    frpc_bin = next(Path(tmpdir).rglob("frpc"), None)
    if frpc_bin is None:
        raise RuntimeError("frpc non trovato nell'archivio")
    run(["install", "-m", "0755", str(frpc_bin), FRPC_BIN])
    shutil.rmtree(tmpdir, ignore_errors=True)
    print(f"[OK] FRPC installato: {FRPC_BIN}")


_FRPC_CONF_TPL = """\
[common]
server_addr = "{server}"
server_port = 7000
auth.method = "token"
auth.token = "{token}"
tls.enable = true
log.to = "/var/log/frpc.log"
log.level = "debug"

[{hostname}]
type = "tcp"
local_ip = "127.0.0.1"
local_port = 6556
remote_port = {remote_port}"""

_FRPC_INITD_OPENWRT = """\
#!/bin/sh /etc/rc.common
START=99
STOP=10
USE_PROCD=1

start_service() {
    procd_open_instance
    procd_set_param command /usr/local/bin/frpc -c /etc/frp/frpc.toml
    procd_set_param respawn
    procd_close_instance
}

stop_service() {
    killall frpc >/dev/null 2>&1 || true
}"""

_FRPC_SYSTEMD_SERVICE = """\
[Unit]
Description=FRP Client Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/frpc -c /etc/frp/frpc.toml
Restart=on-failure
RestartSec=5s
User=root

[Install]
WantedBy=multi-user.target"""


def configure_frpc(hostname: str, server: str, remote_port: int,
                   auth_token: str, os_info: Dict[str, str]) -> None:
    """Writes frpc.toml and installs service/init.d."""
    FRPC_CONF_DIR.mkdir(parents=True, exist_ok=True)
    write_text(FRPC_CONF_FILE, _FRPC_CONF_TPL.format(
        server=server,
        token=auth_token,
        hostname=hostname,
        remote_port=remote_port,
    ))
    FRPC_CONF_FILE.chmod(0o600)

    if os_info["pkg_type"] == "openwrt":
        initd = Path("/etc/init.d/frpc")
        write_text(initd, _FRPC_INITD_OPENWRT)
        initd.chmod(0o755)
        run_capture([str(initd), "enable"])
        run_capture([str(initd), "restart"])
    else:
        write_text(SYSTEMD_DIR / "frpc.service", _FRPC_SYSTEMD_SERVICE)
        run(["systemctl", "daemon-reload"])
        run(["systemctl", "enable", "--now", "frpc.service"])

    print(f"[OK] FRPC configurato: {server}:7000 → localhost:6556 (porta remota {remote_port})")


# FRPC – uninstall ────────────────────────────────────────────────────────────

def uninstall_frpc(os_info: Dict[str, str]) -> None:
    """Removes FRPC and its configuration."""
    print("[INFO] Rimozione FRPC...")
    if os_info["pkg_type"] == "openwrt":
        initd = Path("/etc/init.d/frpc")
        run_capture([str(initd), "stop"])
        run_capture([str(initd), "disable"])
        unlink_safe(initd)
    else:
        run_capture(["systemctl", "stop", "frpc"])
        run_capture(["systemctl", "disable", "frpc"])
        unlink_safe((SYSTEMD_DIR / "frpc.service"))
        run_capture(["systemctl", "daemon-reload"])
    unlink_safe(Path(FRPC_BIN))
    shutil.rmtree(str(FRPC_CONF_DIR), ignore_errors=True)
    print("[OK] FRPC rimosso")


# ─── Git prerequisiti ─────────────────────────────────────────────────────────

def ensure_git(pkg_mgr: str) -> None:
    if shutil.which("git"):
        return
    print("[INFO] git non trovato, installazione in corso...")
    if pkg_mgr == "apt":
        run(["apt-get", "update", "-y"])
        run(["apt-get", "install", "-y", "git"])
    elif pkg_mgr in ("dnf", "yum"):
        run([pkg_mgr, "install", "-y", "git"])
    else:
        print("[ERROR] Impossibile installare git automaticamente. Installare manualmente.", file=sys.stderr)
        sys.exit(1)
    print("[OK] git installato")


def ensure_repo(repo_path: Path, repo_url: str) -> None:
    if (repo_path / ".git").exists():
        return
    print(f"[INFO] Repository non trovato. Clonazione in {repo_path}...")
    repo_path.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", repo_url, str(repo_path)])
    print(f"[OK] Repository clonato: {repo_path}")


def update_repo(repo_path: Path) -> None:
    repo_str = str(repo_path)
    result = run_capture(["git", "fetch", "origin"], cwd=repo_str)
    if result.returncode != 0:
        print(f"[WARN] git fetch fallito: {(result.stdout or '').strip()}")
        return
    run_capture(["git", "reset", "--hard", "origin/main"], cwd=repo_str)
    run_capture(["git", "clean", "-fd"], cwd=repo_str)
    head = run_capture(["git", "rev-parse", "--short", "HEAD"], cwd=repo_str)
    sha = (head.stdout or "").strip()
    print(f"[OK] Repository aggiornato → {sha or 'ok'}")


# ─── STEP 1: Auto Git Sync ────────────────────────────────────────────────────

_GIT_SYNC_SCRIPT = "/usr/local/bin/checkmk-git-sync.sh"

_GIT_SYNC_WRAPPER = """#!/bin/bash
REPO_DIR="{repo_dir}"
LOG_FILE="{log}"
cd "$REPO_DIR" || exit 0
if ! git fetch origin >> "$LOG_FILE" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: git fetch failed" >> "$LOG_FILE"
    exit 0
fi
# Fetch tags for release traceability
git fetch --tags origin >> "$LOG_FILE" 2>&1
git reset --hard origin/main >> "$LOG_FILE" 2>&1
git clean -fd >> "$LOG_FILE" 2>&1
SHA=$(git rev-parse --short HEAD 2>/dev/null)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sync OK ($SHA)" >> "$LOG_FILE"
"""

_GIT_SYNC_SERVICE_TPL = """\
[Unit]
Description=Auto Git Sync - checkmk-tools
Documentation=https://github.com/nethesis/checkmk-tools
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User={user}
Group={user}
ExecStart=/bin/bash {script}
StandardOutput=journal
StandardError=journal
SyslogIdentifier=auto-git-sync"""

_GIT_SYNC_TIMER_TPL = """\
[Unit]
Description=Auto Git Sync timer - every {interval}s

[Timer]
OnBootSec=30s
OnUnitActiveSec={interval}s
Persistent=false

[Install]
WantedBy=timers.target"""


def install_git_sync_systemd(repo_path: Path, interval: int, owner: str) -> None:
    """Install auto-git-sync as systemd service + timer."""
    # Prepare log files
    try:
        Path(GIT_SYNC_LOG).touch(exist_ok=True)
        run_capture(["chown", f"{owner}:{owner}", GIT_SYNC_LOG])
    except Exception:
        pass

    # Write bash script wrappers (avoid multi-line ExecStart problems in systemd)
    wrapper_content = _GIT_SYNC_WRAPPER.format(repo_dir=str(repo_path), log=GIT_SYNC_LOG)
    write_text(Path(_GIT_SYNC_SCRIPT), wrapper_content)
    Path(_GIT_SYNC_SCRIPT).chmod(0o755)

    svc_path = SYSTEMD_DIR / GIT_SYNC_SERVICE_NAME
    timer_path = SYSTEMD_DIR / GIT_SYNC_TIMER_NAME

    write_text(svc_path, _GIT_SYNC_SERVICE_TPL.format(
        user=owner,
        script=_GIT_SYNC_SCRIPT,
    ))
    write_text(timer_path, _GIT_SYNC_TIMER_TPL.format(interval=interval))

    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", GIT_SYNC_TIMER_NAME])
    run(["systemctl", "start", GIT_SYNC_TIMER_NAME])

    # First sync immediate (non-fatal)
    result = run_capture(["systemctl", "start", GIT_SYNC_SERVICE_NAME])
    if result.returncode == 0:
        print(f"[OK] Primo sync eseguito")
    else:
        print(f"[WARN] Primo sync fallito (il timer lo rieseguirà): {(result.stdout or '').strip()[-200:]}")

    print(f"[OK] auto-git-sync.timer attivo → sync ogni {interval}s")
    print(f"     Log:     tail -f {GIT_SYNC_LOG}")
    print(f"     Status:  systemctl status {GIT_SYNC_TIMER_NAME}")


def install_git_sync_cron(repo_path: Path) -> None:
    """Install git sync via cron (OpenWrt / systems without systemd)."""
    cron_line = (
        f"* * * * * cd {repo_path} && "
        f"git fetch origin >> {GIT_SYNC_LOG} 2>&1 && "
        f"git fetch --tags origin >> {GIT_SYNC_LOG} 2>&1 && "
        f"git reset --hard origin/main >> {GIT_SYNC_LOG} 2>&1  # {GIT_SYNC_CRON_MARKER}"
    )
    cron_update(GIT_SYNC_CRON_MARKER, cron_line, openwrt=is_openwrt())
    print(f"[OK] auto-git-sync installato via cron (ogni minuto)")
    print(f"     Log:     tail -f {GIT_SYNC_LOG}")


# ─── STEP 2: Python Full Sync ─────────────────────────────────────────────────

_PYTHON_SYNC_SERVICE_TPL = """\
[Unit]
Description=CheckMK Python Full Checks Sync
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart={cmd}
StandardOutput=journal
StandardError=journal
SyslogIdentifier=checkmk-python-full-sync"""

_PYTHON_SYNC_TIMER_CONTENT = """\
[Unit]
Description=CheckMK Python Full Checks Sync - every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target"""


def _build_sync_cmd(py_bin: str, sync_script: Path, repo_path: Path,
                    target: str, category: str, all_categories: bool,
                    scripts: str = "", temp_dir: str = "") -> str:
    parts = [py_bin, str(sync_script), "--repo", str(repo_path), "--target", target]
    if scripts:
        parts.extend(["--scripts", scripts])
    elif all_categories:
        parts.append("--all-categories")
    else:
        parts.extend(["--category", category])
    if temp_dir:
        parts.extend(["--temp-dir", temp_dir])
    return " ".join(parts)


def _find_sync_script(repo_path: Path) -> Path:
    candidate = repo_path / "script-tools/full/sync_update/sync-python-full-checks.py"
    if not candidate.exists():
        print(f"[ERROR] Script sync non trovato: {candidate}", file=sys.stderr)
        sys.exit(1)
    # Rendi eseguibile
    candidate.chmod(candidate.stat().st_mode | 0o111)
    return candidate


def install_python_sync_systemd(repo_path: Path, target: str,
                                 category: str, all_categories: bool,
                                 scripts: str = "", temp_dir: str = "") -> None:
    """Install checkmk-python-full-sync as systemd service + timer."""
    py_bin = shutil.which("python3")
    if not py_bin:
        print("[ERROR] python3 non trovato nel PATH", file=sys.stderr)
        sys.exit(1)

    sync_script = _find_sync_script(repo_path)
    cmd = _build_sync_cmd(py_bin, sync_script, repo_path, target,
                          category, all_categories, scripts, temp_dir)

    # Modalità temp: esecuzione one-shot senza installare timer
    if temp_dir:
        print(f"[INFO] Modalità anteprima → esecuzione one-shot (nessun timer installato)")
        result = run_capture([py_bin, str(sync_script),
                              "--repo", str(repo_path),
                              "--target", target,
                              "--temp-dir", temp_dir]
                             + (["--scripts", scripts] if scripts else ["--all-categories"])
                             )
        print(result.stdout or "")
        print(f"[OK] Anteprima completata in: {temp_dir}")
        return

    svc_path = SYSTEMD_DIR / PYTHON_SYNC_SERVICE_NAME
    timer_path = SYSTEMD_DIR / PYTHON_SYNC_TIMER_NAME

    write_text(svc_path, _PYTHON_SYNC_SERVICE_TPL.format(cmd=cmd))
    write_text(timer_path, _PYTHON_SYNC_TIMER_CONTENT)

    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", PYTHON_SYNC_TIMER_NAME])

    # Primo sync immediato
    result = run_capture(["systemctl", "start", PYTHON_SYNC_SERVICE_NAME])
    if result.returncode == 0:
        print(f"[OK] checkmk-python-full-sync.timer attivo → deploy ogni 5 min")
    else:
        print(f"[OK] checkmk-python-full-sync.timer attivo → deploy ogni 5 min")
        print(f"[WARN] Primo sync: controllare 'systemctl status {PYTHON_SYNC_SERVICE_NAME}'")

    print(f"     Log:     journalctl -u {PYTHON_SYNC_SERVICE_NAME} -f")
    print(f"     Status:  systemctl status {PYTHON_SYNC_TIMER_NAME}")


def install_python_sync_cron(repo_path: Path, target: str,
                              category: str, all_categories: bool,
                              scripts: str = "", temp_dir: str = "") -> None:
    """Install python full sync via cron."""
    py_bin = shutil.which("python3")
    if not py_bin:
        print("[ERROR] python3 non trovato", file=sys.stderr)
        sys.exit(1)

    sync_script = _find_sync_script(repo_path)

    # Modalità temp: esecuzione one-shot senza installare cron
    if temp_dir:
        print(f"[INFO] Modalità anteprima → esecuzione one-shot")
        cmd_parts = [py_bin, str(sync_script),
                     "--repo", str(repo_path), "--target", target,
                     "--temp-dir", temp_dir]
        if scripts:
            cmd_parts += ["--scripts", scripts]
        else:
            cmd_parts.append("--all-categories")
        result = run_capture(cmd_parts)
        print(result.stdout or "")
        print(f"[OK] Anteprima completata in: {temp_dir}")
        return

    cmd = _build_sync_cmd(py_bin, sync_script, repo_path, target,
                          category, all_categories, scripts, temp_dir)
    cron_line = f"*/5 * * * * {cmd} >> {PYTHON_SYNC_LOG} 2>&1  # {PYTHON_SYNC_CRON_MARKER}"

    cron_update(PYTHON_SYNC_CRON_MARKER, cron_line, openwrt=is_openwrt())
    print(f"[OK] checkmk-python-full-sync installato via cron (ogni 5 min)")
    print(f"     Log:     tail -f {PYTHON_SYNC_LOG}")


# ─── STEP 3: Agent Synchronization (verify-only) ──────────────────────────────────

_AGENT_SYNC_SERVICE_TPL = """\
[Unit]
Description=CheckMK Agent Synchronization Service
Documentation=https://github.com/nethesis/checkmk-tools
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
EnvironmentFile=-/etc/checkmk-agent-sync/checkmk-agent-sync.env
ExecStart=/usr/bin/python3 -B /opt/checkmk-tools/script-tools/full/agent_maintenance/checkmk-agent-autoupdate-linux.py \
  --server-url ${CHECKMK_SERVER_URL} \
  --site ${CHECKMK_SITE} \
  --target auto \
  --verbose

StandardOutput=journal
StandardError=journal
SyslogIdentifier=checkmk-agent-sync

# Non-destructive on failure
FailureAction=none
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target"""





_AGENT_SYNC_TIMER_TPL = """\
[Unit]
Description=CheckMK Agent Synchronization Timer
Documentation=https://github.com/nethesis/checkmk-tools
Requires=checkmk-agent-sync.service

[Timer]
# Run daily at 03:00 AM UTC
OnCalendar=daily

# Randomize by up to 5 minutes to avoid thundering herd
RandomizedDelaySec=5min

# Ensure the service runs even if the system was off at scheduled time
Persistent=yes

# Unit to trigger
Unit=checkmk-agent-sync.service

[Install]
WantedBy=timers.target"""



def install_agent_sync_systemd(server_url: str, site: str, enable_install: bool = False) -> None:
    """Install checkmk-agent-sync as systemd service + timer (verify-only by default).

    enable_install=True adds --install to the ExecStart line, so the timer
    actually upgrades the agent instead of only reporting drift."""
    # Create env directory and env file
    AGENT_SYNC_ENV_DIR.mkdir(parents=True, exist_ok=True)
    env_content = (
        f"# CheckMK Agent Synchronization Configuration\n"
        f"# Installed by install-checkmk-agent-linux.py v{VERSION}\n"
        f"CHECKMK_SERVER_URL={server_url}\n"
        f"CHECKMK_SITE={site}\n"
        f"CHECKMK_TARGET=auto\n"
    )
    write_text(AGENT_SYNC_ENV_FILE, env_content)
    AGENT_SYNC_ENV_FILE.chmod(0o600)

    svc_path = SYSTEMD_DIR / AGENT_SYNC_SERVICE_NAME
    timer_path = SYSTEMD_DIR / AGENT_SYNC_TIMER_NAME

    service_content = _AGENT_SYNC_SERVICE_TPL
    if enable_install:
        service_content = service_content.replace(
            "--target auto   --verbose",
            "--target auto   --install   --verbose",
        )

    write_text(svc_path, service_content)
    write_text(timer_path, _AGENT_SYNC_TIMER_TPL)

    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", AGENT_SYNC_TIMER_NAME])
    mode = "INSTALL (aggiornamento reale)" if enable_install else "VERIFY_ONLY (solo verifica)"
    print(f"[OK] {AGENT_SYNC_TIMER_NAME} attivo (verifica agente ogni giorno alle 03:00 UTC, modalita': {mode})")
    print(f"     Env:    {AGENT_SYNC_ENV_FILE}")
    print(f"     Status: systemctl status {AGENT_SYNC_TIMER_NAME}")


# ─── Add scripts to existing sync ───────────────────────────────────────────────

# ─── Add scripts to existing sync ───────────────────────────────────────────────

def add_scripts_to_sync(new_scripts_arg: str, use_systemd: bool) -> int:
    """Adds scripts to timer/cron list without reinstalling.
    Reads the current configuration, merges, rewrites and reboots."""
    new_set = {s.strip() for s in new_scripts_arg.split(",") if s.strip()}
    if not new_set:
        print("[ERROR] --add-scripts: nessuno script specificato", file=sys.stderr)
        return 1

    if use_systemd:
        svc_path = SYSTEMD_DIR / PYTHON_SYNC_SERVICE_NAME
        if not svc_path.exists():
            print(f"[ERROR] Service non trovato: {svc_path}", file=sys.stderr)
            print("[INFO] Eseguire prima install-checkmk-agent-linux.py senza --add-scripts", file=sys.stderr)
            return 1

        content = svc_path.read_text(encoding="utf-8")

        if "--all-categories" in content:
            print("[INFO] Servizio gia' in modalita' --all-categories.")
            print(f"[INFO] Gli script {sorted(new_set)} verranno deployati automaticamente al prossimo ciclo.")
            return 0

        m = re.search(r'--scripts\s+(\S+)', content)
        if m:
            current = {s.strip() for s in m.group(1).split(",") if s.strip()}
            added = sorted(new_set - current)
            if not added:
                print(f"[INFO] Tutti gli script sono gia' presenti nella lista: {sorted(current)}")
                return 0
            merged = sorted(current | new_set)
            new_scripts_str = ",".join(merged)
            new_content = re.sub(r'--scripts\s+\S+', f'--scripts {new_scripts_str}', content)
            print(f"[INFO] Aggiunti: {added}")
            print(f"[INFO] Lista completa: {merged}")
        else:
            # ExecStart esiste ma senza --scripts (usa --category o --all-categories)
            # Append --scripts to the ExecStart line
            new_scripts_str = ",".join(sorted(new_set))
            new_content = re.sub(
                r'(ExecStart=.+)',
                lambda mm: mm.group(1) + f' --scripts {new_scripts_str}',
                content
            )
            print(f"[INFO] Aggiunto --scripts: {new_scripts_str}")

        svc_path.write_text(new_content, encoding="utf-8")
        run_capture(["systemctl", "daemon-reload"])
        run_capture(["systemctl", "restart", PYTHON_SYNC_TIMER_NAME])
        # Deploy immediato
        result = run_capture(["systemctl", "start", PYTHON_SYNC_SERVICE_NAME])
        if result.returncode == 0:
            print("[OK] Deploy immediato completato.")
        else:
            print("[WARN] Deploy immediato: controlla 'journalctl -u checkmk-python-full-sync -f'")
        print(f"[OK] --add-scripts completato. Timer aggiornato.")

    else:
        # cron (OpenWrt / systems without systemd)
        cron_result = run_capture(["crontab", "-l"] if not is_openwrt() else ["cat", str(OPENWRT_CRONTAB)])
        cron_lines = (cron_result.stdout or "").splitlines()
        updated = False
        for i, line in enumerate(cron_lines):
            if PYTHON_SYNC_CRON_MARKER not in line:
                continue
            if "--all-categories" in line:
                print("[INFO] Cron gia' in modalita' --all-categories. Script verranno deployati automaticamente.")
                return 0
            m = re.search(r'--scripts\s+(\S+)', line)
            if m:
                current = {s.strip() for s in m.group(1).split(",") if s.strip()}
                added = sorted(new_set - current)
                if not added:
                    print(f"[INFO] Script gia' presenti: {sorted(current)}")
                    return 0
                merged = sorted(current | new_set)
                new_scripts_str = ",".join(merged)
                cron_lines[i] = re.sub(r'--scripts\s+\S+', f'--scripts {new_scripts_str}', line)
                print(f"[INFO] Aggiunti: {added}")
                print(f"[INFO] Lista completa: {merged}")
            else:
                new_scripts_str = ",".join(sorted(new_set))
                cron_lines[i] = re.sub(
                    r'(--target\s+\S+)',
                    f'\\1 --scripts {new_scripts_str}',
                    line
                )
                print(f"[INFO] Aggiunto --scripts: {new_scripts_str}")
            updated = True
            break

        if not updated:
            print(f"[ERROR] Marker '{PYTHON_SYNC_CRON_MARKER}' non trovato nel crontab.", file=sys.stderr)
            print("[INFO] Eseguire prima install-checkmk-agent-linux.py senza --add-scripts", file=sys.stderr)
            return 1

        if is_openwrt():
            OPENWRT_CRONTAB.write_text("\n".join(cron_lines) + "\n", encoding="utf-8")
            run_capture(["sh", "-c", "/etc/init.d/cron restart 2>/dev/null || true"])
        else:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".cron", delete=False) as f:
                f.write("\n".join(cron_lines) + "\n")
                tmp = f.name
            run(["crontab", tmp])
            unlink_safe(Path(tmp))
        print("[OK] --add-scripts completato. Cron aggiornato.")

    return 0


# ─── Prompt interattivi ───────────────────────────────────────────────────────

def _ask(prompt: str) -> str:
    """Reads input from /dev/tty if stdin is not a tty (e.g. curl | python3 -).
    Opens /dev/tty in r+w so prompt and response both use the real terminal.
    Fallback to standard input()."""
    import sys
    if not sys.stdin.isatty():
        try:
            with open("/dev/tty", "r+") as tty:
                tty.write(prompt)
                tty.flush()
                return tty.readline().rstrip("\n")
        except OSError:
            # /dev/tty not available: write prompt to stderr and use default
            sys.stderr.write(prompt + " [auto-default]\n")
            sys.stderr.flush()
            return ""
    return input(prompt)

def ask_agent_install() -> bool:
    """Chiede se installare l'agente CheckMK."""
    print()
    print("  STEP A – Installazione CheckMK Agent + FRPC")
    print("  ─────────────────────────────────────────────")
    ans = _ask("  Installare CheckMK Agent (TCP 6556, plain pull + IP allowlist)? [S/n]: ").strip().lower().replace("\r", "") or "s"
    return ans in ("s", "y", "")


def _parse_ip_list(raw: str) -> List[str]:
    """Split a comma/space-separated string into a de-duplicated list of IPs,
    preserving order. Raises ValueError on the first invalid entry."""
    ips: List[str] = []
    for token in re.split(r"[,\s]+", raw.strip()):
        if not token:
            continue
        ipaddress.ip_address(token)  # raises ValueError if malformed
        if token not in ips:
            ips.append(token)
    return ips


def ask_allowed_ips() -> List[str]:
    """Chiede quali IP autorizzare nell'allowlist di cmk-agent-ctl (plain pull).
    Supporta piu' IP separati da virgola o spazio (es. server CheckMK + un
    secondo host di monitoraggio)."""
    print()
    print("  Configurazione IP allowlist (cmk-agent-ctl, plain pull nativo):")
    print("  L'agente accettera' connessioni in chiaro sulla 6556 SOLO da questi IP.")
    print(f"  Usare {DEFAULT_ALLOWED_IPS[0]} se il traffico arriva tramite tunnel FRP locale (caso comune),")
    print("  altrimenti l'IP reale (o piu' IP separati da virgola/spazio) da cui si connette il server CheckMK.")
    while True:
        raw = _ask(f"  IP autorizzati [{DEFAULT_ALLOWED_IPS[0]}]: ").strip().replace("\r", "")
        if not raw:
            return list(DEFAULT_ALLOWED_IPS)
        try:
            ips = _parse_ip_list(raw)
        except ValueError as exc:
            print(f"  [ERR] IP non valido ({exc}), riprova.")
            continue
        if ips:
            return ips
        print("  [ERR] Nessun IP valido inserito, riprova.")


def ask_frpc_install() -> bool:
    """Chiede se installare FRPC."""
    ans = _ask("  Installare FRPC (tunnel verso server CheckMK)? [s/N]: ").strip().lower().replace("\r", "") or "n"
    return ans in ("s", "y")


def ask_frpc_config() -> Tuple[str, str, int, str]:
    """Collects FRPC parameters interactively.

    Returns:
        (hostname, frp_server, remote_port, auth_token)"""
    import socket as _socket
    default_hostname = _socket.gethostname()

    print()
    print("  Configurazione FRPC:")
    hostname = _ask(f"  Nome host [{default_hostname}]: ").strip().replace("\r", "") or default_hostname
    server = _ask("  Remote FRP server: ").strip().replace("\r", "") or os.environ.get("FRP_SERVER", "")

    while True:
        port_raw = _ask("  Porta remota (es: 20001): ").strip().replace("\r", "")
        if port_raw.isdigit():
            remote_port = int(port_raw)
            break
        print("  [ERR] Porta non valida. Inserire un numero.")

    while True:
        token = _ask("  Token FRP (obbligatorio): ").strip().replace("\r", "")
        if token:
            break
        print("  [ERR] Token obbligatorio.")

    return hostname, server, remote_port, token


def ask_interval() -> int:
    print()
    print("  Scegli intervallo git sync:")
    print("  1) Ogni 30 secondi")
    print("  2) Ogni 1 minuto (consigliato)")
    print("  3) Ogni 5 minuti")
    print("  4) Ogni 10 minuti")
    print("  5) Ogni 30 minuti")
    choice = _ask("\n  Scelta [2]: ").strip().replace("\r", "") or "2"
    mapping = {"1": 30, "2": 60, "3": 300, "4": 600, "5": 1800}
    interval = mapping.get(choice, 60)
    print(f"[OK] Intervallo: {interval}s")
    return interval


def ask_category(repo_path: Path) -> Tuple[str, bool]:
    categories = sorted([
        d.name for d in repo_path.iterdir()
        if d.is_dir() and d.name.startswith("script-check-")
    ])
    if not categories:
        return "auto", False

    print()
    print("  Scegli categoria da deployare:")
    print("  0) Tutte le categorie")
    for i, cat in enumerate(categories, 1):
        print(f"  {i}) {cat}")
    print("  a) Auto-detect (consigliato)")

    choice = _ask("\n  Scelta [a]: ").strip().lower().replace("\r", "") or "a"

    if choice == "0":
        return "auto", True
    if choice == "a":
        return "auto", False
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(categories):
            return categories[idx], False
    except ValueError:
        pass
    return "auto", False


def ask_scripts(repo_path: Path) -> Tuple[str, bool, str]:
    """Interactive script selection and deployment mode.

    Step 1 → choose category (OS)
    Step 2 → choose script within the category
    Step 3 → deploy mode (real/preview)

    Returns:
        (scripts_csv, all_categories, temp_dir)
        scripts_csv: string "name1,name2,..." or "" (all categories)
        all_categories: True if the user chose all (no filters)
        temp_dir: path temp if preview, otherwise """""
    # ── Passo 1: Selezione categoria (OS) ────────────────────────────────────
    categories = sorted([
        d.name for d in repo_path.iterdir()
        if d.is_dir() and d.name.startswith("script-check-")
    ])

    print()
    print("  ── Passo 1: Categoria (sistema operativo) ─────────")
    print(f"  {'#':<4} {'Categoria':<35} OS")
    print("  ─" * 30)
    print(f"  {'0':<4} {'(tutte le categorie)':35} -")
    for i, cat in enumerate(categories, 1):
        label = cat.replace("script-check-", "").upper()
        print(f"  {i:<4} {cat:<35} {label}")
    print()

    cat_raw = _ask("  Categoria [0 = tutte]: ").strip().replace("\r", "") or "0"

    filter_cat: Optional[str] = None
    if cat_raw != "0" and cat_raw != "":
        try:
            idx = int(cat_raw) - 1
            if 0 <= idx < len(categories):
                filter_cat = categories[idx]
                print(f"  → {filter_cat}")
        except ValueError:
            pass
    if filter_cat is None:
        print("  → Tutte le categorie")

    # ── Passo 2: Raccolta launcher dalla categoria selezionata ───────────────
    selected_cats = [filter_cat] if filter_cat else categories
    all_launchers: List[Tuple[str, str]] = []  # (stem, categoria)
    for cat_name in selected_cats:
        full_dir = repo_path / cat_name / "full"
        if full_dir.is_dir():
            for launcher in sorted(f for f in full_dir.glob("*.py") if f.stem.startswith("check")):
                all_launchers.append((launcher.stem, cat_name))

    if not all_launchers:
        print("[WARN] Nessuno script trovato nella categoria selezionata.")
        return "", (filter_cat is None), ""

    print()
    print("  ── Passo 2: Selezione script ───────────────────────")
    print(f"  {'#':<4} {'Nome script':<45} Categoria")
    print("  ─" * 35)
    for i, (stem, cat) in enumerate(all_launchers, 1):
        print(f"  {i:<4} {stem:<45} {cat}")
    print()
    print("  Seleziona script da deployare:")
    print("  - Numeri separati da virgola/spazio: es. 1,3,5  oppure  1 3 5")
    print("  - Intervalli: es. 1-5")
    print("  - 0 o invio = tutti quelli elencati sopra")
    print()

    raw = _ask("  Scelta [0 = tutti]: ").strip().replace("\r", "") or "0"

    selected_indices: List[int] = []
    if raw == "0" or raw == "":
        selected_indices = list(range(len(all_launchers)))
    else:
        tokens = raw.replace(",", " ").split()
        for token in tokens:
            if "-" in token and not token.startswith("-"):
                parts = token.split("-", 1)
                try:
                    start, end = int(parts[0]), int(parts[1])
                    selected_indices.extend(range(start - 1, end))
                except ValueError:
                    pass
            else:
                try:
                    selected_indices.append(int(token) - 1)
                except ValueError:
                    pass
        selected_indices = sorted(set(
            i for i in selected_indices if 0 <= i < len(all_launchers)
        ))

    scripts_csv = ""
    all_cat = False
    if not selected_indices or selected_indices == list(range(len(all_launchers))):
        if filter_cat is None:
            # No OS filters AND all scripts → all_categories=True
            all_cat = True
            print(f"  → Tutti gli script di tutte le categorie ({len(all_launchers)} script)")
        else:
            # Specific category, all its scripts → pass explicit list
            chosen = [all_launchers[i][0] for i in range(len(all_launchers))]
            scripts_csv = ",".join(chosen)
            print(f"  → Tutti i {len(chosen)} script di {filter_cat}")
    else:
        chosen = [all_launchers[i][0] for i in selected_indices]
        scripts_csv = ",".join(chosen)
        print(f"  → Selezionati {len(chosen)} script: {scripts_csv}")

    # ── Passo 3: Modalità deploy ─────────────────────────────────────────────
    print()
    print("  ── Passo 3: Modalità deploy ────────────────────────")
    print("  1) Deploy reale → /usr/lib/check_mk_agent/local/ (default)")
    print("  2) Anteprima temp → /tmp/checkmk-sync-preview/ (nessun deploy reale)")
    mode = _ask("\n  Scelta [1]: ").strip().replace("\r", "") or "1"

    temp_dir = ""
    if mode == "2":
        temp_dir = "/tmp/checkmk-sync-preview"
        print(f"  → Anteprima in: {temp_dir}")
    else:
        print("  → Deploy reale")

    return scripts_csv, all_cat, temp_dir


# ─── Argomenti CLI ────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=f"install-checkmk-agent-linux.py v{VERSION} - Installer unificato Agent + git-sync + deploy check Python",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Full interactive installation (recommended)
  python3 install-checkmk-agent-linux.py

  # Quick mode (all defaults, also install agents)
  python3 install-checkmk-agent-linux.py --quick

  # Sync only (skip agent installation)
  python3 install-checkmk-agent-linux.py --skip-agent

  # Uninstall everything
  python3 install-checkmk-agent-linux.py --uninstall

  # Uninstall FRPC only
  python3 install-checkmk-agent-linux.py --uninstall-frpc

  # With specific category and custom git range
  python3 install-checkmk-agent-linux.py --category script-check-ubuntu --git-interval 60""",
    )
    # Repository e target
    p.add_argument("--repo", default=str(REPO_DEFAULT_PATH),
                   help=f"Path repository locale (default: {REPO_DEFAULT_PATH})")
    p.add_argument("--repo-url", default=REPO_URL_DEFAULT,
                   help="URL repository git (usato solo se repo non esiste)")
    p.add_argument("--target", default=LOCAL_TARGET_DEFAULT,
                   help=f"Path local checks target (default: {LOCAL_TARGET_DEFAULT})")

    # Sync check Python
    p.add_argument("--category", default="auto",
                   help="Categoria script-check-* o 'auto' (default: auto)")
    p.add_argument("--all-categories", action="store_true",
                   help="Sincronizza tutte le categorie script-check-*")
    p.add_argument("--scripts", default="",
                   help="Script specifici da deployare (nomi separati da virgola, senza .py)")
    p.add_argument("--temp", action="store_true",
                   help="Deploy in /tmp/checkmk-sync-preview/ invece di --target (anteprima)")
    p.add_argument("--git-interval", type=int, default=None,
                   help="Intervallo git pull in secondi (default: chiesto interattivamente)")
    p.add_argument("--quick", action="store_true",
                   help="Modalità non-interattiva: usa tutti i default senza domande")

    # Agent CheckMK
    p.add_argument("--skip-agent", action="store_true",
                   help="Salta l'installazione dell'agente CheckMK (STEP A)")
    p.add_argument("--skip-agent-sync", action="store_true",
                   help="Salta l'installazione del timer checkmk-agent-sync (STEP 3)")
    p.add_argument("--checkmk-url", default=CHECKMK_BASE_URL_DEFAULT,
                   help=f"URL base agenti CheckMK (default: {CHECKMK_BASE_URL_DEFAULT})")
    p.add_argument("--allowed-ip", default="",
                   help="IP autorizzati nell'allowlist cmk-agent-ctl per il plain pull, "
                        "separati da virgola per piu' di un IP (default: chiesto "
                        f"interattivamente, fallback {DEFAULT_ALLOWED_IPS[0]} in --quick)")
    p.add_argument("--checkmk-server-url", default="https://monitor.nethlab.it",
                   help="URL server CheckMK per agent-sync (default: https://monitor.nethlab.it)")
    p.add_argument("--checkmk-site", default="monitoring",
                   help="Nome sito CheckMK per agent-sync (default: monitoring)")
    p.add_argument("--agent-sync-install", action="store_true",
                   help="Abilita l'aggiornamento reale dell'agente nel timer checkmk-agent-sync "
                        "(aggiunge --install all'ExecStart, invece del default verify-only)")
    p.add_argument("--no-verify-ssl", action="store_true",
                   help="Disabilita verifica certificato SSL (utile per HTTPS con cert self-signed)")

    # FRPC
    p.add_argument("--install-frpc", action="store_true",
                   help="Forza installazione FRPC (default: chiesto interattivamente)")
    p.add_argument("--frp-version", default=FRP_VERSION_DEFAULT,
                   help=f"Versione FRPC da scaricare (default: {FRP_VERSION_DEFAULT})")
    p.add_argument("--frpc-server", default="",
                   help="Hostname server FRP (default: chiesto interattivamente)")
    p.add_argument("--frpc-port", type=int, default=0,
                   help="Porta remota FRP (default: chiesta interattivamente)")
    p.add_argument("--frpc-token", default="",
                   help="Token autenticazione FRP (default: chiesto interattivamente)")
    p.add_argument("--frpc-hostname", default="",
                   help="Nome host nel tunnel FRP (default: hostname locale)")

    # Uninstall
    p.add_argument("--uninstall-frpc", action="store_true",
                   help="Disinstalla solo FRPC ed esce")
    p.add_argument("--uninstall-agent", action="store_true",
                   help="Disinstalla solo agente CheckMK ed esce")
    p.add_argument("--uninstall", action="store_true",
                   help="Disinstalla agente + FRPC ed esce")

    # Added post-installation script
    p.add_argument("--add-scripts", default="", metavar="SCRIPT1,SCRIPT2",
                   help="Aggiunge script al timer/cron senza reinstallare (es: check_arp_watch,check_disk_space)")

    return p.parse_args()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    args = parse_args()
    require_root()

    global SSL_VERIFY
    if args.no_verify_ssl:
        SSL_VERIFY = False
        print("[WARN] Verifica SSL disabilitata (--no-verify-ssl)")

    repo_path = Path(args.repo)
    openwrt = is_openwrt()
    use_systemd = has_systemd() and not openwrt

    # ── Header ───────────────────────────────────────────────────────────────
    print("=" * 60)
    print(f"  install-checkmk-agent-linux.py v{VERSION}")
    print("  Installer unificato CheckMK (Agent + Auto-Sync + Deploy)")
    print("=" * 60)
    print()
    print(f"  Sistema:    {'systemd' if use_systemd else 'cron (OpenWrt/non-systemd)'}")
    print(f"  Repository: {repo_path}")
    print(f"  Target:     {args.target}")
    print()

    # ── Uninstall shortcuts ───────────────────────────────────────────────────
    if args.uninstall or args.uninstall_agent or args.uninstall_frpc:
        os_info = detect_os_info()
        if args.uninstall or args.uninstall_frpc:
            uninstall_frpc(os_info)
        if args.uninstall or args.uninstall_agent:
            uninstall_agent(os_info)
        print("[OK] Disinstallazione completata")
        return 0

    # ── Add scripts shortcut ──────────────────────────────────────────────────
    if args.add_scripts:
        return add_scripts_to_sync(args.add_scripts, use_systemd)

    # ── STEP 0: Prerequisiti ─────────────────────────────────────────────────
    print("── STEP 0: Prerequisiti ──────────────────────────────")
    pkg_mgr = detect_pkg_manager()
    ensure_git(pkg_mgr)
    ensure_repo(repo_path, args.repo_url)
    update_repo(repo_path)
    owner = get_repo_owner(repo_path)
    print(f"[OK] Owner repository: {owner}")

    # ── STEP A: CheckMK Agent + FRPC ─────────────────────────────────────────
    print()
    print("── STEP A: CheckMK Agent + FRPC ──────────────────────")

    agent_installed = False
    frpc_installed = False

    skip_agent = args.skip_agent
    if not skip_agent and not args.quick:
        skip_agent = not ask_agent_install()

    if not skip_agent:
        os_info = detect_os_info()
        if args.allowed_ip:
            try:
                allowed_ips = _parse_ip_list(args.allowed_ip)
            except ValueError as exc:
                print(f"[ERR] --allowed-ip non valido: {exc}", file=sys.stderr)
                return 1
            if not allowed_ips:
                print("[ERR] --allowed-ip non contiene nessun IP valido", file=sys.stderr)
                return 1
        elif args.quick:
            allowed_ips = list(DEFAULT_ALLOWED_IPS)
        else:
            allowed_ips = ask_allowed_ips()
        try:
            install_agent(args.checkmk_url, os_info)
            configure_agent(os_info, allowed_ips)
            agent_installed = True
            if os_info["pkg_type"] == "openwrt":
                print("[OK] CheckMK Agent installato (127.0.0.1:6556)")
            else:
                print(f"[OK] CheckMK Agent installato (porta 6556, plain pull, allowed_ip={allowed_ips})")
        except Exception as exc:
            print(f"[ERR] Installazione agente fallita: {exc}", file=sys.stderr)
            print("[WARN] Continuando con STEP 1 e STEP 2...", file=sys.stderr)
    else:
        os_info = detect_os_info()
        print("[INFO] STEP A saltato (--skip-agent)")

    # FRPC (only if agent installed or forced by flag)
    do_frpc = args.install_frpc
    if not skip_agent and not do_frpc and not args.quick:
        do_frpc = ask_frpc_install()

    if do_frpc:
        try:
            install_frpc(args.frp_version)
            # Raccoglie parametri FRPC
            if args.frpc_server and args.frpc_port and args.frpc_token:
                import socket as _socket
                hostname = args.frpc_hostname or _socket.gethostname()
                server = args.frpc_server
                remote_port = args.frpc_port
                auth_token = args.frpc_token
            elif args.quick:
                print("[WARN] FRPC richiede --frpc-server, --frpc-port, --frpc-token in modalità --quick. Saltato.")
                do_frpc = False
            else:
                hostname, server, remote_port, auth_token = ask_frpc_config()

            if do_frpc:
                configure_frpc(hostname, server, remote_port, auth_token, os_info)
                frpc_installed = True
        except Exception as exc:
            print(f"[ERR] Installazione FRPC fallita: {exc}", file=sys.stderr)
            print("[WARN] Continuando con STEP 1 e STEP 2...", file=sys.stderr)

    # ── STEP 1: Auto Git Sync ─────────────────────────────────────────────────
    print()
    print("── STEP 1: Auto Git Sync ─────────────────────────────")

    if args.quick or args.git_interval is not None:
        interval = args.git_interval or 60
    else:
        interval = ask_interval()

    if use_systemd:
        install_git_sync_systemd(repo_path, interval, owner)
    else:
        install_git_sync_cron(repo_path)

    # ── STEP 2: Python Full Sync ──────────────────────────────────────────────
    print()
    print("── STEP 2: Python Full Sync (deploy local checks) ────")

    scripts = args.scripts
    temp_dir = "/tmp/checkmk-sync-preview" if args.temp else ""

    if args.quick:
        category = args.category
        all_cat = args.all_categories
    else:
        # Modalità interattiva: selezione granulare
        if not scripts and not args.all_categories:
            scripts, all_cat, temp_dir = ask_scripts(repo_path)
            category = args.category
        else:
            category = args.category
            all_cat = args.all_categories

    if scripts:
        print(f"[INFO] Script selezionati: {scripts}")
    else:
        print(f"[INFO] Categoria: {'TUTTE' if all_cat else category}")
    if temp_dir:
        print(f"[INFO] Modalità: ANTEPRIMA → {temp_dir}")

    if use_systemd:
        install_python_sync_systemd(repo_path, args.target, category, all_cat,
                                    scripts=scripts, temp_dir=temp_dir)
    else:
        install_python_sync_cron(repo_path, args.target, category, all_cat,
                                 scripts=scripts, temp_dir=temp_dir)

    # ── STEP 3: CheckMK Agent Sync (verify-only) ────────────────────────────
    print()
    print("── STEP 3: CheckMK Agent Sync (verify-only) ────────")
    if args.skip_agent_sync:
        print("[INFO] STEP 3 saltato (--skip-agent-sync)")
    elif use_systemd:
        try:
            install_agent_sync_systemd(args.checkmk_server_url, args.checkmk_site, args.agent_sync_install)
        except Exception as exc:
            print(f"[WARN] STEP 3 (agent sync) fallito: {exc}", file=sys.stderr)
            print("[WARN] Il sistema continuera' senza agent-sync timer. Puoi installarlo manualmente.", file=sys.stderr)
    else:
        print("[INFO] STEP 3 saltato: sistema non-systemd (agent-sync richiede systemd)")
    # ── Riepilogo finale ──────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  Installazione Completata!")
    print("=" * 60)
    print()

    if agent_installed:
        if os_info["pkg_type"] == "openwrt":
            print(f"   CheckMK Agent         (127.0.0.1:6556, procd + socat)")
        else:
            print(f"   CheckMK Agent         (porta 6556, plain pull nativo, allowed_ip={allowed_ips})")
    if frpc_installed:
        print(f"   FRPC                  (tunnel verso server FRP)")

    if use_systemd:
        print(f"   auto-git-sync.timer          (git pull ogni {interval}s)")
        print(f"   checkmk-python-full-sync.timer (deploy ogni 5min)")
        print(f"   checkmk-agent-sync.timer      (verifica agente ogni giorno alle 03:00 UTC)")
        print()
        print("  Comandi utili:")
        if agent_installed:
            print(f"  cmk-agent-ctl status")
            print(f"  systemctl status {CMK_AGENT_CTL_DAEMON_NAME}")
        if frpc_installed:
            print("  systemctl status frpc")
        print(f"  systemctl status {GIT_SYNC_TIMER_NAME}")
        print(f"  systemctl status {PYTHON_SYNC_TIMER_NAME}")
        print(f"  journalctl -u auto-git-sync -f")
        print(f"  journalctl -u checkmk-python-full-sync -f")
        print(f"  journalctl -u checkmk-agent-sync -f")
    else:
        print(f"   git-auto-sync      (ogni minuto)")
        print(f"   python-full-sync   (ogni 5 minuti)")
        print()
        print("  Verifica: crontab -l")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
