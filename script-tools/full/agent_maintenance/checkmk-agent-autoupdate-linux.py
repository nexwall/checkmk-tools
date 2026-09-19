#!/usr/bin/env python3
"""CheckMK Agent Synchronization Tool

Synchronizes the local CheckMK agent version with the version available on the
configured CheckMK server. Supports multiple target types and provides detailed
status reporting with dry-run capability.

Supported targets:
  - Debian/Ubuntu (dpkg)
  - RHEL/Rocky/Alma/CentOS (rpm)
  - NethSecurity 8 (opkg)
  - NS8 container (detect-only)

Usage:
  # Verify current status only (default, non-destructive)
  python3 checkmk-agent-autoupdate-linux.py --server-url https://monitoring.nethlab.it --site monitoring

  # Dry-run: show what would happen
  python3 checkmk-agent-autoupdate-linux.py --dry-run --server-url https://monitoring.nethlab.it --site monitoring

  # Download only
  python3 checkmk-agent-autoupdate-linux.py --download-only --server-url https://monitoring.nethlab.it --site monitoring

  # Install if newer (destructive, requires confirmation)
  python3 checkmk-agent-autoupdate-linux.py --install --server-url https://monitoring.nethlab.it --site monitoring

Version: 1.0.0
"""

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
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

SCRIPT_VERSION = "1.0.0"


class StatusReport:
    """Structured status output."""

    def __init__(self):
        import datetime as dt
        utc_time = dt.datetime.fromtimestamp(time.time(), tz=dt.timezone.utc)
        self.fields: Dict[str, Any] = {
            "SCRIPT_VERSION": SCRIPT_VERSION,
            "TIMESTAMP": utc_time.isoformat().replace("+00:00", "Z"),
            "MODE": None,
            "DRY_RUN": False,
            "TARGET_VARIANT": None,
            "TARGET_DETECTION_REASON": None,
            "CHECKMK_SERVER_URL": None,
            "CHECKMK_SITE": None,
            "REMOTE_AGENT_PACKAGE_URL": None,
            "LOCAL_PACKAGE_PATH": None,
            "REMOTE_PACKAGE_VERSION": None,
            "INSTALLED_VERSION_BEFORE": None,
            "INSTALLED_VERSION_AFTER": None,
            "ACTION": None,
            "FINAL_STATUS": None,
            "ERROR_MESSAGE": None,
            "VERBOSE_NOTES": [],
        }

    def set(self, key: str, value: Any) -> None:
        """Set a status field."""
        if key in self.fields:
            self.fields[key] = value
        else:
            self.fields[key] = value

    def add_note(self, note: str) -> None:
        """Add a verbose note."""
        self.fields["VERBOSE_NOTES"].append(note)

    def output_json(self) -> str:
        """Return JSON representation."""
        return json.dumps(self.fields, indent=2, default=str)

    def output_text(self) -> str:
        """Return human-readable text representation."""
        lines = []
        lines.append("=" * 70)
        lines.append(f"CheckMK Agent Synchronization Report")
        lines.append("=" * 70)
        for key, value in self.fields.items():
            if key != "VERBOSE_NOTES":
                lines.append(f"{key:.<40} {value}")
        if self.fields.get("VERBOSE_NOTES"):
            lines.append("")
            lines.append("NOTES:")
            for note in self.fields["VERBOSE_NOTES"]:
                lines.append(f"  • {note}")
        lines.append("=" * 70)
        return "\n".join(lines)


def detect_target_type() -> Tuple[str, str]:
    """Detect the local system target type.

    Returns:
        Tuple (target_type, detection_reason)
        target_type: 'deb', 'rpm', 'nethsecurity8', 'ns8-container', or 'unknown'
    """
    # Check for NS8 container (read-only detection)
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        if Path("/etc/nethserver").exists():
            return "ns8-container", "Docker/Podman container with NethServer indicators"

    # Check for NethSecurity 8 (OpenWrt-based)
    if Path("/etc/openwrt_release").exists():
        try:
            with open("/etc/openwrt_release", "r") as f:
                content = f.read()
                if "NethSecurity" in content or "nethsecurity" in content.lower():
                    return "nethsecurity8", "/etc/openwrt_release contains NethSecurity"
        except IOError:
            pass

    # Check for standard package managers
    if shutil.which("dpkg"):
        return "deb", "dpkg found in PATH"

    if shutil.which("rpm"):
        return "rpm", "rpm found in PATH"

    if shutil.which("opkg"):
        return "nethsecurity8", "opkg found in PATH"

    return "unknown", "No recognized package manager detected"


