#!/usr/bin/env python3
"""checkmk_rclone_spaces.py

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
    need_cmd("curl")

    if shutil.which("rclone"):
        version = run(["rclone", "version"], check=False).stdout.splitlines()
        log(f"rclone is already installed: {version[0] if version else 'version unknown'}")
        log("Skipping installation. To force reinstall, remove rclone first.")
        return

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

    version = run(["rclone", "version"], check=False).stdout.splitlines()
    log(f"Installed: {version[0] if version else 'version unknown'}")


def ensure_fuse_allow_other() -> None:
    log("Ensuring /etc/fuse.conf enables user_allow_other...")

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

    verify = fuse_conf.read_text(encoding="utf-8", errors="ignore")
    if "\nuser_allow_other\n" in f"\n{verify}\n":
        log("fuse.conf configured successfully.")
    else:
        warn("Could not verify user_allow_other in fuse.conf, but continuing...")


def normalize_abs_mountpoint(mountpoint: str) -> str:
    mp = mountpoint.strip().rstrip("/")
    if not mp:
        die("Mountpoint cannot be empty.")
    if not mp.startswith("/"):
        die("Mountpoint must be an ABSOLUTE path (start with '/').")
    if ".." in mp:
        die("Mountpoint cannot contain '..'.")
    if mp in {"", "/"}:
        die(f"Refusing mountpoint '{mp}'.")
    return mp


def assert_mountpoint_outside_site(site_home: Path, mountpoint: str) -> None:
    site_home_str = str(site_home)
    if mountpoint == site_home_str or mountpoint.startswith(site_home_str + "/"):
        die(f"Mountpoint must be EXTERNAL to the site. Refusing: {mountpoint} (site_home={site_home})")


def default_external_mountpoint_for_site(site: str) -> str:
    return f"{DEFAULT_EXTERNAL_MOUNT_BASE}/{site}"


def remote_exists(rclone_config: Path, remote_name: str) -> bool:
    env = os.environ.copy()
    env["RCLONE_CONFIG"] = str(rclone_config)
    result = subprocess.run(["rclone", "config", "show", remote_name], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.returncode == 0


def create_or_update_remote_s3(rclone_config: Path, remote_name: str, provider: str, access_key: str, secret_key: str, region: str, endpoint: str) -> None:
    log(f"Creating/updating rclone remote '{remote_name}' in {rclone_config} ...")
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
        die(f"Remote must be in form name:bucket (e.g. do:mybucket). Got: {remote_full}")

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
        region = prompt_default("DO Spaces region (e.g. nyc3, fra1, ams3)", "fra1")
        endpoint = prompt_default("DO Spaces endpoint URL", f"https://{region}.digitaloceanspaces.com")
        provider = "DigitalOcean"
    else:
        region = prompt_default("AWS region (e.g. eu-west-1)", "eu-west-1")
        endpoint = prompt_default("AWS S3 endpoint URL (leave default for AWS)", f"https://s3.{region}.amazonaws.com")
        provider = "AWS"

    create_or_update_remote_s3(rclone_config, remote_name, provider, access_key, secret_key, region, endpoint)

    log("Testing remote connectivity (may fail if bucket ACL/policy blocks list):")
    env = os.environ.copy()
    env["RCLONE_CONFIG"] = str(rclone_config)
    test = subprocess.run(["rclone", "lsd", f"{remote_name}:"], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if test.returncode != 0:
        warn(f"Remote test 'rclone lsd {remote_name}:' failed. Credentials may still be valid, but list may be blocked. You can verify with: RCLONE_CONFIG={rclone_config} rclone ls {remote_full}")
    else:
        log("Remote test OK.")


def write_unit(unit_path: Path, unit_name: str, site: str, site_user: str, site_group: str, rclone_config: Path, rclone_bin: str, remote: str, mountpoint: str) -> None:
    log(f"Writing systemd unit: {unit_name} to {unit_path}")
    log(f"Unit parameters: site={site}, user={site_user}, group={site_group}, remote={remote}, mountpoint={mountpoint}")

    uid = run(["id", "-u", site_user], check=False).stdout.strip() or "0"
    gid = run(["id", "-g", site_group], check=False).stdout.strip() or "0"

    unit = f"""[Unit]
