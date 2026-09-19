#!/usr/bin/env python3
"""checkmk_rclone_space_dyn.py

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

VERSION = "1.0.5"  # Versione script (aggiornare ad ogni modifica)
SCRIPT_NAME = Path(__file__).name
SITES_BASE = Path("/opt/omd/sites")
SYSTEMD_DIR = Path("/etc/systemd/system")
WRAPPER_PATH = Path("/usr/local/sbin/checkmk_cloud_backup_push_run.sh")


def log(message: str) -> None:
    print(f"[{dt.datetime.now().strftime('%F %T')}] {message}")


def err(message: str) -> None:
    print(f"[{dt.datetime.now().strftime('%F %T')}] ERROR: {message}", file=sys.stderr)


def die(message: str, code: int = 1) -> None:
    err(message)
    raise SystemExit(code)


def warn(message: str) -> None:
    print(f"WARN: {message}", file=sys.stderr)


def run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def run_shell(command: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-lc", command], check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def need_root() -> None:
    if os.geteuid() != 0:
        die("Run as root.")


def prompt_default(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def prompt_secret(prompt: str) -> str:
    return getpass.getpass(f"{prompt}: ").strip()


def confirm_default_no(prompt: str) -> bool:
    value = input(f"{prompt} [y/N]: ").strip().lower()
    return value == "y"


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def remote_exists(rclone_config: Path, remote_name: str) -> bool:
    env = os.environ.copy()
    env["RCLONE_CONFIG"] = str(rclone_config)
    result = subprocess.run(["rclone", "config", "show", remote_name], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.returncode == 0


def create_or_update_remote_s3(
    rclone_config: Path,
    remote_name: str,
    provider: str,
    access_key: str,
    secret_key: str,
    region: str,
    endpoint: str,
) -> None:
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
    result = subprocess.run(cmd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        die(f"Failed to create/update remote '{remote_name}': {result.stderr.strip()}")


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
        endpoint = prompt_default("AWS S3 endpoint URL (leave default for AWS)", f"https://s3.{region}.amazonaws.com")
        provider = "AWS"

    log(f"Creating/updating rclone remote '{remote_name}' in {rclone_config} ...")
    create_or_update_remote_s3(rclone_config, remote_name, provider, access_key, secret_key, region, endpoint)

    env = os.environ.copy()
    env["RCLONE_CONFIG"] = str(rclone_config)
    test = subprocess.run(["rclone", "lsd", f"{remote_name}:"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if test.returncode != 0:
        warn(f"Remote test 'rclone lsd {remote_name}:' failed. You can verify with: RCLONE_CONFIG={rclone_config} rclone ls {remote_full}")
    else:
        log("Remote test OK.")


def list_sites() -> List[str]:
    if SITES_BASE.is_dir():
        return sorted([p.name for p in SITES_BASE.iterdir() if p.is_dir()])
    return []


def pick_site_interactive() -> str:
    sites = list_sites()
    if not sites:
        die(f"No OMD sites found in {SITES_BASE}")

    log("Available OMD sites:")
    for index, site in enumerate(sites, start=1):
        print(f"  {index}) {site}")

    choice = input("Select site number: ").strip()
    if not choice.isdigit():
        die("Invalid selection.")
    idx = int(choice)
    if idx < 1 or idx > len(sites):
        die("Out of range.")

    return sites[idx - 1]


def write_wrapper() -> None:
    wrapper = r'''#!/usr/bin/env bash
set -euo pipefail

SITE="${1:?missing site}"
REMOTE="${2:?missing remote (e.g. do:bucket)}"
REMOTE_PREFIX="${3:?missing remote prefix (e.g. checkmk/site)}"
BACKUP_DIR="${4:?missing backup dir}"
RCLONE_CONF="${5:?missing rclone conf}"
RETRIES="${6:-3}"
BWLIMIT="${7:-0}"
RETENTION_DAYS_LOCAL="${8:-30}"
RETENTION_DAYS_REMOTE="${9:-90}"

log() { echo "[$(date '+%F %T')] $*"; }
err() { echo "[$(date '+%F %T')] ERROR: $*" >&2; }

SITEHOME="/opt/omd/sites/${SITE}"
LOCKFILE="/run/lock/checkmk-cloud-backup-push-${SITE}.lock"
LOGDIR="/var/log/checkmk-cloud-backup"
mkdir -p "$LOGDIR"

exec 9>"$LOCKFILE"
if ! flock -n 9; then
  err "Another push is running for site=$SITE (lock: $LOCKFILE)."
  exit 2
fi

[[ -d "$SITEHOME" ]] || { err "Site home not found: $SITEHOME"; exit 3; }
[[ -d "$BACKUP_DIR" ]] || { err "Backup dir not found: $BACKUP_DIR"; exit 4; }
[[ -r "$RCLONE_CONF" ]] || { err "rclone.conf not readable: $RCLONE_CONF"; exit 5; }

mapfile -t candidates < <(
  {
    find "$BACKUP_DIR" -maxdepth 1 -type f \
      \( -name '*.tar.gz' -o -name '*.tgz' -o -name '*.tar' -o -name '*.mkbackup' -o -name '*.zip' \) \
      -printf '%T@ %p\n' 2>/dev/null
    find "$BACKUP_DIR" -maxdepth 1 -type d \
      -name 'Check_MK-*' -printf '%T@ %p\n' 2>/dev/null
  } | sort -nr
)

if [[ "${#candidates[@]}" -eq 0 ]]; then
  err "No backup archives or directories found in $BACKUP_DIR"
  exit 6
fi

DEST="${REMOTE%/}/${REMOTE_PREFIX%/}/"
[[ "$REMOTE_PREFIX" == "." || -z "$REMOTE_PREFIX" ]] && DEST="${REMOTE%/}/"
REMOTE_SITE_PATH="${DEST}${SITE}"

COMMON_OPTS=(
  "--config=$RCLONE_CONF"
  "--log-file=${LOGDIR}/push-${SITE}.log"
  "--log-level=INFO"
  "--retries=$RETRIES"
  "--retries-sleep=10s"
  "--low-level-retries=10"
  "--stats=30s"
  "--stats-one-line"
  "--checksum"
)
[[ "$BWLIMIT" != "0" ]] && COMMON_OPTS+=("--bwlimit=$BWLIMIT")

CURRENT_TIME=$(date +%s)
PUSHED=0

# Process ALL candidates (not just the newest) to handle simultaneous backups (e.g. job00+job01)
for entry in "${candidates[@]}"; do
  CANDIDATE_PATH="$(echo "$entry" | cut -d' ' -f2-)"
  CANDIDATE_FILE="$(basename "$CANDIDATE_PATH")"

  if [[ "$CANDIDATE_FILE" =~ -incomplete ]]; then
    log "Skipping incomplete backup: $CANDIDATE_FILE"
    continue
  fi

  LAST_MODIFIED=$(stat -c %Y "$CANDIDATE_PATH" 2>/dev/null || echo "0")
  AGE_SECONDS=$((CURRENT_TIME - LAST_MODIFIED))
  if [[ $AGE_SECONDS -lt 120 ]]; then
    log "Backup too recent (${AGE_SECONDS}s old), waiting for stability: $CANDIDATE_FILE"
    continue
  fi

  if [[ -d "$CANDIDATE_PATH" ]]; then
    BACKUP_SIZE=$(du -sb "$CANDIDATE_PATH" 2>/dev/null | awk '{print $1}')
  else
    BACKUP_SIZE=$(stat -c %s "$CANDIDATE_PATH" 2>/dev/null || echo "0")
  fi
  if [[ $BACKUP_SIZE -lt 102400 ]]; then
    log "Backup too small (${BACKUP_SIZE} bytes), might be incomplete: $CANDIDATE_FILE"
    continue
  fi

  if [[ "$CANDIDATE_FILE" != *"-"[0-9][0-9][0-9][0-9]"-"[0-9][0-9]"-"[0-9][0-9]"-"* ]]; then
    TIMESTAMP="$(date '+%Y-%m-%d-%Hh%M')"
    TIMESTAMPED_NAME="${CANDIDATE_FILE}-${TIMESTAMP}"
    TIMESTAMPED_PATH="${BACKUP_DIR}/${TIMESTAMPED_NAME}"
    log "Renaming backup with timestamp: $CANDIDATE_FILE -> $TIMESTAMPED_NAME"
    if mv "$CANDIDATE_PATH" "$TIMESTAMPED_PATH"; then
      CANDIDATE_PATH="$TIMESTAMPED_PATH"
      CANDIDATE_FILE="$TIMESTAMPED_NAME"
    fi
  fi

  if [[ -d "$CANDIDATE_PATH" ]]; then
    rclone copy "$CANDIDATE_PATH/" "${REMOTE_SITE_PATH}/${CANDIDATE_FILE}/" "${COMMON_OPTS[@]}"
  else
    TMP_NAME=".${CANDIDATE_FILE}.partial"
    REMOTE_TMP="${REMOTE_SITE_PATH}/${TMP_NAME}"
    REMOTE_FINAL="${REMOTE_SITE_PATH}/${CANDIDATE_FILE}"
    rclone copyto "$CANDIDATE_PATH" "$REMOTE_TMP" "${COMMON_OPTS[@]}"
    rclone moveto "$REMOTE_TMP" "$REMOTE_FINAL" "${COMMON_OPTS[@]}" || {
      rclone delete "$REMOTE_TMP" "${COMMON_OPTS[@]}" 2>/dev/null || true
      continue
    }
  fi

  log "Push completed: $CANDIDATE_FILE"
  PUSHED=$((PUSHED + 1))
done

log "Total backups pushed this run: $PUSHED"

if [[ "$RETENTION_DAYS_LOCAL" -gt 0 ]]; then
  mapfile -t all_backups < <(
    {
      find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type f \
        \( -name '*.tar.gz' -o -name '*.tgz' -o -name '*.tar' -o -name '*.mkbackup' -o -name '*.zip' \) \
        -printf '%T@ %p\n' 2>/dev/null
      find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d \
        -name 'Check_MK-*' -printf '%T@ %p\n' 2>/dev/null
    } | sort -nr | cut -d' ' -f2-
  )
  kept=0
  for backup in "${all_backups[@]}"; do
    kept=$((kept + 1))
if [[ $kept -gt $RETENTION_DAYS_LOCAL ]]; then
      rm -rf "$backup" 2>/dev/null || true
    fi
  done
fi

if [[ "$RETENTION_DAYS_REMOTE" -gt 0 ]]; then
  mapfile -t all_remote_backups < <(
    rclone lsf "$REMOTE_SITE_PATH" --dirs-only "${COMMON_OPTS[@]}" 2>/dev/null || true
    rclone lsf "$REMOTE_SITE_PATH" --files-only "${COMMON_OPTS[@]}" 2>/dev/null | grep -E '\.(tgz|tar\.gz|tar|zip)$' || true
  )

  if [[ ${#all_remote_backups[@]} -gt 0 ]]; then
    # Sort by embedded timestamp (YYYY-MM-DD-HHhMM), not by full name - the raw
    # name sorts by job-type label first (e.g. "job01" always lexically ahead
    # of "job00"), which breaks chronological ordering across job types.
    # Retention is applied PER JOB TYPE so job00 (daily) and job01 (weekly)
    # each keep their own newest RETENTION_DAYS_REMOTE backups independently -
    # otherwise a high-frequency job type permanently evicts a low-frequency one.
    mapfile -t job_types < <(printf '%s\n' "${all_remote_backups[@]}" | grep -oE 'job[0-9]+' | sort -u || true)

    for job_type in "${job_types[@]}"; do
      mapfile -t job_backups < <(printf '%s\n' "${all_remote_backups[@]}" | grep -- "-${job_type}-" || true)

      mapfile -t sorted_backups < <(
        for backup in "${job_backups[@]}"; do
          timestamp="$(echo "$backup" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{2}h[0-9]{2}' || true)"
          printf '%s\t%s\n' "$timestamp" "$backup"
        done | sort -r -t $'\t' -k1,1 | cut -f2-
      )

      kept=0
      for backup in "${sorted_backups[@]}"; do
        kept=$((kept + 1))
        if [[ $kept -gt $RETENTION_DAYS_REMOTE ]]; then
          if [[ "$backup" == */ ]]; then
            rclone purge "${REMOTE_SITE_PATH}/${backup%/}" "${COMMON_OPTS[@]}" 2>/dev/null || true
          else
            rclone delete "${REMOTE_SITE_PATH}/${backup}" "${COMMON_OPTS[@]}" 2>/dev/null || true
          fi
        fi
      done
    done
  fi
fi

log "All operations completed."'''
    WRAPPER_PATH.parent.mkdir(parents=True, exist_ok=True)
    WRAPPER_PATH.write_text(wrapper, encoding="utf-8")
    WRAPPER_PATH.chmod(0o755)


def write_systemd_units() -> None:
    service_unit = """[Unit]
