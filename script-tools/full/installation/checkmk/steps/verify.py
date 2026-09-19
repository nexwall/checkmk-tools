from __future__ import annotations

import os
import subprocess
from pathlib import Path

from lib.common import Colors, command_exists, run_capture
from lib.config import InstallerConfig


def _ok(msg: str) -> None:
    print(f"{Colors.GREEN}{Colors.NC} {msg}")


def _fail(msg: str) -> None:
    print(f"{Colors.RED}{Colors.NC} {msg}")


def _warn(msg: str) -> None:
    print(f"{Colors.YELLOW}{Colors.NC} {msg}")


def _verify_site(site: str) -> tuple[bool, str]:
    if not command_exists("omd"):
        return False, "OMD not installed"
    sites = run_capture(["omd", "sites"], check=False)
    if site not in sites:
        return False, f"Site '{site}' not found"
    status = run_capture(["omd", "status", site], check=False)
    if "running" not in status:
        return False, f"Site '{site}' is not running"
    return True, "OK"


def run(cfg: InstallerConfig) -> int:
    errors = 0

    print("=== CheckMK Installation Verification ===\n")

    print("1. Checking OMD...")
    ok, msg = _verify_site(cfg.site_name)
    if ok:
        _ok("OMD installed")
        _ok(f"Site '{cfg.site_name}' exists and is running")
    else:
        _fail(msg)
        errors += 1
    print("")

    print("2. Checking Apache...")
    if command_exists("systemctl"):
        apache_running = subprocess.run(["systemctl", "is-active", "--quiet", "apache2"]).returncode == 0
        httpd_running = subprocess.run(["systemctl", "is-active", "--quiet", "httpd"]).returncode == 0
        if apache_running or httpd_running:
            _ok("Apache is running")
        else:
            _fail("Apache is not running")
            errors += 1
    else:
        _warn("systemctl not available; cannot check Apache")
    print("")

    print("3. Checking Firewall...")
    if command_exists("ufw"):
        status = run_capture(["ufw", "status"], check=False)
        if "Status: active" in status:
            _ok("UFW is active")
            if "80/tcp" in status:
                _ok("HTTP port 80 is open")
            else:
                _warn("HTTP port 80 may not be open")
            if "443/tcp" in status:
                _ok("HTTPS port 443 is open")
            else:
                _warn("HTTPS port 443 may not be open")
        else:
            _warn("UFW is inactive")
    else:
        _warn("ufw not installed")
    print("")

    print("4. Checking Fail2Ban...")
    if command_exists("systemctl"):
        if subprocess.run(["systemctl", "is-active", "--quiet", "fail2ban"]).returncode == 0:
            _ok("Fail2Ban is running")
        else:
            _warn("Fail2Ban is not running")
    else:
        _warn("systemctl not available; cannot check fail2ban")
    print("")

    print("5. Checking SSL...")
    if Path("/etc/letsencrypt/live").is_dir():
        _ok("Let's Encrypt directory exists")
    else:
        _warn("No Let's Encrypt certificates found")
    print("")

    print("6. Checking Web Access...")
    if command_exists("curl"):
        code = run_capture(
            [
                "bash",
                "-lc",
                f"curl -s -o /dev/null -w '%{{http_code}}' http://localhost/{cfg.site_name}/",
            ],
            check=False,
        )
        if code.startswith(("200", "301", "302")):
            _ok("CheckMK web interface accessible locally")
        else:
            _fail(f"CheckMK web interface not accessible (HTTP {code})")
            errors += 1
    else:
        _warn("curl not installed")

    print("")

    print("7. Checking Local Checks deployment...")
    local_dir = Path("/usr/lib/check_mk_agent/local")
    if not cfg.deploy_local_checks:
        _warn("DEPLOY_LOCAL_CHECKS=false: skipped")
    elif not local_dir.is_dir():
        _fail(f"Local checks directory not found: {local_dir}")
        errors += 1
    else:
        try:
            installed = [
                p
                for p in local_dir.iterdir()
                if p.is_file() and not p.name.startswith(".") and os.access(p, os.X_OK)
            ]
        except PermissionError:
            installed = []

        if installed:
            _ok(f"Local checks present: {len(installed)} executable file(s)")
        else:
            _fail("No executable local checks found")
            errors += 1

    print("")

    print("8. Checking Auto Git Sync...")
    if not cfg.enable_auto_git_sync:
        _warn("ENABLE_AUTO_GIT_SYNC=false: skipped")
    elif not command_exists("systemctl"):
        _warn("systemctl not available; cannot check auto-git-sync.service")
    else:
        script_path = Path("/usr/local/bin/auto-git-sync.py")
        if script_path.exists():
            _ok(f"Auto git sync script present: {script_path}")
        else:
            _fail(f"Auto git sync script missing: {script_path}")
            errors += 1

        service_name = "auto-git-sync.service"
        active = subprocess.run(["systemctl", "is-active", "--quiet", service_name]).returncode == 0
        enabled = subprocess.run(["systemctl", "is-enabled", "--quiet", service_name]).returncode == 0
        if active:
            _ok(f"{service_name} is active")
        else:
            _fail(f"{service_name} is not active")
            errors += 1
        if enabled:
            _ok(f"{service_name} is enabled")
        else:
            _warn(f"{service_name} is not enabled")

    print("\n===================================")
    ip = run_capture(["bash", "-lc", "hostname -I | awk '{print $1}'"], check=False)
    if errors == 0:
        print(f"{Colors.GREEN} All checks passed{Colors.NC}\n")
        print(f"Access CheckMK at: http://{ip}/{cfg.site_name}")
        return 0
    print(f"{Colors.RED} {errors} check(s) failed{Colors.NC}\n")
    print("Review the errors above and fix any issues")
    return 1
