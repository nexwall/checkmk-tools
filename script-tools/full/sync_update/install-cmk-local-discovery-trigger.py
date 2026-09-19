#!/usr/bin/env python3
"""install-cmk-local-discovery-trigger.py

Systemd installer for cmk-local-discovery-trigger.py with production guardrails.

Create:
- /etc/systemd/system/checkmk-local-discovery-trigger.service
- /etc/systemd/system/checkmk-local-discovery-trigger.timer

Version: 1.3.0"""

import argparse
import grp
import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

VERSION = "1.4.0"
SYSTEMD_DIR = Path("/etc/systemd/system")
SERVICE_NAME = "checkmk-local-discovery-trigger.service"
TIMER_NAME = "checkmk-local-discovery-trigger.timer"
DEFAULT_SCRIPT = Path("/opt/checkmk-tools/script-tools/full/sync_update/cmk-local-discovery-trigger.py")
DEFAULT_LOG_FILE = Path("/var/log/checkmk_server_autoheal.log")
DEFAULT_REPO_DIR = Path("/opt/checkmk-tools")
DEFAULT_AUTO_SYNC_SCRIPT = Path("/opt/checkmk-tools/script-tools/full/sync_update/auto_git_sync.py")
AUTO_SYNC_SERVICE_NAME = "auto-git-sync.service"
DEFAULT_AUTO_SYNC_LOG_FILE = Path("/var/log/auto-git-sync.log")


def run(cmd: List[str]) -> None:
    subprocess.run(cmd, check=True)