Description=Checkmk Cloud Backup Push (rclone) for site %i
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=root
Group=root
EnvironmentFile=-/etc/default/checkmk-cloud-backup-push-%i
Environment=REMOTE=do:testmonbck
Environment=REMOTE_PREFIX=checkmk-backups
Environment=BACKUP_DIR=/var/backups/checkmk
Environment=RCLONE_CONF=/opt/omd/sites/%i/.config/rclone/rclone.conf
Environment=RETRIES=3
Environment=BWLIMIT=0
Environment=RETENTION_DAYS_LOCAL=2
Environment=RETENTION_DAYS_REMOTE=1
ExecStart=/usr/local/sbin/checkmk_cloud_backup_push_run.sh %i \"${REMOTE}\" \"${REMOTE_PREFIX}\" \"${BACKUP_DIR}\" \"${RCLONE_CONF}\" \"${RETRIES}\" \"${BWLIMIT}\" \"${RETENTION_DAYS_LOCAL}\" \"${RETENTION_DAYS_REMOTE}\"
TimeoutStartSec=0
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7

[Install]
WantedBy=multi-user.target"""

    path_unit = """[Unit]
Description=Monitor backup directory for Checkmk site %i

[Path]
PathModified=/var/backups/checkmk
TriggerLimitIntervalSec=1m
TriggerLimitBurst=5
Unit=checkmk-cloud-backup-push@%i.service

