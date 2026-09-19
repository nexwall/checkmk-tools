#!/usr/bin/env python3
"""upgrade-checkmk.py

Python wrapper for upgrade-checkmk.sh with outcome management for automations/emails:
- No updates available
- Update completed with final version
- Update failed with rollback performed
- Skipped: pre-release (beta/RC) version detected
- Post-upgrade self-agent update from the upgraded Checkmk site
- Self-agent update version verification and test mode

Version: 1.6.1"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

VERSION = "1.6.1"
REPORT_FILE = Path("/tmp/checkmk-upgrade-report.txt")
BACKUP_DIR = Path("/opt/omd/backups")
EMAIL_FROM = "no-reply@nethesis.it"


def detect_backend() -> tuple[Path, str] | None:
    """Find the upgrade backend: shell script first, then Python fallback.

    Returns (path, runner) or None if nothing is found."""
    sh_candidates = [
        Path(__file__).with_name("upgrade-checkmk.sh"),
        Path("/usr/local/bin/upgrade-checkmk.sh"),
        Path("/opt/checkmk-tools/script-tools/full/upgrade_maintenance/upgrade-checkmk.sh"),
    ]
    for c in sh_candidates:
        if c.exists():
            return c, "bash"
    # Python fallback (upgrade_checkmk.py with underscore)
    py_candidates = [
        Path(__file__).with_name("upgrade_checkmk.py"),
        Path("/opt/checkmk-tools/script-tools/full/upgrade_maintenance/upgrade_checkmk.py"),
    ]
    for c in py_candidates:
        if c.exists():
            return c, "python3"
    return None


def run_cmd(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def read_report() -> str:
    if not REPORT_FILE.exists():
        return ""
    return REPORT_FILE.read_text(encoding="utf-8", errors="ignore")


def detect_site_from_report(report: str) -> str:
    # Match both English (Site:) and Italian (Sito:) variants
    match = re.search(r"^(?:Site|Sito):\s*(\S+)", report, re.MULTILINE)
    if match:
        return match.group(1)

    try:
        sites = run_cmd(["omd", "sites"])
        for line in sites.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("SITE"):
                continue
            return line.split()[0]
    except FileNotFoundError:
        # omd binary missing (e.g. removed by buggy cleanup) — try OMD sites dir
        for candidate in [Path("/omd/sites"), Path("/opt/omd/sites")]:
            if candidate.exists():
                dirs = [d.name for d in candidate.iterdir() if d.is_dir()]
                if dirs:
                    return dirs[0]
    return ""


def get_current_version(site_name: str) -> str:
    if not site_name:
        return "unknown"
    out = run_cmd(["omd", "version", site_name])
    match = re.search(r"[0-9]+\.[0-9]+\.[0-9]+p[0-9]+", out.stdout)
    return match.group(0) if match else "unknown"


def get_latest_backup(site_name: str) -> Path | None:
    if not site_name or not BACKUP_DIR.exists():
        return None
    candidates = sorted(BACKUP_DIR.glob(f"{site_name}_pre-upgrade_*.tar.gz"), reverse=True)
    return candidates[0] if candidates else None


def execute_rollback(site_name: str, backup_file: Path) -> tuple[bool, str]:
    if not site_name:
        return False, "site non determinato"
    if not backup_file.exists():
        return False, f"backup non trovato: {backup_file}"

    stop_res = run_cmd(["omd", "stop", site_name])
    if stop_res.returncode not in (0,):
        return False, f"stop fallito: {stop_res.stderr.strip() or stop_res.stdout.strip()}"

    restore_res = run_cmd(["omd", "restore", site_name, str(backup_file)])
    if restore_res.returncode != 0:
        return False, f"restore fallito: {restore_res.stderr.strip() or restore_res.stdout.strip()}"

    start_res = run_cmd(["omd", "start", site_name])
    if start_res.returncode != 0:
        return False, f"start post-rollback fallito: {start_res.stderr.strip() or start_res.stdout.strip()}"

    return True, "rollback eseguito"


def fix_site_ownership(site_name: str) -> int:
    """Fix files under /omd/sites/<site>/ not owned by the site user.

    Root-owned files inside the OMD tree make 'omd backup' (run as the site
    user) fail with Permission denied, which blocks both scheduled backups
    and pre-upgrade backups.

    This function finds and corrects such files. It excludes var/log/ and .git/
    to avoid touching active log files or the repository metadata.

    Returns the number of files fixed, or -1 on error.
    """
    site_root = Path(f"/omd/sites/{site_name}")
    if not site_root.is_dir():
        return 0

    try:
        result = subprocess.run(
            [
                "find", str(site_root),
                "-not", "-path", f"{site_root}/var/log/*",
                "-not", "-path", f"{site_root}/.git/*",
                "-type", "f",
                "!", "(", "-user", site_name, "-a", "-group", site_name, ")",
            ],
            text=True, capture_output=True, timeout=30,
        )
        if result.returncode != 0:
            return -1

        files = [f for f in result.stdout.splitlines() if f.strip()]
        if not files:
            return 0

        fixed = 0
        for f in files:
            try:
                subprocess.run(
                    ["chown", f"{site_name}:{site_name}", f],
                    capture_output=True, timeout=5,
                )
                fixed += 1
            except Exception:
                pass

        # Also fix __pycache__ directories with wrong ownership
        subprocess.run(
            [
                "find", str(site_root),
                "-not", "-path", f"{site_root}/var/log/*",
                "-type", "d", "-name", "__pycache__",
                "-exec", "chown", "-R", f"{site_name}:{site_name}", "{}", "+",
            ],
            capture_output=True, timeout=30,
        )

        return fixed
    except subprocess.TimeoutExpired:
        print(f"[WARN] Ownership check timed out for site {site_name}", file=sys.stderr)
        return -1
    except Exception as e:
        print(f"[WARN] Ownership check failed: {e}", file=sys.stderr)
        return -1


def get_omd_version(site_name: str) -> str:
    """Get the Checkmk/OMD version for the site.

    Returns version string or "UNKNOWN" if detection fails.
    """
    if not site_name:
        return "UNKNOWN"
    out = run_cmd(["omd", "version", site_name])
    if out.returncode != 0:
        return "UNKNOWN"
    # Extract version line (usually first line with format like "2.5.0p7")
    match = re.search(r"[0-9]+\.[0-9]+\.[0-9]+p[0-9]+", out.stdout)
    return match.group(0) if match else "UNKNOWN"


def get_installed_agent_version() -> str:
    """Get the local installed Checkmk agent version.

    Uses dpkg-query on Debian/Ubuntu.
    Returns version string, "NOT_INSTALLED" if not found, or "UNKNOWN" if detection fails.
    """
    result = run_cmd(["dpkg-query", "-W", "-f=${Version}", "check-mk-agent"])
    if result.returncode != 0:
        return "NOT_INSTALLED"
    version = result.stdout.strip()
    return version if version else "NOT_INSTALLED"


def get_agent_package_version(agent_package_path: Path) -> str:
    """Get the version from an agent .deb package.

    Uses dpkg-deb to read package metadata.
    Returns version string, or "PACKAGE_VERSION_UNKNOWN" if detection fails.
    """
    if not agent_package_path or not agent_package_path.exists():
        return "PACKAGE_VERSION_UNKNOWN"
    result = run_cmd(["dpkg-deb", "-f", str(agent_package_path), "Version"])
    if result.returncode != 0:
        return "PACKAGE_VERSION_UNKNOWN"
    version = result.stdout.strip()
    return version if version else "PACKAGE_VERSION_UNKNOWN"


def verify_self_agent_version(expected_version: str, installed_version: str) -> tuple[bool, str]:
    """Verify that the installed agent version matches the expected version.

    Returns (match: bool, status_str: str).
    Status string is one of:
    - "SELF_AGENT_UPDATE_SUCCESS"
    - "SELF_AGENT_UPDATE_VERSION_MISMATCH"
    - "SELF_AGENT_UPDATE_VERIFY_FAILED"
    - "SELF_AGENT_UPDATE_DONE_VERSION_UNKNOWN"
    """
    if expected_version == "PACKAGE_VERSION_UNKNOWN":
        return False, "SELF_AGENT_UPDATE_DONE_VERSION_UNKNOWN"
    if installed_version == "UNKNOWN" or installed_version == "NOT_INSTALLED":
        return False, "SELF_AGENT_UPDATE_VERIFY_FAILED"
    if expected_version == installed_version:
        return True, "SELF_AGENT_UPDATE_SUCCESS"
    return False, "SELF_AGENT_UPDATE_VERSION_MISMATCH"


def find_agent_package(site_name: str) -> Path | None:
    """Find the newest Checkmk agent .deb package in the upgraded site.

    Search in /omd/sites/<site>/share/check_mk/agents/ for check-mk-agent_*_all.deb.
    Returns the newest package path or None if not found.
    """
    if not site_name:
        return None

    agent_dir = Path(f"/omd/sites/{site_name}/share/check_mk/agents")
    if not agent_dir.exists():
        return None

    candidates = sorted(agent_dir.glob("check-mk-agent_*_all.deb"), reverse=True)
    return candidates[0] if candidates else None


def update_self_checkmk_agent(site_name: str, dry_run: bool = False) -> dict:
    """Update the local Checkmk agent from the upgraded site with version verification.

    Search for the agent package in the upgraded site and install it locally.
    Track and verify versions before, during, and after the update.

    Returns dict with keys:
    - success (bool): whether update succeeded
    - detail (str): human-readable summary
    - omd_version (str): detected OMD version
    - agent_version_before (str): local agent version before update
    - site_agent_package_path (str): path to discovered package
    - site_agent_package_version (str): version from package metadata
    - agent_version_after (str): local agent version after update
    - version_match (bool): whether after version matches package version
    - update_status (str): one of SELF_AGENT_UPDATE_* constants
    """
    result = {
        "success": False,
        "detail": "",
        "omd_version": "UNKNOWN",
        "agent_version_before": "UNKNOWN",
        "site_agent_package_path": "",
        "site_agent_package_version": "UNKNOWN",
        "agent_version_after": "UNKNOWN",
        "version_match": False,
        "update_status": "SELF_AGENT_UPDATE_FAILED",
    }

    if not site_name:
        result["detail"] = "site name not determined"
        return result

    # Phase 1: Collect pre-update versions
    result["omd_version"] = get_omd_version(site_name)
    result["agent_version_before"] = get_installed_agent_version()

    # Phase 2: Verify site is running after upgrade
    status_res = run_cmd(["omd", "status", site_name])
    if status_res.returncode != 0:
        result["detail"] = f"site {site_name} not running after upgrade"
        result["update_status"] = "SELF_AGENT_UPDATE_FAILED"
        return result

    # Phase 3: Find agent package in the upgraded site
    agent_pkg = find_agent_package(site_name)
    if not agent_pkg:
        result["detail"] = "no agent package found in site"
        result["update_status"] = "SELF_AGENT_UPDATE_FAILED"
        return result

    result["site_agent_package_path"] = str(agent_pkg)
    result["site_agent_package_version"] = get_agent_package_version(agent_pkg)

    # Phase 4: Early return for dry-run before any real installation
    if dry_run:
        result["success"] = True
        result["agent_version_after"] = "NOT_EXECUTED_DRY_RUN"
        result["detail"] = f"DRY_RUN: would install agent {result['site_agent_package_version']} from {agent_pkg.name}"

        # Determine dry-run status based on version alignment
        if result["agent_version_before"] == "UNKNOWN" or result["site_agent_package_version"] == "UNKNOWN":
            result["version_match"] = False
            result["update_status"] = "DRY_RUN_SELF_AGENT_VERSION_UNKNOWN"
        elif result["agent_version_before"] == result["site_agent_package_version"]:
            result["version_match"] = True
            result["update_status"] = "DRY_RUN_SELF_AGENT_ALREADY_ALIGNED"
        else:
            result["version_match"] = False
            result["update_status"] = "DRY_RUN_SELF_AGENT_UPDATE_WOULD_RUN"
        return result

    # Phase 5: Real installation
    install_res = run_cmd(["dpkg", "-i", str(agent_pkg)])
    if install_res.returncode != 0:
        result["detail"] = f"dpkg install failed: {install_res.stderr.strip() or install_res.stdout.strip()}"
        result["update_status"] = "SELF_AGENT_UPDATE_FAILED"
        return result

    # Phase 6: Verify agent command exists and runs
    # Use bash because 'command' is a shell builtin, not an executable
    verify_res = subprocess.run(
        ["bash", "-c", "command -v check_mk_agent"],
        text=True, capture_output=True,
    )
    if verify_res.returncode != 0:
        result["detail"] = "check_mk_agent command not found after install"
        result["update_status"] = "SELF_AGENT_UPDATE_FAILED"
        return result

    # Phase 7: Run agent to verify it works
    agent_run = run_cmd(["check_mk_agent"], check=False)
    if agent_run.returncode != 0:
        result["detail"] = f"check_mk_agent execution failed: {agent_run.stderr.strip()}"
        result["update_status"] = "SELF_AGENT_UPDATE_FAILED"
        return result

    # Phase 8: Collect post-update version and verify
    result["agent_version_after"] = get_installed_agent_version()
    version_match, update_status = verify_self_agent_version(
        result["site_agent_package_version"],
        result["agent_version_after"],
    )
    result["version_match"] = version_match
    result["update_status"] = update_status

    if version_match:
        result["success"] = True
        result["detail"] = (
            f"agent updated from {result['agent_version_before']} "
            f"to {result['agent_version_after']} (OMD: {result['omd_version']})"
        )
    else:
        result["success"] = False
        result["detail"] = (
            f"agent version after install ({result['agent_version_after']}) "
            f"does not match package version ({result['site_agent_package_version']})"
        )

    return result


def send_mail(recipient: str, subject: str, body: str) -> None:
    if not recipient:
        return
    cmd = ["mail", "-r", EMAIL_FROM, "-s", subject, recipient]
    result = subprocess.run(cmd, input=body, text=True, capture_output=True)
    if result.returncode != 0:
        subprocess.run(["mail", "-s", subject, recipient], input=body, text=True, capture_output=True)


def build_message(status: str, site_name: str, version: str, details: str = "") -> tuple[str, str]:
    host = os.uname().nodename
    if status == "NO_UPDATE":
        subject = f"CheckMK Auto-Upgrade - Nessun aggiornamento ({host})"
        body = f"Nessun aggiornamento disponibile per il sito {site_name}.\nVersione corrente: {version}\n"
    elif status == "SKIPPED_BETA":
        subject = f"CheckMK Auto-Upgrade - Saltato: versione beta/RC ({host})"
        body = (
            f"Auto-upgrade saltato: rilevata versione pre-release ({version}) sul sito {site_name}.\n"
            f"L'upgrade automatico verso la stable e' disabilitato quando e' installata una beta o RC.\n"
            f"Aggiornare manualmente quando si e' pronti a passare alla versione stabile.\n"
        )
    elif status == "SUCCESS":
        subject = f"CheckMK Auto-Upgrade - Completato ({host})"
        body = f"Aggiornamento completato alla versione: {version}\nSito: {site_name}\n"
    elif status == "SUCCESS_WITH_AGENT_UPDATE_FAILED":
        subject = f"CheckMK Auto-Upgrade - Completato, ma agent update fallito ({host})"
        body = (
            f"Aggiornamento server completato alla versione: {version}\nSito: {site_name}\n"
            f"ATTENZIONE: Aggiornamento agent locale fallito.\nDettagli: {details}\n"
        )
    elif status == "FAILED_ROLLBACK":
        subject = f"CheckMK Auto-Upgrade - Fallito con rollback ({host})"
        body = f"Aggiornamento fallito: eseguito rollback.\nSito: {site_name}\nDettagli: {details}\n"
    else:
        subject = f"CheckMK Auto-Upgrade - Fallito ({host})"
        body = f"Aggiornamento fallito e rollback non eseguito.\nSito: {site_name}\nDettagli: {details}\n"
    return subject, body


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wrapper upgrade-checkmk con esiti strutturati")
    parser.add_argument("--email", default="", help="Email destinatario report esito")
    parser.add_argument("--dry-run", action="store_true", help="Simulate upgrade and agent update without making changes")
    parser.add_argument("--test-self-agent-update", action="store_true", help="Test only the self-agent update phase without server upgrade")
    parser.add_argument("forward_args", nargs=argparse.REMAINDER, help="Argomenti da inoltrare allo script shell")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Handle test mode: run only self-agent update without server upgrade
    if args.test_self_agent_update:
        print("[TEST_MODE] Running self-agent update test without server upgrade")
        site_name = detect_site_from_report("")
        if not site_name:
            # Try to find a site directly
            for site_dir in Path("/omd/sites").iterdir():
                if site_dir.is_dir() and (site_dir / "etc").exists():
                    site_name = site_dir.name
                    break
        if not site_name:
            print("ERROR: Could not determine site name for test mode", file=sys.stderr)
            return 1

        print(f"[TEST_MODE] Testing self-agent update on site: {site_name}")
        agent_result = update_self_checkmk_agent(site_name, dry_run=args.dry_run)

        print("\n=== TEST_MODE SELF-AGENT UPDATE REPORT ===")
        print(f"SERVER_UPGRADE: not executed, test mode")
        print(f"OMD_VERSION_AFTER: {agent_result['omd_version']}")
        print(f"LOCAL_AGENT_VERSION_BEFORE: {agent_result['agent_version_before']}")
        print(f"SITE_AGENT_PACKAGE_PATH: {agent_result['site_agent_package_path']}")
        print(f"SITE_AGENT_PACKAGE_VERSION: {agent_result['site_agent_package_version']}")
        print(f"LOCAL_AGENT_VERSION_AFTER: {agent_result['agent_version_after']}")
        print(f"SELF_AGENT_VERSION_MATCH: {'yes' if agent_result['version_match'] else 'no'}")
        print(f"UPDATE_STATUS: {agent_result['update_status']}")
        # Add test mode prefix for dry-run operations
        final_status = f"TEST_SELF_AGENT_UPDATE_DRY_RUN" if args.dry_run else f"TEST_{agent_result['update_status']}"
        print(f"FINAL_STATUS: {final_status}")
        print(f"DETAIL: {agent_result['detail']}")

        return 0 if agent_result["success"] else 1

    result = detect_backend()
    if result is None:
        print(
            "ERROR: missing target script: upgrade-checkmk.sh or upgrade_checkmk.py "
            "(checked: sibling, /usr/local/bin, /opt/checkmk-tools/script-tools/full/upgrade_maintenance)",
            file=sys.stderr,
        )
        return 1

    script, runner = result

    forward = args.forward_args
    if forward and forward[0] == "--":
        forward = forward[1:]

    # Add --dry-run to forward args if specified
    if args.dry_run:
        forward = ["--dry-run"] + forward

    # Fix ownership before upgrade to prevent backup failures caused by
    # root-owned files inside the OMD site tree
    if Path("/omd/sites").is_dir():
        for site_dir in Path("/omd/sites").iterdir():
            if site_dir.is_dir() and (site_dir / "etc").exists():
                fixed = fix_site_ownership(site_dir.name)
                if fixed > 0:
                    print(f"[INFO] Fixed {fixed} file(s) owned by wrong user in site {site_dir.name}")
                elif fixed < 0:
                    print(f"[WARN] Ownership check failed for site {site_dir.name}")

    run = subprocess.run([runner, str(script), *forward], text=True)
    report = read_report()
    site_name = detect_site_from_report(report)

    no_update = "Nessun aggiornamento necessario" in report or "No upgrade needed" in report
    if run.returncode == 0 and no_update:
        version = get_current_version(site_name)
        self_agent_result = update_self_checkmk_agent(site_name, dry_run=False)
        print(f"SELF_AGENT_UPDATE: {self_agent_result['detail']}")
        subject, body = build_message("NO_UPDATE", site_name, version)
        send_mail(args.email, subject, body)
        print(f"NO_UPDATE: sito {site_name} già alla versione {version}")
        return 0

    skipped_beta = "SKIPPED_BETA" in report
    if run.returncode == 0 and skipped_beta:
        version = get_current_version(site_name)
        subject, body = build_message("SKIPPED_BETA", site_name, version)
        send_mail(args.email, subject, body)
        print(f"SKIPPED_BETA: versione pre-release rilevata ({version}), auto-upgrade disabilitato")
        return 0

    if run.returncode == 0:
        version = get_current_version(site_name)
        # Fix ownership after upgrade (upgrade may create root-owned artifacts)
        if site_name:
            fixed = fix_site_ownership(site_name)
            if fixed > 0:
                print(f"[INFO] Fixed {fixed} file(s) owned by wrong user in site {site_name}")

        # POST_UPGRADE_SITE_VERIFY and SELF_AGENT_UPDATE phase
        if not args.dry_run:
            agent_result = update_self_checkmk_agent(site_name, dry_run=False)
        else:
            agent_result = update_self_checkmk_agent(site_name, dry_run=True)
            print(f"[DRY_RUN] Agent update: {agent_result['detail']}")

        # Report version information
        print(f"\n=== SELF_AGENT_UPDATE VERSION REPORT ===")
        print(f"OMD_VERSION_AFTER: {agent_result['omd_version']}")
        print(f"LOCAL_AGENT_VERSION_BEFORE: {agent_result['agent_version_before']}")
        print(f"SITE_AGENT_PACKAGE_PATH: {agent_result['site_agent_package_path']}")
        print(f"SITE_AGENT_PACKAGE_VERSION: {agent_result['site_agent_package_version']}")
        print(f"LOCAL_AGENT_VERSION_AFTER: {agent_result['agent_version_after']}")
        print(f"SELF_AGENT_VERSION_MATCH: {'yes' if agent_result['version_match'] else 'no'}")
        print(f"UPDATE_STATUS: {agent_result['update_status']}")

        if agent_result["success"]:
            subject, body = build_message("SUCCESS", site_name, version)
            body += f"\n=== Agent Update Details ===\n"
            body += f"OMD Version: {agent_result['omd_version']}\n"
            body += f"Agent Version Before: {agent_result['agent_version_before']}\n"
            body += f"Agent Version After: {agent_result['agent_version_after']}\n"
            body += f"Package Version: {agent_result['site_agent_package_version']}\n"
            body += f"Version Match: {'yes' if agent_result['version_match'] else 'no'}\n"
            body += f"Status: {agent_result['update_status']}\n"
            body += f"Detail: {agent_result['detail']}\n"
            send_mail(args.email, subject, body)
            print(f"SUCCESS: aggiornamento completato alla versione {version}")
            print(f"SELF_AGENT_UPDATE: {agent_result['detail']}")
            return 0
        else:
            # Server upgrade succeeded but agent update failed
            subject, body = build_message("SUCCESS_WITH_AGENT_UPDATE_FAILED", site_name, version, agent_result["detail"])
            body += f"\n=== Agent Update Details ===\n"
            body += f"OMD Version: {agent_result['omd_version']}\n"
            body += f"Agent Version Before: {agent_result['agent_version_before']}\n"
            body += f"Agent Version After: {agent_result['agent_version_after']}\n"
            body += f"Package Version: {agent_result['site_agent_package_version']}\n"
            body += f"Status: {agent_result['update_status']}\n"
            body += f"Detail: {agent_result['detail']}\n"
            send_mail(args.email, subject, body)
            print(f"SUCCESS_WITH_AGENT_UPDATE_FAILED: server upgrade OK, agent update failed")
            print(f"[WARN] Agent update detail: {agent_result['detail']}")
            return 0

    backup = get_latest_backup(site_name)
    if backup is not None:
        rollback_ok, detail = execute_rollback(site_name, backup)
        if rollback_ok:
            subject, body = build_message("FAILED_ROLLBACK", site_name, get_current_version(site_name), detail)
            send_mail(args.email, subject, body)
            print("FAILED_ROLLBACK: aggiornamento fallito, eseguito rollback")
            return 2
        subject, body = build_message("FAILED", site_name, get_current_version(site_name), detail)
        send_mail(args.email, subject, body)
        print(f"FAILED: aggiornamento fallito, rollback non riuscito ({detail})")
        return 1

    subject, body = build_message("FAILED", site_name, "unknown", "backup non disponibile")
    send_mail(args.email, subject, body)
    print("FAILED: aggiornamento fallito, rollback non eseguito (backup non disponibile)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
