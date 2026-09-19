from __future__ import annotations

import shlex
from pathlib import Path

from lib.common import cleanup_backup_files, command_exists, log_error, log_header, log_info, log_success, log_warn, require_root
from lib.common import run as run_cmd
from lib.common import _BACKUP_DIR, run_capture
from lib.config import InstallerConfig

# backup_file() now stores everything in _BACKUP_DIR (/var/backups/checkmk-installer)
# plus we still clean any stale .backup files from old runs in these dirs
_LEGACY_BACKUP_DIRS: list[Path] = [
    Path("/etc/apt/apt.conf.d"),
    Path("/etc/ssh"),
    Path("/etc/chrony"),
    Path("/etc/fail2ban"),
    Path("/lib/systemd/system"),
]


def _mount_points_to_unmount(findmnt_output: str) -> list[str]:
    """Parse `findmnt -R -n -o TARGET <dir>` output into unmount order
    (deepest/innermost mount first, so nested mounts don't block each other)."""
    points = [line.strip() for line in findmnt_output.splitlines() if line.strip()]
    return list(reversed(points))


def _delete_dir(path: Path) -> bool:
    """Delete a directory (rm -rf). Returns True if something was deleted."""
    if not path.exists():
        return False
    log_warn(f"Deleting: {path}")
    run_cmd(["rm", "-rf", str(path)], check=False)
    return True


def _list_installed_packages() -> set[str]:
    out = run_capture(["dpkg-query", "-W", "-f", "${Package}\n"], check=False)
    return {line.strip() for line in out.splitlines() if line.strip()}


def _filter_removal_packages(installed: set[str]) -> list[str]:
    prefixes = [
        "check-mk-raw-",
        "check-mk-community-",
    ]

    exact = {
        "check-mk-agent",
        "check-mk-agent-logwatch",
        "gdebi-core",
        "postfix",
        "mailutils",
        "ufw",
        "fail2ban",
        "apache2",
        "certbot",
        "python3-certbot-apache",
        "timeshift",
        "chrony",
        "unattended-upgrades",
        "python3-pip",
        # NOT "git": remove-all deliberately keeps auto-git-sync.service and
        # the /opt/checkmk-tools repo clone running (see run() below) - both
        # need git to function. Purging it left auto-git-sync silently
        # failing every cycle forever, confirmed live on ubntmarzio 2026-08-03.
    }

    to_remove: set[str] = set()
    for pkg in installed:
        if pkg in exact:
            to_remove.add(pkg)
            continue
        if any(pkg.startswith(pfx) for pfx in prefixes):
            to_remove.add(pkg)

    return sorted(to_remove)


# Maps each leftover config dir to the package(s) that must be confirmed gone
# before it's safe to delete. Regression fix 2026-08-03: apt-get purge runs
# with check=False, so a failed purge (e.g. the apache2/python3-certbot-apache
# cross-dependency, or a broken maintainer script) used to leave a package
# still installed while this step deleted its config dir anyway - dpkg then
# considers the package "ii" (fully installed) with no config on disk, which
# breaks any future reinstall/reconfigure of that exact package. Confirmed
# live on ubntmarzio: postfix, ufw, fail2ban, apache2 and chrony were all
# found in this broken state from an earlier remove-all run.
_LEFTOVER_DIR_OWNERS: dict[Path, list[str]] = {
    Path("/etc/fail2ban"): ["fail2ban"],
    Path("/etc/apache2"): ["apache2"],
    Path("/etc/postfix"): ["postfix"],
    Path("/etc/ufw"): ["ufw"],
    Path("/etc/chrony"): ["chrony"],
}


def _any_checkmk_package_installed(installed: set[str]) -> bool:
    """True if any check-mk-raw-* or check-mk-community-* package is still installed.

    Used to gate the /opt/omd/versions/* force-cleanup below: CheckMK's own
    postrm script does a plain rmdir on its version directory, which fails
    (and can abort the whole apt transaction, see check-mk-community's
    pre-removal check earlier in this file) if anything unrelated was left
    inside - confirmed live on ubntmarzio 2026-08-03: a stray python_dotenv
    install under lib/python3.13/site-packages blocked the rmdir, leaving
    the whole version directory orphaned on disk even though dpkg considers
    the package (eventually) purged.
    """
    prefixes = ("check-mk-raw-", "check-mk-community-")
    return any(pkg.startswith(prefixes) for pkg in installed)