[Install]
WantedBy=multi-user.target"""

    timer_unit = """[Unit]
Description=Timer for Checkmk Cloud Backup Push (rclone) for site %i

[Timer]
OnCalendar=*:0/1
Persistent=true
Unit=checkmk-cloud-backup-push@%i.service

[Install]
WantedBy=timers.target"""

    (SYSTEMD_DIR / "checkmk-cloud-backup-push@.service").write_text(service_unit, encoding="utf-8")
    (SYSTEMD_DIR / "checkmk-cloud-backup-push@.path").write_text(path_unit, encoding="utf-8")
    (SYSTEMD_DIR / "checkmk-cloud-backup-push@.timer").write_text(timer_unit, encoding="utf-8")


def write_defaults_file(site: str, remote: str = "do:testmonbck", retention_local: str = "2", retention_remote: str = "1", remote_prefix: str = "checkmk-backups") -> None:
    defaults = Path(f"/etc/default/checkmk-cloud-backup-push-{site}")
    if defaults.exists():
        log(f"Defaults file already exists: {defaults} (not overwriting)")
        return

    text = f"""REMOTE={remote}
REMOTE_PREFIX={remote_prefix}
BACKUP_DIR=/var/backups/checkmk
RCLONE_CONF=/opt/omd/sites/{site}/.config/rclone/rclone.conf
RETRIES=3
BWLIMIT=0
RETENTION_DAYS_LOCAL={retention_local}
RETENTION_DAYS_REMOTE={retention_remote}"""
    defaults.write_text(text, encoding="utf-8")
    defaults.chmod(0o644)
    log(f"Created defaults file: {defaults}")


def check_dependencies() -> None:
    missing = []
    for cmd in ["systemctl", "curl", "du", "awk"]:
        if not command_exists(cmd):
            missing.append(cmd)

    if not missing:
        log("All system dependencies are present")
        return

    log(f"Missing dependencies: {' '.join(missing)}")

    installer = None
    if command_exists("apt-get"):
        installer = ["apt-get", "install", "-y"]
        run(["apt-get", "update", "-qq"], check=False)
    elif command_exists("dnf"):
        installer = ["dnf", "install", "-y"]
    elif command_exists("yum"):
        installer = ["yum", "install", "-y"]

    if installer is None:
        die(f"No supported package manager found. Install manually: {' '.join(missing)}")

    for dep in missing:
        run(installer + [dep], check=False)


def install_rclone_if_missing() -> None:
    if command_exists("rclone"):
        version = run(["rclone", "version"], check=False).stdout.splitlines()
        ver = version[0] if version else "version unknown"
        log(f"rclone is already installed ({ver})")
        return

    log("rclone not found. Installing rclone...")
    result = run_shell("curl -fsSL https://rclone.org/install.sh | bash", check=False)
    if result.returncode != 0 or not command_exists("rclone"):
        die("Failed to install rclone automatically.")


def setup() -> None:
    need_root()
    check_dependencies()
    install_rclone_if_missing()

    sites = list_sites()
    if not sites:
        die(f"No OMD sites found in {SITES_BASE}")

    log(f"Discovered sites: {' '.join(sites)}")

    configured_remote_name = ""
    configured_bucket = ""

    for site in sites:
        rclone_config = Path(f"/opt/omd/sites/{site}/.config/rclone/rclone.conf")
        config_dir = rclone_config.parent
        config_dir.mkdir(parents=True, exist_ok=True)

        if not rclone_config.exists():
            rclone_config.touch()

        run(["chown", "-R", f"{site}:{site}", str(config_dir)], check=False)
        run(["chmod", "700", str(config_dir)], check=False)
        run(["chmod", "600", str(rclone_config)], check=False)

        log(f"Configuring rclone remote for site: {site}")
        if not configured_remote_name:
            configured_remote_name = prompt_default("Enter rclone remote name", "do")
            configured_bucket = prompt_default("Enter bucket name", "testmonbck")

        configured_remote = f"{configured_remote_name}:{configured_bucket}"
        ensure_remote_configured(rclone_config, configured_remote)

        run(["chown", "-R", f"{site}:{site}", str(config_dir)], check=False)
        run(["chmod", "700", str(config_dir)], check=False)
        run(["chmod", "600", str(rclone_config)], check=False)

    log("Installing systemd units and wrapper...")
    write_wrapper()
    write_systemd_units()
    run(["systemctl", "daemon-reload"], check=False)

    backup_dir = Path("/var/backups/checkmk")
    backup_dir.mkdir(parents=True, exist_ok=True)
    run(["chmod", "755", str(backup_dir)], check=False)

    retention_local = prompt_default("Local retention (number of backups)", "2")
    retention_remote = prompt_default("Remote retention (number of backups)", "1")
    remote_prefix = prompt_default("Remote folder name (cartella nel bucket)", "checkmk-backups")

    for site in sites:
        write_defaults_file(site, f"{configured_remote_name}:{configured_bucket}", retention_local, retention_remote, remote_prefix)
        run(["chown", "-R", f"{site}:{site}", str(backup_dir)], check=False)
        run(["systemctl", "enable", "--now", f"checkmk-cloud-backup-push@{site}.timer"], check=False)
        log(f"   {site} - monitoring /var/backups/checkmk")

    log("Setup complete.")


def run_site(site: str = "") -> None:
    need_root()
    selected = site or pick_site_interactive()
    site_home = SITES_BASE / selected
    if not site_home.is_dir():
        die(f"Site not found: {selected}")

    write_defaults_file(selected)
    run(["chown", "-R", f"{selected}:{selected}", "/var/backups/checkmk"], check=False)
    run(["systemctl", "start", f"checkmk-cloud-backup-push@{selected}.service"], check=False)
    run(["systemctl", "enable", "--now", f"checkmk-cloud-backup-push@{selected}.timer"], check=False)

    log(f"Done. Active monitoring enabled for site={selected}")


def remove_site(site: str = "") -> None:
    need_root()
    selected = site or pick_site_interactive()

    for unit in [
        f"checkmk-cloud-backup-push@{selected}.path",
        f"checkmk-cloud-backup-push@{selected}.timer",
        f"checkmk-cloud-backup-push@{selected}.service",
    ]:
        run(["systemctl", "disable", "--now", unit], check=False)
        run(["systemctl", "stop", unit], check=False)

    defaults = Path(f"/etc/default/checkmk-cloud-backup-push-{selected}")
    if defaults.exists():
        defaults.unlink()
        log(f"Removed defaults: {defaults}")

    log("Shared templates remain installed.")


def usage() -> None:
    print(
        f"""Usage:
  {SCRIPT_NAME} setup
  {SCRIPT_NAME} run <site>
  {SCRIPT_NAME} remove <site>"""
    )


def main() -> int:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        usage()
        return 0

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command", nargs="?", default="help")
    parser.add_argument("site", nargs="?")
    args = parser.parse_args()

    if args.command in {"-h", "--help", "help", ""}:
        usage()
        return 0

    if args.command == "setup":
        setup()
        return 0
    if args.command == "run":
        run_site(args.site or "")
        return 0
    if args.command == "remove":
        remove_site(args.site or "")
        return 0

    die(f"Unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