def get_os_variant() -> str:
    """Get human-readable OS variant."""
    try:
        with open("/etc/os-release", "r") as f:
            for line in f:
                if line.startswith("NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except IOError:
        pass
    return "Unknown"


def get_local_agent_version(target_type: str) -> Optional[str]:
    """Get the version of the locally installed CheckMK agent.

    Args:
        target_type: 'deb', 'rpm', 'nethsecurity8', 'ns8-container'

    Returns:
        Version string (e.g. '2.4.0p23') or None if not installed.
    """
    if target_type == "deb":
        try:
            out = subprocess.check_output(
                ["dpkg-query", "-W", "-f=${Version}", "check-mk-agent"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            return out.split("-")[0] if out else None
        except subprocess.CalledProcessError:
            return None

    if target_type == "rpm":
        try:
            out = subprocess.check_output(
                ["rpm", "-q", "--queryformat", "%{VERSION}", "check-mk-agent"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            return out if out and "not installed" not in out else None
        except subprocess.CalledProcessError:
            return None

    if target_type == "nethsecurity8":
        try:
            out = subprocess.check_output(
                ["opkg", "list-installed", "check-mk-agent"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            if out:
                # Format: check-mk-agent - 2.4.0p23-1
                parts = out.split(" - ")
                if len(parts) >= 2:
                    version_str = parts[1].split("-")[0]
                    return version_str if version_str else None
            return None
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

    if target_type == "ns8-container":
        # NS8 containers: read-only detection, no installation
        return None

    return None


def get_server_agent_version(server_url: str, site: str) -> Optional[str]:
    """Query the CheckMK server for the available agent version.

    Tries multiple strategies:
    1. Local OMD symlink reading (if running on CheckMK server)
    2. REST API /check_mk/api/1.0/version
    3. HTML scraping of /check_mk/agents/

    Args:
        server_url: Base server URL (e.g. https://monitoring.nethlab.it)
        site: Site name (e.g. monitoring)

    Returns:
        Version string or None if unreachable.
    """
    base_url = f"{server_url.rstrip('/')}/{site}"

    # Strategy 1: Local OMD symlink (if running on CheckMK server)
    version_link = Path(f"/omd/sites/{site}/version")
    if version_link.is_symlink():
        try:
            target = version_link.resolve().name
            m = re.match(r"(\d+\.\d+\.\d+(?:p\d+)?)", target)
            if m:
                return m.group(1)
        except (OSError, AttributeError):
            pass

    # Strategy 2: REST API
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    api_url = f"{base_url}/check_mk/api/1.0/version"
    try:
        req = urllib.request.Request(api_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as resp:
            data = json.loads(resp.read().decode())
            ver = data.get("version", "")
            if ver:
                m = re.match(r"(\d+\.\d+\.\d+(?:p\d+)?)", ver)
                return m.group(1) if m else None
    except Exception:
        pass

    # Strategy 3: HTML scraping
    agents_url = f"{base_url}/check_mk/agents/"
    try:
        with urllib.request.urlopen(agents_url, timeout=10, context=ssl_ctx) as resp:
            html = resp.read().decode(errors="replace")
        pattern = r"check-mk-agent[_-](\d+\.\d+\.\d+p\d+)"
        m = re.search(pattern, html)
        if m:
            return m.group(1)
    except Exception:
        pass

    return None


def build_download_url(
    server_url: str, site: str, version: str, target_type: str
) -> Tuple[str, str]:
    """Build the download URL and filename for the agent package.

    Args:
        server_url: Base server URL
        site: Site name
        version: Agent version (e.g. '2.4.0p23')
        target_type: 'deb', 'rpm', 'nethsecurity8'

    Returns:
        Tuple (full_url, filename)
    """
    base_url = f"{server_url.rstrip('/')}/{site}/check_mk/agents/"

    if target_type in ("deb", "nethsecurity8"):
        filename = f"check-mk-agent_{version}-1_all.deb"
    elif target_type == "rpm":
        filename = f"check-mk-agent-{version}-1.noarch.rpm"
    else:
        raise ValueError(f"Unsupported target type: {target_type}")

    return f"{base_url}{filename}", filename


def download_agent(
    url: str, dest_path: Path, verbose: bool = False
) -> bool:
    """Download the agent package.

    Args:
        url: Full download URL
        dest_path: Destination file path
        verbose: Enable verbose output

    Returns:
        True if successful, False otherwise.
    """
    try:
        if verbose:
            print(f"[INFO] Downloading from: {url}")
        urllib.request.urlretrieve(url, str(dest_path))
        if verbose:
            print(f"[OK] Downloaded to: {dest_path}")
        return True
    except Exception as e:
        print(f"[ERROR] Download failed: {e}", file=sys.stderr)
        return False


def install_agent_deb(pkg_path: Path, dry_run: bool = False, verbose: bool = False) -> bool:
    """Install .deb package.

    Args:
        pkg_path: Path to .deb file
        dry_run: If True, don't actually install
        verbose: Enable verbose output

    Returns:
        True if successful, False otherwise.
    """
    if dry_run:
        if verbose:
            print(f"[DRY-RUN] Would install: dpkg -i {pkg_path}")
        return True

    if verbose:
        print(f"[INFO] Installing: {pkg_path.name}")

    ret = subprocess.run(["dpkg", "-i", str(pkg_path)]).returncode
    if ret != 0:
        subprocess.run(["apt-get", "install", "-f", "-y"],
                       stderr=subprocess.DEVNULL)

    # Disable cmk-agent-ctl-daemon to avoid port conflicts
    subprocess.run(["systemctl", "stop", "cmk-agent-ctl-daemon.service"],
                   stderr=subprocess.DEVNULL)
    subprocess.run(["systemctl", "disable", "cmk-agent-ctl-daemon.service"],
                   stderr=subprocess.DEVNULL)

    return ret == 0


def install_agent_rpm(pkg_path: Path, dry_run: bool = False, verbose: bool = False) -> bool:
    """Install .rpm package.

    Args:
        pkg_path: Path to .rpm file
        dry_run: If True, don't actually install
        verbose: Enable verbose output

    Returns:
        True if successful, False otherwise.
    """
    if dry_run:
        if verbose:
            print(f"[DRY-RUN] Would install: rpm -Uvh --replacepkgs {pkg_path}")
        return True

    if verbose:
        print(f"[INFO] Installing: {pkg_path.name}")

    ret = subprocess.run(["rpm", "-Uvh", "--replacepkgs", str(pkg_path)]).returncode
    return ret == 0


def install_agent_opkg(pkg_path: Path, dry_run: bool = False, verbose: bool = False) -> bool:
    """Install .deb package on OpenWrt (NethSecurity) by extracting binary.

    Args:
        pkg_path: Path to .deb file
        dry_run: If True, don't actually install
        verbose: Enable verbose output

    Returns:
        True if successful, False otherwise.
    """
    if dry_run:
        if verbose:
            print(f"[DRY-RUN] Would extract and install: {pkg_path}")
        return True

    if verbose:
        print(f"[INFO] Extracting and installing (OpenWrt): {pkg_path.name}")

    tmpdir = Path(tempfile.mkdtemp())
    try:
        subprocess.run(["ar", "x", str(pkg_path)], cwd=str(tmpdir), check=True)
        data_tars = list(tmpdir.glob("data.tar.*"))
        if not data_tars:
            print("[ERROR] data.tar.* not found in .deb", file=sys.stderr)
            return False

        subprocess.run(["tar", "-xf", str(data_tars[0]), "-C", str(tmpdir)], check=True)

        for candidate in (tmpdir / "usr/bin/check_mk_agent",
                          tmpdir / "usr/bin/check-mk-agent"):
            if candidate.exists():
                subprocess.run(["install", "-m", "0755", str(candidate),
                                "/usr/bin/check_mk_agent"], check=True)
                if verbose:
                    print("[OK] check_mk_agent installed")
                return True

        print("[ERROR] Agent binary not found in .deb", file=sys.stderr)
        return False
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Extraction failed: {e}", file=sys.stderr)
        return False
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


def parse_version(ver: str) -> Tuple[int, int, int, int]:
    """Parse CheckMK version string to comparable tuple.

    Ex: '2.4.0p23' → (2, 4, 0, 23)
        '2.4.0' → (2, 4, 0, 0)
    """
    m = re.match(r"(\d+)\.(\d+)\.(\d+)(?:p(\d+))?", ver.strip())
    if not m:
        return (0, 0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4) or 0))


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(
        description=f"CheckMK Agent Synchronization Tool v{SCRIPT_VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Verify only (default, non-destructive)
  python3 checkmk-agent-autoupdate-linux.py --server-url https://monitoring.nethlab.it --site monitoring

  # Dry-run
  python3 checkmk-agent-autoupdate-linux.py --dry-run --server-url https://monitoring.nethlab.it --site monitoring

  # Download only
  python3 checkmk-agent-autoupdate-linux.py --download-only --server-url https://monitoring.nethlab.it --site monitoring --package-cache-dir /tmp

  # Install (destructive)
  python3 checkmk-agent-autoupdate-linux.py --install --server-url https://monitoring.nethlab.it --site monitoring""",
    )
    p.add_argument(
        "--server-url",
        required=False,
        default="https://monitoring.nethlab.it",
        help="Base CheckMK server URL (default: https://monitoring.nethlab.it)",
    )
    p.add_argument(
        "--site",
        required=False,
        default="monitoring",
        help="CheckMK site name (default: monitoring)",
    )
    p.add_argument(
        "--target",
        choices=["auto", "deb", "rpm", "nethsecurity8", "ns8-container"],
        default="auto",
        help="Target system type (default: auto)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry-run mode: show what would happen without making changes",
    )
    p.add_argument(
        "--install",
        action="store_true",
        help="Install/update the agent if version differs (destructive)",
    )
    p.add_argument(
        "--download-only",
        action="store_true",
        help="Download only, do not install",
    )
    p.add_argument(
        "--package-cache-dir",
        type=str,
        default=None,
        help="Cache directory for downloaded packages (default: temp)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Force installation/download even if versions match",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    return p.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()
    report = StatusReport()

    # Determine mode
    if args.dry_run:
        mode = "DRY_RUN"
    elif args.download_only:
        mode = "DOWNLOAD_ONLY"
    elif args.install:
        mode = "INSTALL"
    else:
        mode = "VERIFY_ONLY"

    report.set("MODE", mode)
    report.set("DRY_RUN", args.dry_run)
    report.set("CHECKMK_SERVER_URL", args.server_url)
    report.set("CHECKMK_SITE", args.site)

    # Detect target
    if args.target == "auto":
        target_type, detection_reason = detect_target_type()
    else:
        target_type = args.target
        detection_reason = f"Explicitly specified: --target {args.target}"

    report.set("TARGET_VARIANT", target_type)
    report.set("TARGET_DETECTION_REASON", detection_reason)

    if args.verbose:
        print(f"[INFO] Target: {target_type} ({detection_reason})")
        print(f"[INFO] Mode: {mode}")

    # NS8 container: detect-only, no action
    if target_type == "ns8-container":
        report.set("FINAL_STATUS", "NS8_CONTAINER_DETECTED_NO_ACTION")
        print(report.output_text())
        return 0

    # NethSecurity 8: detect-only, no action for now
    if target_type == "nethsecurity8":
        report.set("FINAL_STATUS", "NETHSECURITY8_DETECTED_NO_ACTION")
        if args.verbose:
            print("[INFO] NethSecurity 8 detected (device-specific management)")
        print(report.output_text())
        return 0

    # Unsupported target
    if target_type == "unknown":
        report.set("FINAL_STATUS", "UNSUPPORTED_TARGET")
        report.set("ERROR_MESSAGE", "No recognized package manager detected")
        print(report.output_text(), file=sys.stderr)
        return 1

    # Get local version
    local_version = get_local_agent_version(target_type)
    report.set("INSTALLED_VERSION_BEFORE", local_version)

    if args.verbose:
        if local_version:
            print(f"[INFO] Local agent version: {local_version}")
        else:
            print(f"[INFO] Local agent: not installed")

    # Get remote version
    if args.verbose:
        print(f"[INFO] Querying server: {args.server_url}/{args.site}")

    remote_version = get_server_agent_version(args.server_url, args.site)
    if not remote_version:
        report.set("FINAL_STATUS", "REMOTE_PACKAGE_NOT_FOUND")
        report.set("ERROR_MESSAGE", f"Could not retrieve agent version from {args.server_url}/{args.site}")
        print(report.output_text(), file=sys.stderr)
        return 1

    report.set("REMOTE_PACKAGE_VERSION", remote_version)

    if args.verbose:
        print(f"[INFO] Remote agent version: {remote_version}")

    # Build download URL
    try:
        download_url, filename = build_download_url(
            args.server_url, args.site, remote_version, target_type
        )
        report.set("REMOTE_AGENT_PACKAGE_URL", download_url)
    except ValueError as e:
        report.set("FINAL_STATUS", "UNSUPPORTED_TARGET")
        report.set("ERROR_MESSAGE", str(e))
        print(report.output_text(), file=sys.stderr)
        return 1

    # Compare versions
    local_tuple = parse_version(local_version) if local_version else (0, 0, 0, 0)
    remote_tuple = parse_version(remote_version)

    update_needed = remote_tuple > local_tuple or (args.force and remote_tuple >= local_tuple)

    if args.verbose:
        print(f"[INFO] Version comparison: local {local_tuple} vs remote {remote_tuple}")

    # VERIFY_ONLY mode
    if mode == "VERIFY_ONLY":
        if update_needed:
            report.set("ACTION", "UPDATE_AVAILABLE")
            report.set("FINAL_STATUS", "AGENT_UPDATE_REQUIRED")
            if args.verbose:
                print(f"[INFO] Update available: {local_version or 'N/A'} → {remote_version}")
        else:
            report.set("ACTION", "NO_ACTION")
            report.set("FINAL_STATUS", "VERIFY_ONLY_OK")
            if args.verbose:
                print(f"[OK] Agent is already at desired version: {local_version or remote_version}")
        print(report.output_text())
        return 0

    # DRY_RUN mode
    if args.dry_run:
        if update_needed:
            report.set("ACTION", "WOULD_INSTALL")
            report.set("FINAL_STATUS", "DRY_RUN_AGENT_UPDATE_WOULD_RUN")
            report.add_note(f"Would download: {download_url}")
            report.add_note(f"Would install {remote_version}")
        else:
            report.set("ACTION", "NO_ACTION")
            report.set("FINAL_STATUS", "DRY_RUN_AGENT_ALREADY_ALIGNED")
        report.set("INSTALLED_VERSION_AFTER", "NOT_EXECUTED_DRY_RUN")
        print(report.output_text())
        return 0

    # DOWNLOAD_ONLY mode
    if args.download_only:
        if not update_needed and not args.force:
            report.set("ACTION", "NO_ACTION")
            report.set("FINAL_STATUS", "AGENT_ALREADY_ALIGNED")
            print(report.output_text())
            return 0

        cache_dir = Path(args.package_cache_dir) if args.package_cache_dir else Path(tempfile.gettempdir())
        cache_dir.mkdir(parents=True, exist_ok=True)

        pkg_path = cache_dir / filename
        report.set("LOCAL_PACKAGE_PATH", str(pkg_path))

        if not download_agent(download_url, pkg_path, args.verbose):
            report.set("FINAL_STATUS", "AGENT_UPDATE_FAILED")
            report.set("ERROR_MESSAGE", "Download failed")
            print(report.output_text(), file=sys.stderr)
            return 1

        report.set("ACTION", "DOWNLOADED")
        report.set("FINAL_STATUS", "DOWNLOAD_ONLY_OK")
        report.add_note(f"Downloaded to: {pkg_path}")
        print(report.output_text())
        return 0

    # INSTALL mode (requires root)
    if mode == "INSTALL":
        if os.geteuid() != 0:
            report.set("FINAL_STATUS", "AGENT_UPDATE_FAILED")
            report.set("ERROR_MESSAGE", "Root privilege required for installation")
            print(report.output_text(), file=sys.stderr)
            return 1

        if not update_needed and not args.force:
            report.set("ACTION", "NO_ACTION")
            report.set("FINAL_STATUS", "AGENT_ALREADY_ALIGNED")
            print(report.output_text())
            return 0

        # Create temp directory and download
        tmpdir = Path(tempfile.mkdtemp(prefix="cmk-agent-sync-"))
        try:
            pkg_path = tmpdir / filename
            report.set("LOCAL_PACKAGE_PATH", str(pkg_path))

            if not download_agent(download_url, pkg_path, args.verbose):
                report.set("FINAL_STATUS", "AGENT_UPDATE_FAILED")
                report.set("ERROR_MESSAGE", "Download failed")
                print(report.output_text(), file=sys.stderr)
                return 1

            # Install
            if target_type == "deb":
                ok = install_agent_deb(pkg_path, args.dry_run, args.verbose)
            elif target_type == "rpm":
                ok = install_agent_rpm(pkg_path, args.dry_run, args.verbose)
            elif target_type == "nethsecurity8":
                ok = install_agent_opkg(pkg_path, args.dry_run, args.verbose)
            else:
                ok = False

            if not ok:
                report.set("FINAL_STATUS", "AGENT_UPDATE_FAILED")
                report.set("ERROR_MESSAGE", "Installation failed")
                print(report.output_text(), file=sys.stderr)
                return 1

            # Verify new version
            new_version = get_local_agent_version(target_type)
            report.set("INSTALLED_VERSION_AFTER", new_version or remote_version)
            report.set("ACTION", "INSTALLED")
            report.set("FINAL_STATUS", "AGENT_UPDATE_SUCCESS")
            report.add_note(f"Updated to: {new_version or remote_version}")

            if args.verbose:
                print(f"[OK] Installation completed: {new_version or remote_version}")

            print(report.output_text())
            return 0

        finally:
            shutil.rmtree(str(tmpdir), ignore_errors=True)

    print(report.output_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