def _dirs_safe_to_delete(still_installed: set[str]) -> list[Path]:
    """Leftover config dirs whose owning package(s) are confirmed NOT installed."""
    return [
        path
        for path, owners in _LEFTOVER_DIR_OWNERS.items()
        if not any(pkg in still_installed for pkg in owners)
    ]


def _backup_cloud_push_units(site: str) -> tuple[list[str], list[str]]:
    """Systemd units for the local backup jobs and cloud-push mechanism.

    Returns (units_to_stop_and_disable, unit_files_to_delete). The
    cloud-push template units (checkmk-cloud-backup-push@.*) are deleted
    but not stopped directly - only their site-instantiated form
    (checkmk-cloud-backup-push@<site>.*) is a running unit.
    """
    backup_job_units = [
        "checkmk-backup-job00.service",
        "checkmk-backup-job00.timer",
        "checkmk-backup-job01.service",
        "checkmk-backup-job01.timer",
    ]
    cloud_push_instance_units = [
        f"checkmk-cloud-backup-push@{site}.timer",
        f"checkmk-cloud-backup-push@{site}.path",
        f"checkmk-cloud-backup-push@{site}.service",
    ]
    cloud_push_template_units = [
        "checkmk-cloud-backup-push@.service",
        "checkmk-cloud-backup-push@.path",
        "checkmk-cloud-backup-push@.timer",
    ]
    to_stop = [*backup_job_units, *cloud_push_instance_units]
    to_delete = [*backup_job_units, *cloud_push_template_units]
    return to_stop, to_delete


def _backup_cloud_push_files(site: str) -> list[Path]:
    """Non-systemd files left by the backup/cloud-push mechanism, keyed by site."""
    return [
        Path("/usr/local/sbin/checkmk_cloud_backup_push_run.sh"),
        Path(f"/etc/default/checkmk-cloud-backup-push-{site}"),
    ]


def _confirm_or_abort(host: str, site: str) -> None:
    log_header("REMOVE ALL (UNINSTALL)")
    log_warn("This will REMOVE CheckMK/OMD and related services installed by this bootstrap.")
    log_warn("It will also remove common dependencies (apache2/postfix/ufw/fail2ban/certbot/git/pip).")
    print("")
    print(f"Host: {host}")
    print(f"Site: {site}")
    print("")

    typed_host = input("Type the hostname to confirm: ").strip()
    if typed_host != host:
        raise SystemExit("Confirmation failed: hostname mismatch")

    typed = input("Type REMOVE to proceed: ").strip()
    if typed != "REMOVE":
        raise SystemExit("Aborted")


def _confirm_non_interactive(host: str, confirm_hostname: str) -> None:
    if not confirm_hostname:
        raise SystemExit("--assume-yes requires --confirm-hostname")
    if confirm_hostname != host:
        raise SystemExit(f"Confirmation failed: expected hostname '{confirm_hostname}', got '{host}'")


