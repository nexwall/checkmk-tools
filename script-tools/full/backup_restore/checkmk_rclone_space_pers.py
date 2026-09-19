#!/usr/bin/env python3
"""checkmk_rclone_space_pers.py

Version: 1.0.0"""

import argparse
import datetime as dt
import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

VERSION = "1.0.0"

DEFAULT_REMOTE = "do:testmonbck"
DEFAULT_EXTERNAL_MOUNT_BASE = "/mnt/checkmk-spaces"
DEFAULT_CACHE_BASE = "/var/cache/rclone"
DEFAULT_LOG_BASE = "/var/log"
DEFAULT_VFS_CACHE_MAX_SIZE = "10G"
DEFAULT_VFS_CACHE_MAX_AGE = "24h"
DEFAULT_DIR_CACHE_TIME = "5m"
DEFAULT_POLL_INTERVAL = "1m"
DEFAULT_TIMEOUT = "30s"
DEFAULT_CONTIMEOUT = "10s"
DEFAULT_RETRIES = "10"
DEFAULT_LOW_LEVEL_RETRIES = "20"
DEFAULT_SITES_BASES = ["/opt/omd/sites", "/omd/sites"]


def log(message: str) -> None:
    print(f"[{dt.datetime.now().strftime('%F %T')}] {message}")


def warn(message: str) -> None:
    print(f"WARN: {message}", file=sys.stderr)