def run_best_effort(cmd: List[str]) -> bool:
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def require_root() -> None:
    if os.geteuid() != 0:
        print("[ERROR] Eseguire come root", file=sys.stderr)
        sys.exit(1)


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def ensure_log_file(log_file: Path, run_as_user: str, run_as_group: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.touch(exist_ok=True)

    uid = pwd.getpwnam(run_as_user).pw_uid
    gid = grp.getgrnam(run_as_group).gr_gid
    os.chown(log_file, uid, gid)
    os.chmod(log_file, 0o664)


def detect_default_site() -> str:
    sites_root = Path("/opt/omd/sites")
    if not sites_root.exists():
        return "monitoring"

    monitoring_site = sites_root / "monitoring"
    if monitoring_site.exists() and monitoring_site.is_dir():
        return "monitoring"

    candidates = sorted([p.name for p in sites_root.iterdir() if p.is_dir()])
    if candidates:
        return candidates[0]
    return "monitoring"


def resolve_runtime_identity(site: str, run_as_user: str, run_as_group: str) -> tuple[str, str]:
    selected_user = run_as_user.strip() if run_as_user else ""
    selected_group = run_as_group.strip() if run_as_group else ""

    if not selected_user:
        try:
            pwd.getpwnam(site)
            selected_user = site
        except KeyError:
            selected_user = "root"

    if not selected_group:
        try:
            grp.getgrnam(selected_user)
            selected_group = selected_user
        except KeyError:
            selected_group = "root"

    return selected_user, selected_group


def install_git_if_missing() -> None:
    if shutil.which("git"):
        return

    if shutil.which("apt-get"):
        run_best_effort(["apt-get", "update", "-qq"])
        run(["apt-get", "install", "-y", "git"])
        return

    if shutil.which("dnf"):
        run_best_effort(["dnf", "-y", "makecache"])
        run(["dnf", "install", "-y", "git"])
        return

    if shutil.which("yum"):
        run_best_effort(["yum", "-y", "makecache"])
        run(["yum", "install", "-y", "git"])
        return

    raise RuntimeError("Package manager non supportato per installare git")


def setup_auto_git_sync(
    run_as_user: str,
    run_as_group: str,
    repo_dir: Path,
    auto_sync_script: Path,
    auto_sync_interval: int,
    auto_sync_log_file: Path,
) -> Path:
    if not auto_sync_script.exists():
        raise RuntimeError(f"Script auto git sync non trovato: {auto_sync_script}")

    if not repo_dir.exists():
        raise RuntimeError(f"Repository locale non trovato: {repo_dir}")

    ensure_log_file(auto_sync_log_file, run_as_user, run_as_group)

    service_content = f"""[Unit]
Description=Auto Git Sync for checkmk-tools
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={run_as_user}
Group={run_as_group}
Environment=TARGET_DIR={repo_dir}
Environment=SYNC_INTERVAL={auto_sync_interval}
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 {auto_sync_script} {auto_sync_interval}
Restart=always
RestartSec=15
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target"""

    service_path = SYSTEMD_DIR / AUTO_SYNC_SERVICE_NAME
    write_text(service_path, service_content)

    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", AUTO_SYNC_SERVICE_NAME])
    run(["systemctl", "restart", AUTO_SYNC_SERVICE_NAME])
    return service_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Installa service/timer guardrail per local discovery trigger")
    parser.add_argument("--site", default="", help="Nome site OMD (auto-detect se omesso)")
    parser.add_argument("--run-as-user", default="", help="Utente systemd del servizio (auto-detect se omesso)")
    parser.add_argument("--run-as-group", default="", help="Gruppo systemd del servizio (auto-detect se omesso)")
    parser.add_argument("--script-path", default=str(DEFAULT_SCRIPT), help="Path script cmk-local-discovery-trigger.py")
    parser.add_argument("--agent-timeout", type=int, default=90, help="Timeout per host cmk -d in secondi")
    parser.add_argument("--detect-plugins", default="local", help="Plugin target per discovery (default: local)")
    parser.add_argument(
        "--no-activate",
        action="store_true",
        help="Disabilita 'cmk -O' al termine (default: abilitato su discovery riuscita)",
    )
    parser.add_argument("--interval-min", type=int, default=5, help="Intervallo timer in minuti")
    parser.add_argument("--boot-delay-min", type=int, default=3, help="Delay run dopo boot in minuti")
    parser.add_argument("--timeout-start-min", type=int, default=25, help="TimeoutStartSec in minuti")
    parser.add_argument("--runtime-max-min", type=int, default=25, help="RuntimeMaxSec in minuti")
    parser.add_argument("--accuracy-sec", type=int, default=60, help="AccuracySec del timer")
    parser.add_argument("--hosts", default="", help="Lista host separati da virgola (vuoto = tutti gli host del site)")
    parser.add_argument("--debug", action="store_true", help="Abilita log debug dettagliati nel trigger")
    parser.add_argument(
        "--log-file",
        default=str(DEFAULT_LOG_FILE),
        help="Path log unificato autoheal (default: /var/log/checkmk_server_autoheal.log)",
    )
    parser.add_argument(
        "--setup-auto-sync-git",
        action="store_true",
        help="Installa/aggiorna git e configura auto-git-sync.service per /opt/checkmk-tools.",
    )
    parser.add_argument(
        "--auto-sync-interval-sec",
        type=int,
        default=60,
        help="Intervallo in secondi auto-git-sync (default: 60)",
    )
    parser.add_argument(
        "--repo-dir",
        default=str(DEFAULT_REPO_DIR),
        help="Path repository locale checkmk-tools (default: /opt/checkmk-tools)",
    )
    parser.add_argument(
        "--auto-sync-script-path",
        default=str(DEFAULT_AUTO_SYNC_SCRIPT),
        help="Path script auto_git_sync.py (default: /opt/checkmk-tools/script-tools/full/sync_update/auto_git_sync.py)",
    )
    parser.add_argument(
        "--auto-sync-log-file",
        default=str(DEFAULT_AUTO_SYNC_LOG_FILE),
        help="Path log auto git sync (default: /var/log/auto-git-sync.log)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Preset rapido consigliato: auto-detect site/user/group + timer 5 min.",
    )
    return parser.parse_args()


def is_checkmk_server() -> bool:
    """Verify that this is a CheckMK server (omd + cmk present)."""
    return shutil.which("omd") is not None and shutil.which("cmk") is not None


def main() -> int:
    args = parse_args()
    require_root()

    # Guardrail: This script should ONLY be run on CheckMK servers, not monitored hosts
    if not is_checkmk_server():
        print("[ERROR] Questo non è un server CheckMK (omd/cmk non trovati).", file=sys.stderr)
        print("[ERROR] Il discovery trigger va installato SOLO sul server CheckMK, non sugli host monitorati.", file=sys.stderr)
        return 1

    if args.quick and not args.site:
        args.site = detect_default_site()

    if not args.site:
        args.site = detect_default_site()

    run_as_user, run_as_group = resolve_runtime_identity(args.site, args.run_as_user, args.run_as_group)

    script_path = Path(args.script_path)
    if not script_path.exists():
        print(f"[ERROR] Script non trovato: {script_path}", file=sys.stderr)
        return 1

    log_file = Path(args.log_file)
    try:
        ensure_log_file(log_file, run_as_user, run_as_group)
    except KeyError as exc:
        print(f"[ERROR] Utente/gruppo non valido per ownership log: {exc}", file=sys.stderr)
        return 1
    except PermissionError as exc:
        print(f"[ERROR] Permessi insufficienti per creare log file {log_file}: {exc}", file=sys.stderr)
        return 1

    exec_cmd = [
        "/usr/bin/python3",
        str(script_path),
        "--site",
        args.site,
        "--agent-timeout",
        str(args.agent_timeout),
        "--detect-plugins",
        args.detect_plugins,
    ]

    if not args.no_activate:
        exec_cmd.append("--activate")

    if args.hosts.strip():
        exec_cmd.extend(["--hosts", args.hosts.strip()])

    if args.debug:
        exec_cmd.append("--debug")

    service_content = f"""[Unit]
Description=CheckMK local services change detector (discovery trigger)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User={run_as_user}
Group={run_as_group}
Environment=CHECKMK_AUTOHEAL_LOG_FILE={log_file}
ExecStart={' '.join(exec_cmd)}
TimeoutStartSec={args.timeout_start_min}min
RuntimeMaxSec={args.runtime_max_min}min
NoNewPrivileges=true"""

    timer_content = f"""[Unit]
Description=Run CheckMK local services change detector every {args.interval_min} minutes

[Timer]
OnBootSec={args.boot_delay_min}min
OnUnitActiveSec={args.interval_min}min
Persistent=true
AccuracySec={args.accuracy_sec}s

[Install]
WantedBy=timers.target"""

    service_path = SYSTEMD_DIR / SERVICE_NAME
    timer_path = SYSTEMD_DIR / TIMER_NAME

    write_text(service_path, service_content)
    write_text(timer_path, timer_content)

    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", TIMER_NAME])
    run(["systemctl", "restart", TIMER_NAME])
    run(["systemctl", "start", SERVICE_NAME])

    auto_sync_service_path = None
    if args.setup_auto_sync_git:
        try:
            install_git_if_missing()
            auto_sync_service_path = setup_auto_git_sync(
                run_as_user=run_as_user,
                run_as_group=run_as_group,
                repo_dir=Path(args.repo_dir),
                auto_sync_script=Path(args.auto_sync_script_path),
                auto_sync_interval=args.auto_sync_interval_sec,
                auto_sync_log_file=Path(args.auto_sync_log_file),
            )
        except RuntimeError as exc:
            print(f"[ERROR] Setup auto sync git fallito: {exc}", file=sys.stderr)
            return 1

    print(f"[OK] install-cmk-local-discovery-trigger.py v{VERSION}")
    print(f"[OK] Service: {service_path}")
    print(f"[OK] Timer:   {timer_path}")
    print(f"[OK] Site:    {args.site}")
    print(f"[OK] RunAs:   {run_as_user}:{run_as_group}")
    print(f"[OK] Log:     {log_file}")
    if auto_sync_service_path:
        print(f"[OK] AutoSync Service: {auto_sync_service_path}")
        print(f"[OK] AutoSync Log:     {args.auto_sync_log_file}")
    print(f"[OK] Verifica: systemctl status {SERVICE_NAME} --no-pager")
    print(f"[OK] Verifica: systemctl list-timers --all | grep {TIMER_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
