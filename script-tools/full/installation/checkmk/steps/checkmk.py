from __future__ import annotations

import re
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path

from lib.common import command_exists, log_header, log_info, log_success, log_warn, run as run_cmd, run_capture, run_stdin
from lib.config import InstallerConfig


def _parse_version_tuple(version: str) -> tuple[int, int, int, int]:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)p(\d+)", version.strip())
    if not m:
        raise ValueError(f"Invalid CheckMK version: {version}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))


def _pkg_prefix_for_version(version: str) -> str:
    """CheckMK renamed the Raw Edition package starting with 2.5.0:
    2.4.x and earlier -> check-mk-raw-X.Y.ZpN
    2.5.0 and later   -> check-mk-community-X.Y.ZpN
    Mirrors the same rule already used by upgrade_maintenance/upgrade_checkmk.py."""
    major, minor, _patch, _p = _parse_version_tuple(version)
    return "check-mk-community" if (major, minor) >= (2, 5) else "check-mk-raw"


def _detect_latest_version(timeout_sec: int = 20) -> tuple[str, str]:
    """Return (version, pkg_prefix) of the latest stable CheckMK release, detected from the
    public marketing page (same source and parsing strategy as upgrade_checkmk.py):
      - Raw Edition (<=2.4.x): filename 'check-mk-raw-X.Y.ZpN' appears directly in page HTML
      - Community Edition (>=2.5.0): data-edition="community" data-version="X.Y.ZpN" attributes
    """
    url = "https://checkmk.com/download"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; checkmk-tools-installer/1.0; +https://github.com/nethesis/checkmk-tools)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    raw_versions = set(re.findall(r"check-mk-raw-(\d+\.\d+\.\d+p\d+)", html))
    community_versions = set(
        re.findall(r'data-edition=["\']community["\'][^>]*?data-version=["\'](\d+\.\d+\.\d+p\d+)["\']', html)
    )

    best_version: str | None = None
    best_prefix: str | None = None
    for v in raw_versions:
        if best_version is None or _parse_version_tuple(v) > _parse_version_tuple(best_version):
            best_version, best_prefix = v, "check-mk-raw"
    for v in community_versions:
        if best_version is None or _parse_version_tuple(v) > _parse_version_tuple(best_version):
            best_version, best_prefix = v, "check-mk-community"

    if not best_version or not best_prefix:
        raise RuntimeError("Could not detect any versions from download page")
    return best_version, best_prefix


def _probe_url_ok(url: str, timeout_sec: int = 20) -> bool:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; checkmk-tools-installer/1.0; +https://github.com/nethesis/checkmk-tools)",
            "Accept": "application/octet-stream,*/*",
            "Range": "bytes=0-0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            status = getattr(resp, "status", None)
            return status in {200, 206}
    except urllib.error.HTTPError:
        return False
    except Exception:
        return False


def _derive_latest_from_seed_url(seed_url: str, *, codename: str, arch: str, timeout_sec: int = 20) -> str:
    """Given a known-good deb URL, probe newer patch versions and return the latest reachable URL.

    Handles both package name prefixes (check-mk-raw- for <=2.4.x, check-mk-community- for
    >=2.5.0): whichever prefix appears in the seed URL is the one reused for every probed URL,
    so a 2.5.x+ seed keeps probing check-mk-community- patches instead of a nonexistent
    check-mk-raw- filename."""

    # Extract base '/checkmk' prefix
    if "/checkmk/" not in seed_url:
        return seed_url

    prefix, tail = seed_url.split("/checkmk/", 1)
    base = prefix.rstrip("/") + "/checkmk"

    m = re.search(r"(check-mk-raw|check-mk-community)-(\d+\.\d+\.\d+)p(\d+)_0\.[a-z0-9]+_[^/]+\.deb", seed_url)
    if not m:
        return seed_url

    pkg_prefix = m.group(1)
    series = m.group(2)
    seed_patch = int(m.group(3))

    last_ok = seed_patch
    consecutive_fail = 0

    # Probe forward from the seed patch; stop after a few consecutive misses.
    for patch in range(seed_patch, seed_patch + 50):
        ver = f"{series}p{patch}"
        url = f"{base}/{ver}/{pkg_prefix}-{ver}_0.{codename}_{arch}.deb"
        if _probe_url_ok(url, timeout_sec=timeout_sec):
            last_ok = patch
            consecutive_fail = 0
        else:
            consecutive_fail += 1
            if patch > seed_patch and consecutive_fail >= 3:
                break

    ver = f"{series}p{last_ok}"
    return f"{base}/{ver}/{pkg_prefix}-{ver}_0.{codename}_{arch}.deb"


def run_step(cfg: InstallerConfig) -> None:
    log_header("60-CHECKMK")
    log_info("Installing CheckMK...")

    url = cfg.checkmk_deb_url.strip()

    # Support local file paths (or file://) so users can pre-stage a .deb on the host.
    if url.startswith("file://"):
        url = url[len("file://") :]

    codename = run_capture(["lsb_release", "-cs"], check=False) or "jammy"
    arch = run_capture(["dpkg", "--print-architecture"], check=False) or "amd64"

    if url.startswith("/"):
        deb_path = Path(url)
        if not deb_path.is_file():
            raise RuntimeError(f"Local CheckMK .deb not found: {deb_path}")
        log_info(f"Using local .deb: {deb_path}")
        # apt-get install accepts a local .deb path directly, resolves missing
        # dependencies same as gdebi -n did - and unlike gdebi, run() injects
        # Dpkg::Progress-Fancy=1 for a real percentage progress bar.
        run_cmd(["apt-get", "install", "-y", str(deb_path)])
    else:
        cmk_version = (cfg.cmk_version or "").strip()

        # If user provided a URL and asked for latest, use it as a seed and probe forward.
        if url and cmk_version.lower() in {"latest", ""}:
            derived = _derive_latest_from_seed_url(url, codename=codename, arch=arch)
            if derived != url:
                log_info(f"Derived latest URL from seed: {derived}")
            url = derived

        if not url:
            cmk_version = (cfg.cmk_version or "").strip()
            pkg_prefix = "check-mk-raw"
            if cmk_version.lower() in {"latest", ""}:
                log_info("CMK_VERSION=latest: detecting latest available version...")
                try:
                    cmk_version, pkg_prefix = _detect_latest_version()
                    log_info(f"Detected: {cmk_version} ({pkg_prefix})")
                except Exception as exc:
                    # Detection page unreachable (network/auth issue) - fall back to probing from a known seed.
                    log_warn(f"Could not auto-detect version from download page: {exc}")
                    log_warn("Falling back to automatic probe from known seed URL (2.4.0p20)...")
                    seed_url = (
                        f"https://download.checkmk.com/checkmk/2.4.0p20"
                        f"/check-mk-raw-2.4.0p20_0.{codename}_{arch}.deb"
                    )
                    derived = _derive_latest_from_seed_url(seed_url, codename=codename, arch=arch)
                    log_info(f"Auto-detected latest URL: {derived}")
                    url = derived
            else:
                pkg_prefix = _pkg_prefix_for_version(cmk_version)

            if not url:
                url = f"https://download.checkmk.com/checkmk/{cmk_version}/{pkg_prefix}-{cmk_version}_0.{codename}_{arch}.deb"
                log_info(f"Using derived URL: {url}")

        deb_path = Path("/tmp") / Path(url).name
        run_cmd(["wget", "-O", str(deb_path), url])
        # apt-get install accepts a local .deb path directly, resolves missing
        # dependencies same as gdebi -n did - and unlike gdebi, run() injects
        # Dpkg::Progress-Fancy=1 for a real percentage progress bar.
        run_cmd(["apt-get", "install", "-y", str(deb_path)])

    if not command_exists("omd"):
        raise RuntimeError("omd command not found after installation")

    sites_output = run_capture(["omd", "sites"], check=False)
    if cfg.site_name not in sites_output:
        # Cleans orphaned unix user/group (left from previous partial run)
        import subprocess as _sp
        _grp = _sp.run(["getent", "group", cfg.site_name], capture_output=True)
        if _grp.returncode == 0:
            log_warn(f"Gruppo unix '{cfg.site_name}' orfano trovato (site non esiste). Rimozione...")
            run_cmd(["userdel", cfg.site_name], check=False)
            run_cmd(["groupdel", cfg.site_name], check=False)
        run_cmd(["omd", "create", cfg.site_name])
    run_cmd(["omd", "start", cfg.site_name], check=False)

    if cfg.checkmk_admin_password:
        log_info("Setting cmkadmin password (value not shown)...")
        run_stdin(
            ["omd", "su", cfg.site_name, "-c", "htpasswd -i ~/etc/htpasswd cmkadmin"],
            f"{cfg.checkmk_admin_password}\n",
            check=False,
        )

    ip = run_capture(["bash", "-lc", "hostname -I | awk '{print $1}'"], check=False)
    log_success("CheckMK installed")
    log_info(f"Site: {cfg.site_name}")
    log_info(f"URL: http://{ip}/{cfg.site_name}")


def run(cfg: InstallerConfig) -> None:
    run_step(cfg)
