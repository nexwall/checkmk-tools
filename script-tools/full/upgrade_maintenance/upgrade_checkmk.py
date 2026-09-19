#!/usr/bin/env python3
"""upgrade_checkmk.py - CheckMK Upgrade Automation

Automates the CheckMK update process (CRE/Community Edition).
Features:
- Current and latest available version detection
- Supports both check-mk-raw (<=2.4.x) and check-mk-free (>=2.5.x Community)
- Site backup before upgrade
- Download and install .deb package
- Stop/Update/Start the site
- Cleanup obsolete versions and old packages
- Detailed report

Usage:
    upgrade_checkmk.py [site_name]

Version: 1.4.1"""

import sys
import os
import re
import shutil
import subprocess
import requests
import time
import argparse
from datetime import datetime
from pathlib import Path

VERSION = "1.5.0"

# --- Configuration ---
DOWNLOAD_DIR = Path("/tmp/checkmk-upgrade")
BACKUP_DIR = Path("/opt/omd/backups")
REPORT_FILE = Path("/tmp/checkmk-upgrade-report.txt")

class Console:
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'
    
    @staticmethod
    def log(msg): 
        print(f"{Console.BLUE}[INFO]{Console.NC} {msg}")
        with open(REPORT_FILE, "a") as f: f.write(f"[INFO] {msg}\n")
    
    @staticmethod
    def warn(msg): 
        print(f"{Console.YELLOW}[WARN]{Console.NC} {msg}")
        with open(REPORT_FILE, "a") as f: f.write(f"[WARN] {msg}\n")
        
    @staticmethod
    def error(msg, fatal=True): 
        print(f"{Console.RED}[ERROR]{Console.NC} {msg}")
        with open(REPORT_FILE, "a") as f: f.write(f"[ERROR] {msg}\n")
        if fatal: sys.exit(1)
        
    @staticmethod
    def success(msg): 
        print(f"{Console.GREEN}[OK]{Console.NC} {msg}")
        with open(REPORT_FILE, "a") as f: f.write(f"[OK] {msg}\n")