def run(cfg: InstallerConfig, *, assume_yes: bool = False, confirm_hostname: str = "") -> None:
    require_root()

    host = run_capture(["hostname"], check=False) or "unknown"
    if assume_yes:
        _confirm_non_interactive(host=host, confirm_hostname=confirm_hostname)
    else:
        _confirm_or_abort(host=host, site=cfg.site_name)

    log_header("Stopping services")
    # auto-git-sync and local checks are NOT removed (excluded from remove-all)
    run_cmd(["systemctl", "stop", "--now", "apache2"], check=False)
    run_cmd(["systemctl", "stop", "--now", "postfix"], check=False)
    run_cmd(["systemctl", "stop", "--now", "fail2ban"], check=False)

    if command_exists("omd"):
        log_header("Removing OMD site")
        run_cmd(["omd", "stop", cfg.site_name], check=False)
        # omd rm doesn't support --yes on all versions: use manual umount + rm directly
        run_cmd(["omd", "rm", cfg.site_name], check=False)
        # Fallback: if site dir still exists after omd rm, delete it manually
        site_dir = Path(f"/omd/sites/{cfg.site_name}")
        if site_dir.exists():
            log_warn(f"omd rm did not remove {site_dir} - deleting manually")
            # Unmount tmp (tmpfs) to avoid 'device or resource busy'
            tmp_dir = site_dir / "tmp"
            if tmp_dir.exists():
                run_cmd(["umount", "-l", str(tmp_dir)], check=False)
            run_cmd(["rm", "-rf", str(site_dir)], check=False)

    log_header("Removing backup / cloud-push jobs")
    # Local packages/config/systemd units only - the remote rclone bucket
    # contents are NOT touched here, that stays a deliberate manual step.
    units_to_stop, units_to_delete = _backup_cloud_push_units(cfg.site_name)
    for unit in units_to_stop:
        run_cmd(["systemctl", "disable", "--now", unit], check=False)

    systemd_dir = Path("/etc/systemd/system")
    for unit in units_to_delete:
        _delete_dir(systemd_dir / unit)
    for path in _backup_cloud_push_files(cfg.site_name):
        _delete_dir(path)
    run_cmd(["systemctl", "daemon-reload"], check=False)

    log_header("Cleaning up timeshift runtime state")
    # /run is tmpfs so this vanishes on reboot regardless, but an interrupted
    # backup can leave an active bind-mount under here that a plain package
    # purge won't unmount on its own.
    timeshift_run_dir = Path("/run/timeshift")
    if timeshift_run_dir.is_dir():
        findmnt_out = run_capture(["findmnt", "-R", "-n", "-o", "TARGET", str(timeshift_run_dir)], check=False)
        for mount_point in _mount_points_to_unmount(findmnt_out):
            run_cmd(["umount", "-l", mount_point], check=False)
        _delete_dir(timeshift_run_dir)
    else:
        log_info("No /run/timeshift runtime state found")

    log_header("Cleaning up installer backup files")
    total_cleaned = 0
    # Central backup dir (current)
    for d in [_BACKUP_DIR, *_LEGACY_BACKUP_DIRS]:
        n = cleanup_backup_files(d)
        if n:
            log_info(f"  Deleted {n} backup file(s) from {d}")
            total_cleaned += n
    if total_cleaned == 0:
        log_info("No backup files found to clean")
    else:
        log_success(f"Cleaned {total_cleaned} backup file(s) total")

    log_header("Purging packages")
    installed = _list_installed_packages()
    to_remove = _filter_removal_packages(installed)

    if to_remove:
        log_info(f"Purging {len(to_remove)} packages...")
        log_info("Packages: " + " ".join(shlex.quote(p) for p in to_remove))
        purge_result = run_cmd(["apt-get", "purge", "-y", *to_remove], check=False)
        if purge_result.returncode != 0:
            log_warn("apt-get purge exited with an error - some packages may still be installed")
    else:
        log_info("No matching packages to purge")

    log_header("Autoremove")
    run_cmd(["apt-get", "autoremove", "-y"], check=False)

    # Explicitly remove leftover config dirs dpkg won't delete when not empty
    # ESCLUSI: /usr/lib/check_mk_agent (contiene i check locali deployati)
    #
    # Re-check what's ACTUALLY still installed (not just the purge exit code)
    # before deleting each dir - only delete when its owning package(s) are
    # confirmed gone, otherwise skip it and warn. See _LEFTOVER_DIR_OWNERS.
    log_header("Removing leftover config directories")
    still_installed = _list_installed_packages()
    for path, owners in _LEFTOVER_DIR_OWNERS.items():
        remaining = [pkg for pkg in owners if pkg in still_installed]
        if remaining:
            log_warn(f"Skipping {path}: package(s) {remaining} still installed - leaving config in place to avoid an inconsistent state")
            continue
        _delete_dir(path)
    _delete_dir(Path("/omd"))

    # Force-clean any orphaned /opt/omd/versions/* left by a failed postrm,
    # once no check-mk-raw-*/check-mk-community-* package remains installed
    # (i.e. dpkg itself is done with them, regardless of postrm's own
    # rmdir cleanup succeeding or not).
    if not _any_checkmk_package_installed(_list_installed_packages()):
        versions_dir = Path("/opt/omd/versions")
        if versions_dir.is_dir():
            for version_path in sorted(versions_dir.iterdir()):
                if version_path.is_dir():
                    _delete_dir(version_path)

    log_header("Deleting directories")
    dirs_to_delete: list[Path] = [
        Path("/omd"),
        Path("/etc/check_mk"),
        # ESCLUSO: /opt/checkmk-tools (repo) e /usr/lib/check_mk_agent/local (check deployati)
    ]
    for path in dirs_to_delete:
        _delete_dir(path)

    log_info("Mantenuti: /opt/checkmk-tools (repo), auto-git-sync.service, /usr/lib/check_mk_agent/local/")

    log_header("Result")
    if command_exists("omd"):
        log_error("omd is still present on PATH; removal may be incomplete")
    else:
        log_success("Remove-all completed (omd not present)")