def die(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def run_shell(command: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-lc", command], check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def require_root() -> None:
    if os.geteuid() != 0:
        die("Run as root.")


def need_cmd(command: str) -> None:
    if shutil.which(command) is None:
        die(f"Missing command: {command}")


def prompt_default(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def prompt_secret(prompt: str) -> str:
    return getpass.getpass(f"{prompt}: ").strip()


def confirm_default_no(prompt: str) -> bool:
    value = input(f"{prompt} [y/N]: ").strip().lower()
    return value == "y"


def discover_site_bases() -> List[Path]:
    return [Path(base) for base in DEFAULT_SITES_BASES if Path(base).is_dir()]


def list_sites() -> List[str]:
    if shutil.which("omd"):
        result = run(["omd", "sites"], check=False)
        sites: List[str] = []
        for line in (result.stdout or "").splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            site = line.split()[0]
            if site.replace("_", "a").replace("-", "a").isalnum():
                sites.append(site)
        return sorted(set(sites))

    found = set()
    for base in discover_site_bases():
        for child in base.iterdir():
            if child.is_dir():
                found.add(child.name)
    return sorted(found)


def pick_site_interactive_or_manual() -> str:
    sites = list_sites()
    if not sites:
        warn("No sites auto-discovered. You can still proceed by entering site name manually.")
        return prompt_default("Enter site name", "monitoring")

    log("Available OMD sites:")
    for idx, site in enumerate(sites, start=1):
        print(f"  [{idx}] {site}")

    while True:
        choice = input("Select site number (or type a site name): ").strip()
        if choice.isdigit():
            n = int(choice)
            if 1 <= n <= len(sites):
                return sites[n - 1]
            warn("Invalid selection.")
            continue
        if choice and choice.replace("_", "a").replace("-", "a").isalnum():
            return choice
        warn("Invalid input.")


def resolve_site_home(site: str) -> Path:
    if shutil.which("omd"):
        result = run(["omd", "config", site, "show", "HOME"], check=False)
        if result.returncode == 0:
            parts = (result.stdout or "").strip().split()
            if parts:
                home = Path(parts[-1])
                if home.is_dir():
                    return home

    for base in discover_site_bases():
        candidate = base / site
        if candidate.is_dir():
            return candidate

    guess = Path(prompt_default("Enter full site home path", f"/opt/omd/sites/{site}"))
    return guess


def site_user_from_site(site: str) -> str:
    return site


def install_rclone_stable() -> None:
    if shutil.which("rclone"):
        version = run(["rclone", "version"], check=False).stdout.splitlines()
        log(f"rclone is already installed: {version[0] if version else 'version unknown'}")
        return

    need_cmd("curl")
    log("Installing rclone (stable) from rclone.org...")
    installer = Path(f"/tmp/rclone-install-{os.getpid()}.sh")
    download = run(["curl", "-fsSL", "https://rclone.org/install.sh", "-o", str(installer)], check=False)
    if download.returncode != 0:
        die("Failed to download rclone install script")

    exec_res = run(["bash", str(installer)], check=False)
    try:
        installer.unlink(missing_ok=True)
    except Exception:
        pass

    if exec_res.returncode != 0 or not shutil.which("rclone"):
        die("Failed to install rclone")


def ensure_fuse_allow_other() -> None:
    fuse_conf = Path("/etc/fuse.conf")
    if not fuse_conf.exists():
        die("/etc/fuse.conf not found (install fuse3).")

    content = fuse_conf.read_text(encoding="utf-8", errors="ignore")
    if "\nuser_allow_other\n" in f"\n{content}\n":
        log("user_allow_other already enabled in fuse.conf")
        return

    backup = Path(f"/etc/fuse.conf.backup.{int(dt.datetime.now().timestamp())}")
    try:
        shutil.copy2(fuse_conf, backup)
    except Exception:
        pass

    lines = content.splitlines()
    changed = False
    for i, line in enumerate(lines):
        if line.strip().startswith("#") and "user_allow_other" in line:
            lines[i] = "user_allow_other"
            changed = True
            break

    if not changed:
        lines.append("user_allow_other")

    fuse_conf.write_text("\n".join(lines) + "\n", encoding="utf-8")


def normalize_abs_mountpoint(mountpoint: str) -> str:
    mp = mountpoint.strip().rstrip("/")
    if not mp:
        die("Mountpoint cannot be empty.")
    if not mp.startswith("/"):
        die("Mountpoint must be absolute.")
    if ".." in mp:
        die("Mountpoint cannot contain '..'.")
    if mp == "":
        die("Invalid mountpoint")
    return mp


def assert_mountpoint_outside_site(site_home: Path, mountpoint: str) -> None:
    site_home_str = str(site_home)
    if mountpoint == site_home_str or mountpoint.startswith(site_home_str + "/"):
        die(f"Mountpoint must be external to site: {mountpoint}")


def default_external_mountpoint_for_site(site: str) -> str:
    return f"{DEFAULT_EXTERNAL_MOUNT_BASE}/{site}"


def default_cache_dir_for_site(site: str) -> str:
    return f"{DEFAULT_CACHE_BASE}/{site}"


def default_log_file_for_site(site: str) -> str:
    return f"{DEFAULT_LOG_BASE}/rclone-{site}-mount.log"


def remote_exists(rclone_config: Path, remote_name: str) -> bool:
    env = os.environ.copy()
    env["RCLONE_CONFIG"] = str(rclone_config)
    result = subprocess.run(["rclone", "config", "show", remote_name], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.returncode == 0


def create_or_update_remote_s3(rclone_config: Path, remote_name: str, provider: str, access_key: str, secret_key: str, region: str, endpoint: str) -> None:
    env = os.environ.copy()
    env["RCLONE_CONFIG"] = str(rclone_config)
    cmd = [
        "rclone", "config", "create", remote_name, "s3",
        f"provider={provider}",
        "env_auth=false",
        f"access_key_id={access_key}",
        f"secret_access_key={secret_key}",
        f"region={region}",
        f"endpoint={endpoint}",
        "acl=private",
        "--obscure",
    ]
    res = subprocess.run(cmd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        die(f"Failed to configure remote '{remote_name}': {res.stderr.strip()}")


def ensure_remote_configured(rclone_config: Path, remote_full: str) -> None:
    if ":" not in remote_full:
        die(f"Remote must be in form name:bucket. Got: {remote_full}")

    remote_name = remote_full.split(":", 1)[0]

    if remote_exists(rclone_config, remote_name):
        if confirm_default_no(f"Remote '{remote_name}' already exists. Reconfigure it?"):
            log(f"Reconfiguring existing remote '{remote_name}'.")
        else:
            log(f"Remote '{remote_name}' already configured.")
            return
    else:
        log(f"Remote '{remote_name}' not found in {rclone_config}. Will create it now.")

    mode = prompt_default("Remote type (do/aws)", "do")
    access_key = prompt_default("S3 Access Key ID", "")
    if not access_key:
        die("Access Key ID cannot be empty.")
    secret_key = prompt_secret("S3 Secret Access Key")
    if not secret_key:
        die("Secret Access Key cannot be empty.")

    if mode == "do":
        region = prompt_default("DO Spaces region (e.g. nyc3, fra1, ams3)", "ams3")
        endpoint = prompt_default("DO Spaces endpoint URL", f"https://{region}.digitaloceanspaces.com")
        provider = "DigitalOcean"
    else:
        region = prompt_default("AWS region (e.g. eu-west-1)", "eu-west-1")
        endpoint = prompt_default("AWS S3 endpoint URL", f"https://s3.{region}.amazonaws.com")
        provider = "AWS"

    create_or_update_remote_s3(rclone_config, remote_name, provider, access_key, secret_key, region, endpoint)


def write_unit(
    unit_path: Path,
    unit_name: str,
    site: str,
    site_user: str,
    site_group: str,
    rclone_config: Path,
    rclone_bin: str,
    remote: str,
    mountpoint: str,
    cache_dir: str,
    log_file: str,
    vfs_cache_max_size: str,
    vfs_cache_max_age: str,
    dir_cache_time: str,
    poll_interval: str,
    timeout: str,
    contimeout: str,
    retries: str,
    low_level_retries: str,
) -> None:
    uid = run(["id", "-u", site_user], check=False).stdout.strip() or "0"
    gid = run(["id", "-g", site_user], check=False).stdout.strip() or "0"

    unit = f"""[Unit]
Description=Rclone mount {remote} for Checkmk site {site} (external mountpoint)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={site_user}
Group={site_group}
Environment=RCLONE_CONFIG={rclone_config}
TimeoutStopSec=20
ExecStart={rclone_bin} mount {remote} {mountpoint} \\
  --allow-other \\
  --uid {uid} --gid {gid} \\
  --umask 002 \\
  --vfs-cache-mode full \\
  --cache-dir {cache_dir} \\
  --vfs-cache-max-size {vfs_cache_max_size} \\
  --vfs-cache-max-age {vfs_cache_max_age} \\
  --dir-cache-time {dir_cache_time} \\
  --poll-interval {poll_interval} \\
  --timeout {timeout} \\
  --contimeout {contimeout} \\
  --retries {retries} \\
  --low-level-retries {low_level_retries} \\
  --log-file {log_file} \\
  --log-level INFO
ExecStop=/bin/fusermount3 -uz {mountpoint}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target"""

    unit_path.write_text(unit, encoding="utf-8")
    if not unit_path.exists():
        die(f"Failed to write unit file: {unit_path}")


def write_cleanup_script(cleanup_script: Path) -> None:
    script = r"""#!/usr/bin/env bash
set -euo pipefail

MOUNTPOINT="${1:?missing mountpoint}"
RETENTION_DAYS="${2:-90}"
LOGFILE="/var/log/checkmk-backup-cleanup.log"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOGFILE"; }

if [[ ! -d "$MOUNTPOINT" ]]; then
  log "ERROR: Mountpoint not found: $MOUNTPOINT"
  exit 1
fi

RENAMED=0
while IFS= read -r -d '' backup; do
  BACKUP_NAME="$(basename "$backup")"
  if [[ "$BACKUP_NAME" =~ -incomplete ]]; then
    continue
  fi

  LAST_MODIFIED=$(stat -c %Y "$backup" 2>/dev/null || echo "0")
  CURRENT_TIME=$(date +%s)
  AGE_SECONDS=$((CURRENT_TIME - LAST_MODIFIED))
  [[ $AGE_SECONDS -lt 120 ]] && continue

  if [[ -d "$backup" ]]; then
    BACKUP_SIZE=$(du -sb "$backup" 2>/dev/null | awk '{print $1}')
  else
    BACKUP_SIZE=$(stat -c %s "$backup" 2>/dev/null || echo "0")
  fi
  [[ $BACKUP_SIZE -lt 102400 ]] && continue

  if [[ ! "$BACKUP_NAME" =~ -[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{2}h[0-9]{2}$ ]]; then
    MTIME=$(stat -c %Y "$backup" 2>/dev/null || echo "0")
    TIMESTAMP=$(date -d "@${MTIME}" '+%Y-%m-%d-%Hh%M' 2>/dev/null || date '+%Y-%m-%d-%Hh%M')
    NEW_PATH="${MOUNTPOINT}/${BACKUP_NAME}-${TIMESTAMP}"
    mv "$backup" "$NEW_PATH" && RENAMED=$((RENAMED+1))
  fi
done < <(find "$MOUNTPOINT" -mindepth 1 -maxdepth 1 \( -type f -o -type d \) -name 'Check_MK-*' -print0 2>/dev/null)

DELETED=0
while IFS= read -r -d '' backup; do
  rm -rf "$backup" && DELETED=$((DELETED+1))
done < <(find "$MOUNTPOINT" -mindepth 1 -maxdepth 1 \( -type f -o -type d \) -mtime +${RETENTION_DAYS} -print0 2>/dev/null)

log "Renamed $RENAMED backup(s), deleted $DELETED backup(s).""""
    cleanup_script.write_text(script, encoding="utf-8")
    cleanup_script.chmod(0o755)


def write_cleanup_units(site: str, mountpoint: str, retention_days: str = "90") -> None:
    cleanup_script = Path(f"/usr/local/sbin/checkmk_backup_cleanup_{site}.sh")
    rename_script = Path(f"/usr/local/sbin/checkmk_backup_rename_{site}.sh")

    write_cleanup_script(cleanup_script)

    rename_body = r"""#!/usr/bin/env bash
set -euo pipefail

MOUNTPOINT="${1:?missing mountpoint}"
LOGFILE="/var/log/checkmk-backup-rename.log"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOGFILE"; }

[[ -d "$MOUNTPOINT" ]] || exit 1

RENAMED=0
while IFS= read -r -d '' backup; do
  BACKUP_NAME="$(basename "$backup")"
  [[ "$BACKUP_NAME" =~ -incomplete ]] && continue

  LAST_MODIFIED=$(stat -c %Y "$backup" 2>/dev/null || echo "0")
  CURRENT_TIME=$(date +%s)
  AGE_SECONDS=$((CURRENT_TIME - LAST_MODIFIED))
  [[ $AGE_SECONDS -lt 120 ]] && continue

  if [[ -d "$backup" ]]; then
    BACKUP_SIZE=$(du -sb "$backup" 2>/dev/null | awk '{print $1}')
  else
    BACKUP_SIZE=$(stat -c %s "$backup" 2>/dev/null || echo "0")
  fi
  [[ $BACKUP_SIZE -lt 102400 ]] && continue

  if [[ ! "$BACKUP_NAME" =~ -[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{2}h[0-9]{2}$ ]]; then
    TIMESTAMP=$(date '+%Y-%m-%d-%Hh%M')
    NEW_PATH="${MOUNTPOINT}/${BACKUP_NAME}-${TIMESTAMP}"
    mv "$backup" "$NEW_PATH" 2>/dev/null && RENAMED=$((RENAMED+1)) || true
  fi
done < <(find "$MOUNTPOINT" -mindepth 1 -maxdepth 1 \( -type f -o -type d \) -name 'Check_MK-*' ! -name '*-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*' -print0 2>/dev/null)

[[ $RENAMED -gt 0 ]] && log "Renamed $RENAMED backup(s)" || log "No backups to rename""""
    rename_script.write_text(rename_body, encoding="utf-8")
    rename_script.chmod(0o755)

    cleanup_service = Path(f"/etc/systemd/system/checkmk-backup-cleanup@{site}.service")
    cleanup_timer = Path(f"/etc/systemd/system/checkmk-backup-cleanup@{site}.timer")
    rename_service = Path(f"/etc/systemd/system/checkmk-backup-rename@{site}.service")
    rename_timer = Path(f"/etc/systemd/system/checkmk-backup-rename@{site}.timer")

    cleanup_service.write_text(
        f"""[Unit]
Description=Cleanup old backups for Checkmk site {site}

[Service]
Type=oneshot
ExecStart={cleanup_script} {mountpoint} {retention_days}""",
        encoding="utf-8",
    )

    cleanup_timer.write_text(
        f"""[Unit]
Description=Daily cleanup timer for Checkmk site {site} backups

[Timer]
OnCalendar=daily
OnBootSec=1h
Persistent=true

[Install]
WantedBy=timers.target""",
        encoding="utf-8",
    )

    rename_service.write_text(
        f"""[Unit]
Description=Rename backup after creation for Checkmk site {site}

[Service]
Type=oneshot
ExecStart={rename_script} {mountpoint}""",
        encoding="utf-8",
    )

    rename_timer.write_text(
        f"""[Unit]
Description=Timer for backup rename for Checkmk site {site}

[Timer]
OnCalendar=*:0/1
Persistent=true
Unit=checkmk-backup-rename@{site}.service

[Install]
WantedBy=timers.target""",
        encoding="utf-8",
    )


def stop_unmount_disable(unit_name: str, mountpoint: str) -> None:
    run(["systemctl", "stop", unit_name], check=False)
    run(["systemctl", "disable", unit_name], check=False)
    mount_check = run_shell(f"mount | grep -qF ' on {mountpoint} '", check=False)
    if mount_check.returncode == 0:
        run(["fusermount3", "-uz", mountpoint], check=False)


def setup_flow() -> None:
    need_cmd("systemctl")
    need_cmd("fusermount3")

    site = pick_site_interactive_or_manual()
    site_home = resolve_site_home(site)
    if not site_home.is_dir():
        die(f"Site home does not exist: {site_home}")

    site_user = site_user_from_site(site)
    if run(["id", site_user], check=False).returncode != 0:
        warn(f"Default site user '{site_user}' not found.")
        site_user = prompt_default("Enter site user to run rclone under", site)
        if run(["id", site_user], check=False).returncode != 0:
            die(f"User '{site_user}' not found.")

    site_group = site_user
    if run(["getent", "group", site_group], check=False).returncode != 0:
        site_group = run(["id", "-gn", site_user], check=False).stdout.strip() or site_user

    rclone_config = site_home / ".config" / "rclone" / "rclone.conf"
    if not rclone_config.exists():
        warn(f"rclone config not found at {rclone_config}")
        rclone_config = Path(prompt_default("Enter full path to rclone.conf for site", str(rclone_config)))
        if not rclone_config.exists():
            die(f"rclone config still not found: {rclone_config}")

    config_dir = rclone_config.parent
    run(["chown", "-R", f"{site_user}:{site_group}", str(config_dir)], check=False)
    run(["chmod", "755", str(config_dir)], check=False)
    run(["chmod", "600", str(rclone_config)], check=False)

    remote_name = prompt_default("Enter rclone remote name", "do")
    bucket_name = prompt_default("Enter bucket name", "testmonbck")
    remote = f"{remote_name}:{bucket_name}"
    ensure_remote_configured(rclone_config, remote)

    mountpoint = normalize_abs_mountpoint(prompt_default("Enter EXTERNAL mountpoint path (absolute)", default_external_mountpoint_for_site(site)))
    assert_mountpoint_outside_site(site_home, mountpoint)

    unit_name = prompt_default("Enter systemd unit name", f"rclone-{site}-spaces.service")
    unit_path = Path("/etc/systemd/system") / unit_name

    cache_dir = prompt_default("Enter rclone cache dir", default_cache_dir_for_site(site))
    log_file = prompt_default("Enter rclone log file", default_log_file_for_site(site))

    vfs_cache_max_size = prompt_default("VFS cache max size", DEFAULT_VFS_CACHE_MAX_SIZE)
    vfs_cache_max_age = prompt_default("VFS cache max age", DEFAULT_VFS_CACHE_MAX_AGE)
    dir_cache_time = prompt_default("Dir cache time", DEFAULT_DIR_CACHE_TIME)
    poll_interval = prompt_default("Poll interval", DEFAULT_POLL_INTERVAL)
    timeout = prompt_default("Network timeout", DEFAULT_TIMEOUT)
    contimeout = prompt_default("Connect timeout", DEFAULT_CONTIMEOUT)
    retries = prompt_default("Retries", DEFAULT_RETRIES)
    low_level_retries = prompt_default("Low-level retries", DEFAULT_LOW_LEVEL_RETRIES)

    install_rclone_stable()
    ensure_fuse_allow_other()

    Path(mountpoint).mkdir(parents=True, exist_ok=True)
    run(["chown", f"{site_user}:{site_group}", mountpoint], check=False)
    run(["chmod", "2775", mountpoint], check=False)

    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    run(["chown", f"{site_user}:{site_group}", cache_dir], check=False)
    run(["chmod", "750", cache_dir], check=False)

    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    Path(log_file).touch(exist_ok=True)
    run(["chown", f"{site_user}:{site_group}", log_file], check=False)
    run(["chmod", "640", log_file], check=False)

    rclone_bin = shutil.which("rclone")
    if not rclone_bin:
        die("rclone binary not found")

    stop_unmount_disable(unit_name, mountpoint)

    write_unit(
        unit_path,
        unit_name,
        site,
        site_user,
        site_group,
        rclone_config,
        rclone_bin,
        remote,
        mountpoint,
        cache_dir,
        log_file,
        vfs_cache_max_size,
        vfs_cache_max_age,
        dir_cache_time,
        poll_interval,
        timeout,
        contimeout,
        retries,
        low_level_retries,
    )

    run(["systemctl", "daemon-reload"], check=False)
    run(["systemctl", "enable", "--now", unit_name], check=False)

    mounted = False
    for _ in range(15):
        if run_shell(f"mount | grep -qF ' on {mountpoint} '", check=False).returncode == 0:
            mounted = True
            break
        run(["sleep", "2"], check=False)

    if not mounted:
        warn("Mount not present after start. Check service logs.")

    if confirm_default_no("Setup automatic backup cleanup?"):
        retention_days = prompt_default("Retention days", "90")
        write_cleanup_units(site, mountpoint, retention_days)
        run(["systemctl", "daemon-reload"], check=False)
        run(["systemctl", "enable", "--now", f"checkmk-backup-cleanup@{site}.timer"], check=False)
        run(["systemctl", "enable", "--now", f"checkmk-backup-rename@{site}.timer"], check=False)

    log("SETUP COMPLETE (always-on mount).")


def remove_flow() -> None:
    need_cmd("systemctl")
    need_cmd("fusermount3")

    remove_by = prompt_default("Remove by (site/unit)", "site")

    if remove_by == "unit":
        units_res = run_shell("systemctl list-unit-files 'rclone-*.service' --no-legend | awk '{print $1}' | sort -u", check=False)
        units = [u.strip() for u in (units_res.stdout or "").splitlines() if u.strip()]

        if units:
            log("Available rclone units:")
            for idx, unit in enumerate(units, start=1):
                print(f"  [{idx}] {unit}")
            choice = input("Select unit number (or type full unit name): ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(units):
                unit_name = units[int(choice) - 1]
            elif choice.endswith(".service"):
                unit_name = choice
            else:
                die("Invalid input")
        else:
            unit_name = prompt_default("Enter systemd unit name to remove", "rclone-monitoring-spaces.service")

        unit_path = Path("/etc/systemd/system") / unit_name
        mountpoint = ""
        if unit_path.exists():
            text = unit_path.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                if line.startswith("ExecStart=") and " mount " in line:
                    parts = line.split()
                    if "mount" in parts:
                        idx = parts.index("mount")
                        if idx + 2 < len(parts):
                            mountpoint = parts[idx + 2]
                            break

        if not mountpoint:
            mountpoint = prompt_default("Enter mountpoint path to unmount", "/mnt/checkmk-spaces/monitoring")

        mountpoint = normalize_abs_mountpoint(mountpoint)
        stop_unmount_disable(unit_name, mountpoint)

        if unit_path.exists():
            unit_path.unlink()

        run(["systemctl", "daemon-reload"], check=False)

        if confirm_default_no(f"Also remove mountpoint directory {mountpoint}?"):
            shutil.rmtree(mountpoint, ignore_errors=True)

        log("REMOVE COMPLETE.")
        return

    site = pick_site_interactive_or_manual()
    site_home = resolve_site_home(site)
    mountpoint = normalize_abs_mountpoint(prompt_default("Enter EXTERNAL mountpoint path to unmount (absolute)", default_external_mountpoint_for_site(site)))
    assert_mountpoint_outside_site(site_home, mountpoint)

    unit_name = prompt_default("Enter systemd unit name to remove", f"rclone-{site}-spaces.service")
    unit_path = Path("/etc/systemd/system") / unit_name

    cache_dir = prompt_default("Enter rclone cache dir to remove (optional)", default_cache_dir_for_site(site))
    log_file = prompt_default("Enter rclone log file to remove (optional)", default_log_file_for_site(site))

    stop_unmount_disable(unit_name, mountpoint)

    if unit_path.exists():
        unit_path.unlink()

    run(["systemctl", "daemon-reload"], check=False)

    if confirm_default_no(f"Also remove cache dir {cache_dir}?"):
        shutil.rmtree(cache_dir, ignore_errors=True)
    if confirm_default_no(f"Also remove log file {log_file}?"):
        Path(log_file).unlink(missing_ok=True)
    if confirm_default_no(f"Also remove mountpoint directory {mountpoint}?"):
        shutil.rmtree(mountpoint, ignore_errors=True)

    cleanup_files = [
        Path(f"/etc/systemd/system/checkmk-backup-cleanup@{site}.timer"),
        Path(f"/etc/systemd/system/checkmk-backup-cleanup@{site}.service"),
        Path(f"/usr/local/sbin/checkmk_backup_cleanup_{site}.sh"),
        Path(f"/etc/systemd/system/checkmk-backup-rename@{site}.timer"),
        Path(f"/etc/systemd/system/checkmk-backup-rename@{site}.service"),
        Path(f"/usr/local/sbin/checkmk_backup_rename_{site}.sh"),
    ]

    run(["systemctl", "stop", f"checkmk-backup-cleanup@{site}.timer"], check=False)
    run(["systemctl", "disable", f"checkmk-backup-cleanup@{site}.timer"], check=False)
    run(["systemctl", "stop", f"checkmk-backup-rename@{site}.timer"], check=False)
    run(["systemctl", "disable", f"checkmk-backup-rename@{site}.timer"], check=False)

    for file in cleanup_files:
        file.unlink(missing_ok=True)

    run(["systemctl", "daemon-reload"], check=False)
    log("REMOVE COMPLETE.")


def usage() -> None:
    print(
        "Usage:\n"
        "  checkmk_rclone_space_pers.py setup\n"
        "  checkmk_rclone_space_pers.py remove\n"
    )


def main() -> int:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        usage()
        return 0

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("action", nargs="?", default="")
    args = parser.parse_args()

    require_root()

    if args.action == "setup":
        setup_flow()
        return 0
    if args.action == "remove":
        remove_flow()
        return 0
    if args.action in {"", "help"}:
        usage()
        return 0

    die(f"Unknown action: {args.action}. Use: setup|remove")
    return 1


if __name__ == "__main__":
    sys.exit(main())