def run_cmd(cmd, check=True):
    Console.log(f"Exec: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=check, text=True, capture_output=False)
        return True
    except subprocess.CalledProcessError as e:
        Console.warn(f"Command failed: {e}")
        return False

def get_current_version(site):
    try:
        res = subprocess.check_output(["omd", "version", site], text=True)
        # Match stable (pN), beta (bN), and release candidate (rcN) versions
        # e.g. 2.4.0p24.cre, 2.5.0b2.cee, 2.5.0rc1.cre
        m = re.search(r'(\d+\.\d+\.\d+(?:p\d+|b\d+|rc\d+))', res)
        if m: return m.group(1)
    except Exception:
        pass
    Console.error(f"Cannot detect version for site {site}")


def is_prerelease_version(version: str) -> bool:
    """Return True if version is a beta (bN) or release candidate (rcN),
    not a stable release (pN). Auto-upgrade must never run on pre-release builds."""
    return bool(re.search(r'\d+\.\d+\.\d+(?:b\d+|rc\d+)$', version))

def _version_key(v: str):
    """Convert 'X.Y.ZpN' to a tuple for numeric comparison."""
    m = re.match(r'^(\d+)\.(\d+)\.(\d+)p(\d+)$', v)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
    return (0, 0, 0, 0)


def get_latest_version():
    """Return (version, pkg_prefix) of the latest stable CheckMK release.

    Package naming changed between major versions:
      2.4.x and earlier  ->  check-mk-raw-X.Y.ZpN        (CRE / Raw Edition)
      2.5.0 and later    ->  check-mk-community-X.Y.ZpN  (Community Edition)

    Detection strategy:
      - CRE: filename 'check-mk-raw-X.Y.ZpN' appears directly in page HTML
      - Community: parsed from HTML attribute data-edition="community" data-version="X.Y.ZpN"
    """
    try:
        url = "https://checkmk.com/download"
        res = requests.get(url, timeout=10)
        # 2.4.x and earlier: filename listed verbatim in page source
        raw_versions = re.findall(r'check-mk-raw-(\d+\.\d+\.\d+p\d+)', res.text)
        # 2.5.0+: version exposed via HTML data attributes (JS-rendered selector)
        community_versions = re.findall(
            r'data-edition=["\']community["\'][^>]*?data-version=["\'](\d+\.\d+\.\d+p\d+)["\']',
            res.text
        )

        best_version = None
        best_prefix  = None

        for v in set(raw_versions):
            if best_version is None or _version_key(v) > _version_key(best_version):
                best_version = v
                best_prefix  = "check-mk-raw"

        for v in set(community_versions):
            if best_version is None or _version_key(v) > _version_key(best_version):
                best_version = v
                best_prefix  = "check-mk-community"

        if best_version:
            return best_version, best_prefix
    except Exception as e:
        Console.warn(f"Failed to check update: {e}")
    return None, None

def cleanup_half_configured_packages():
    """Remove any check-mk-* packages left in half-configured (iF) state.

    These accumulate when dpkg -i succeeds partially but the post-installation
    script fails (e.g. update-alternatives pointing to a non-existent OMD version
    directory). A single iF package blocks all subsequent apt/dpkg operations
    and causes 'apt-get autoremove' to fail with exit code 100.

    This function must be called:
    - Before installing a new .deb (preventive cleanup)
    - After a dpkg -i failure (recovery cleanup)
    """
    try:
        result = subprocess.run(
            ["dpkg", "-l"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return

        half_configured = []
        for line in result.stdout.splitlines():
            # State 'iF' = half-configured (install failed)
            if line.startswith("iF") and "check-mk-" in line:
                parts = line.split()
                if len(parts) >= 2:
                    half_configured.append(parts[1])

        if not half_configured:
            return

        Console.warn(
            f"Found {len(half_configured)} half-configured check-mk package(s): "
            f"{', '.join(half_configured)}. Removing..."
        )
        subprocess.run(
            ["dpkg", "--remove", "--force-depends"] + half_configured,
            capture_output=True, text=True, timeout=30,
        )
        Console.log("Half-configured packages removed successfully")
    except Exception as e:
        Console.warn(f"Failed to clean half-configured packages: {e}")


def detect_deb_codename():
    try:
        with open("/etc/os-release") as f:
            data = f.read()
        
        distro_id = re.search(r'^ID=([a-z]+)', data, re.M).group(1)
        version_id = re.search(r'^VERSION_ID="?([^"]+)"?', data, re.M).group(1)
        
        if distro_id == "ubuntu":
            if version_id == "20.04": return "focal"
            if version_id == "22.04": return "jammy"
            if version_id == "24.04": return "noble"
        elif distro_id == "debian":
            if version_id == "11": return "bullseye"
            if version_id == "12": return "bookworm"
            
    except Exception:
        pass
    Console.error("Unsupported OS/Version")

class Upgrader:
    def __init__(self, site):
        self.site = site
        self.codename = detect_deb_codename()
        
    def run(self):
        # Init Report
        with open(REPORT_FILE, "w") as f:
            f.write(f"CHECKMK UPGRADE REPORT - {datetime.now()}\n")
            f.write(f"Site: {self.site}\n\n")

        current = get_current_version(self.site)
        latest, pkg_prefix = get_latest_version()

        Console.log(f"Current: {current}")
        Console.log(f"Latest:  {latest} ({pkg_prefix})")

        # Safety guard: never auto-upgrade from a pre-release (beta/RC) version.
        # Installing a stable package over a beta is a downgrade and breaks the site.
        if is_prerelease_version(current):
            Console.warn(
                f"Pre-release version detected ({current}) — skipping auto-upgrade. "
                "Upgrade manually when ready to move to stable."
            )
            with open(REPORT_FILE, "a") as f:
                f.write(
                    f"SKIPPED_BETA: pre-release version {current} detected "
                    "— auto-upgrade disabled to prevent incompatible version change\n"
                )
            return

        if not latest or current == latest:
            Console.success("No upgrade needed")
            return

        Console.log(f"Upgrading {current} -> {latest} (package: {pkg_prefix})")

        # Clean up stale .backup_ temp files left by previous failed omd backup runs
        # or by WATO config edits run as root. Pattern: *.backup_ and *.backup_TIMESTAMP.
        # These are owned by root and block the next omd backup (run as site user).
        site_dir = Path(f"/omd/sites/{self.site}")
        stale = list(site_dir.rglob("*.backup_*"))
        if stale:
            Console.log(f"Removing {len(stale)} stale .backup_* file(s) before backup...")
            for f in stale:
                try:
                    f.unlink()
                except Exception as e:
                    Console.warn(f"Could not remove {f}: {e}")

        # Backups
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_file = BACKUP_DIR / f"{self.site}_pre-upgrade_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz"
        Console.log(f"Backup site to {backup_file}...")
        if not run_cmd(["omd", "backup", self.site, str(backup_file)]):
            Console.error("Backup failed, aborting upgrade. Check for stale .backup_* files owned by root.")

        # Download
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        pkg_name = f"{pkg_prefix}-{latest}_0.{self.codename}_amd64.deb"
        url = f"https://download.checkmk.com/checkmk/{latest}/{pkg_name}"
        local_pkg = DOWNLOAD_DIR / pkg_name
        
        if not local_pkg.exists():
            Console.log(f"Downloading {url}...")
            r = requests.get(url, stream=True)
            if r.status_code == 200:
                with open(local_pkg, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            else:
                Console.error(f"Download failed: {r.status_code}")
                
        # Pre-install: clean any half-configured packages that would block dpkg
        cleanup_half_configured_packages()

        # Install
        Console.log("Installing .deb...")
        if not run_cmd(["dpkg", "-i", str(local_pkg)]):
            Console.warn("dpkg failed — cleaning half-configured packages and retrying...")
            cleanup_half_configured_packages()
            run_cmd(["apt-get", "install", "-f", "-y"])
            if not run_cmd(["dpkg", "-i", str(local_pkg)]):
                Console.error("Install failed")
                
        # Upgrade Site
        Console.log("Stopping site...")
        run_cmd(["omd", "stop", self.site])
        
        Console.log("Updating site...")
        run_cmd(["omd", "-f", "update", "--conflict=install", self.site])
        
        Console.log("Starting site...")
        run_cmd(["omd", "start", self.site])
        
        new_ver = get_current_version(self.site)
        Console.success(f"Upgrade completed. New version: {new_ver}")
        
        self.cleanup(current, new_ver)

    def cleanup(self, old_ver, new_ver):
        Console.log("Cleanup...")

        # Detect actual OMD versions directory (varies by distro)
        for candidate in [Path("/omd/versions"), Path("/opt/omd/versions")]:
            if candidate.exists():
                versions_dir = candidate
                break
        else:
            Console.warn("OMD versions directory not found, skipping version cleanup")
            versions_dir = None

        if versions_dir:
            # new_ver from omd version output is e.g. '2.4.0p24', but dirs are '2.4.0p24.cre'
            # Keep any directory whose name starts with new_ver
            for v in versions_dir.iterdir():
                if v.is_dir() and not v.is_symlink() and v.name != "default":
                    if not v.name.startswith(new_ver):
                        Console.log(f"Removing old version: {v.name}")
                        shutil.rmtree(v)
                    
        # Fix any remaining broken dependencies before cleanup
        run_cmd(["apt-get", "install", "-f", "-y"])

        # Remove old debs
        run_cmd(["apt-get", "autoremove", "-y"])
        
        # Clean downloads
        shutil.rmtree(DOWNLOAD_DIR)

def main():
    if os.geteuid() != 0:
        Console.error("Run as root")
        
    parser = argparse.ArgumentParser()
    parser.add_argument("site", nargs="?")
    args = parser.parse_args()
    
    site = args.site
    if not site:
        # Detect
        try:
            sites = subprocess.check_output(["omd", "sites", "--bare"], text=True).split()
            if not sites: Console.error("No sites found")
            site = sites[0] # Default to first
        except:
            Console.error("OMD not found")
            
    Upgrader(site).run()

if __name__ == "__main__":
    main()