Description=Rclone mount {remote} for Checkmk site {site} (external mountpoint)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={site_user}
Group={site_group}
Environment=RCLONE_CONFIG={rclone_config}
ExecStart={rclone_bin} mount {remote} {mountpoint} --allow-other --uid {uid} --gid {gid} --umask 002 --vfs-cache-mode writes
ExecStop=/bin/fusermount3 -u {mountpoint}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target"""

    unit_path.write_text(unit, encoding="utf-8")
    if not unit_path.exists():
        die(f"Failed to write unit file: {unit_path}")

    lines_count = len(unit.splitlines())
    log(f"Unit file written successfully ({lines_count} lines)")


def stop_unmount_disable(unit_name: str, mountpoint: str) -> None:
    run(["systemctl", "stop", unit_name], check=False)
    run(["systemctl", "disable", unit_name], check=False)
    if run_shell(f"mount | grep -qF ' on {mountpoint} '", check=False).returncode == 0:
        run(["fusermount3", "-u", mountpoint], check=False)


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
        warn(f"Group '{site_group}' not found; using primary group of {site_user}.")
        site_group = run(["id", "-gn", site_user], check=False).stdout.strip() or site_user

    rclone_config = site_home / ".config" / "rclone" / "rclone.conf"
    if not rclone_config.exists():
        warn(f"rclone config not found at {rclone_config}.")
        rclone_config = Path(prompt_default("Enter full path to rclone.conf for site", str(rclone_config)))
        if not rclone_config.exists():
            die(f"rclone config still not found: {rclone_config}")

    log(f"Checking permissions for rclone config: {rclone_config}")
    config_dir = rclone_config.parent

    if config_dir.is_dir():
        run(["chown", "-R", f"{site_user}:{site_group}", str(config_dir)], check=False)
        run(["chmod", "755", str(config_dir)], check=False)
        parent = config_dir.parent
        run(["chown", f"{site_user}:{site_group}", str(parent)], check=False)
        run(["chmod", "755", str(parent)], check=False)

    if rclone_config.exists():
        run(["chown", f"{site_user}:{site_group}", str(rclone_config)], check=False)
        run(["chmod", "600", str(rclone_config)], check=False)
        ls = run(["ls", "-la", str(rclone_config)], check=False)
        if ls.stdout:
            log(f"Fixed permissions: {ls.stdout.strip()}")

    remote = prompt_default("Enter rclone remote (format name:bucket)", DEFAULT_REMOTE)
    ensure_remote_configured(rclone_config, remote)

    mp_default = default_external_mountpoint_for_site(site)
    mountpoint = normalize_abs_mountpoint(prompt_default("Enter EXTERNAL mountpoint path (absolute)", mp_default))
    assert_mountpoint_outside_site(site_home, mountpoint)

    unit_name = prompt_default("Enter systemd unit name", f"rclone-{site}-spaces.service")
    unit_path = Path("/etc/systemd/system") / unit_name

    log("Summary:")
    print(f"  Site:          {site}")
    print(f"  Site home:     {site_home}")
    print(f"  Run as user:   {site_user}:{site_group}")
    print(f"  rclone config: {rclone_config}")
    print(f"  Remote:        {remote}")
    print(f"  Mountpoint:    {mountpoint}")
    print(f"  Unit:          {unit_name}")
    print()

    install_rclone_stable()
    ensure_fuse_allow_other()

    log(f"Creating mountpoint directory: {mountpoint}")
    Path(mountpoint).mkdir(parents=True, exist_ok=True)
    run(["chown", f"{site_user}:{site_group}", mountpoint], check=False)
    run(["chmod", "2775", mountpoint], check=False)
    log("Mountpoint directory created and configured.")

    rclone_bin = shutil.which("rclone")
    if not rclone_bin:
        die("rclone binary not executable")
    log(f"Using rclone binary: {rclone_bin}")

    log("Stopping and disabling any existing service...")
    stop_unmount_disable(unit_name, mountpoint)

    log("Creating systemd unit file...")
    write_unit(unit_path, unit_name, site, site_user, site_group, rclone_config, rclone_bin, remote, mountpoint)

    if not unit_path.exists():
        die(f"Failed to create unit file: {unit_path}")
    log(f"Unit file created successfully: {unit_path}")

    log("Reloading systemd daemon...")
    run(["systemctl", "daemon-reload"], check=False)

    log(f"Enabling and starting service: {unit_name}")
    run(["systemctl", "enable", "--now", unit_name], check=False)

    run(["sleep", "2"], check=False)

    log("Service status:")
    status = run(["systemctl", "status", unit_name, "--no-pager", "-l"], check=False)
    if status.stdout:
        print(status.stdout.strip())
    if status.stderr:
        print(status.stderr.strip(), file=sys.stderr)

    log("Mount check:")
    mount_chk = run_shell(f"mount | grep -F '{mountpoint}'", check=False)
    if mount_chk.returncode == 0:
        if mount_chk.stdout:
            print(mount_chk.stdout.strip())
        log("Mount verified successfully.")
    else:
        warn("Mount not present after service start. Checking service status...")
        status2 = run(["systemctl", "status", unit_name, "--no-pager", "-l"], check=False)
        if status2.stdout:
            print(status2.stdout.strip())
        journal = run(["journalctl", "-u", unit_name, "-n", "50", "--no-pager"], check=False)
        if journal.stdout:
            print(journal.stdout.strip())
        die("Mount not present after service start.")

    log(f"Smoke test as {site_user}:")
    smoke = run(["su", "-", site_user, "-c", f"cd '{mountpoint}' && ls -la . | head -n 20"], check=False)
    if smoke.returncode == 0:
        if smoke.stdout:
            print(smoke.stdout.strip())
        log("Smoke test passed.")
    else:
        warn("Smoke test failed. Service may still be starting up.")

    log("SETUP COMPLETE.")


def remove_flow() -> None:
    need_cmd("systemctl")
    need_cmd("fusermount3")

    log("Remove mode: you can remove by selecting a site OR by specifying a unit directly.")
    remove_by = prompt_default("Remove by (site/unit)", "site")

    if remove_by == "unit":
        units_res = run_shell("systemctl list-unit-files 'rclone-*.service' --no-legend | awk '{print $1}' | sort -u", check=False)
        units = [u.strip() for u in (units_res.stdout or "").splitlines() if u.strip()]

        if units:
            log("Available rclone units:")
            for idx, unit in enumerate(units, start=1):
                print(f"  [{idx}] {unit}")

            while True:
                choice = input("Select unit number (or type full unit name): ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(units):
                    unit_name = units[int(choice) - 1]
                    break
                if choice.startswith("rclone-") and choice.endswith(".service"):
                    unit_name = choice
                    break
                warn("Invalid input.")
        else:
            warn("No rclone-*.service units found. Proceeding with manual entry.")
            unit_name = prompt_default("Enter systemd unit name to remove", "rclone-testmonbck.service")

        exec_show = run(["systemctl", "show", "-p", "ExecStart", "--value", unit_name], check=False).stdout or ""
        mountpoint = ""
        parts = exec_show.split()
        for i, token in enumerate(parts):
            if token == "mount" and i + 2 < len(parts):
                mountpoint = parts[i + 2]
                break

        if not mountpoint:
            warn("Could not parse mountpoint from unit ExecStart. Asking manually.")
            mountpoint = prompt_default("Enter mountpoint path to unmount", "/mnt/checkmk-spaces/monitoring")

        mountpoint = normalize_abs_mountpoint(mountpoint)
        unit_path = Path("/etc/systemd/system") / unit_name

        log(f"Removing unit: {unit_name}")
        log(f"Mountpoint: {mountpoint}")

        stop_unmount_disable(unit_name, mountpoint)

        if unit_path.exists():
            unit_path.unlink()
            log(f"Removed unit file: {unit_path}")
        else:
            warn(f"Unit file not found: {unit_path}")

        run(["systemctl", "daemon-reload"], check=False)
        log("REMOVE COMPLETE.")
        return

    site = pick_site_interactive_or_manual()
    site_home = resolve_site_home(site)

    mp_default = default_external_mountpoint_for_site(site)
    mountpoint = normalize_abs_mountpoint(prompt_default("Enter EXTERNAL mountpoint path to unmount (absolute)", mp_default))
    assert_mountpoint_outside_site(site_home, mountpoint)

    unit_name = prompt_default("Enter systemd unit name to remove", f"rclone-{site}-spaces.service")
    unit_path = Path("/etc/systemd/system") / unit_name

    log("Removing:")
    print(f"  Site:       {site}")
    print(f"  Site home:  {site_home}")
    print(f"  Mountpoint: {mountpoint}")
    print(f"  Unit:       {unit_name}")
    print()

    stop_unmount_disable(unit_name, mountpoint)

    if unit_path.exists():
        unit_path.unlink()
        log(f"Removed unit file: {unit_path}")
    else:
        warn(f"Unit file not found: {unit_path}")

    run(["systemctl", "daemon-reload"], check=False)
    log("REMOVE COMPLETE.")


def usage() -> None:
    print(
        "Usage:\n"
        "  checkmk_rclone_spaces.py setup\n"
        "  checkmk_rclone_spaces.py remove\n"
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
