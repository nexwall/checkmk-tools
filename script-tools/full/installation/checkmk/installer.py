#!/usr/bin/env python3
"""checkmk - Python guided installer (Ubuntu) for CheckMK and related services.

Re-implements the workflow in script-tools/full/installation/install-cmk8/install-cmk/scripts/*.sh in Python.

Version: 1.0.30"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from lib.common import VERSION, log_header, log_info, log_success
from lib.config import config_to_env, load_config, write_dotenv
from steps import (
    apache,
    auto_git_sync,
    backup_jobs,
    certbot,
    checkmk,
    checkmk_auto_upgrade,
    config_backup,
    config_backup_minimal,
    config_backup_ultra_minimal,
    deploy_checks,
    dns_refresh,
    fail2ban,
    firewall,
    log_optimizer,
    notify_scripts,
    ntp,
    packages,
    postfix,
    rclone_setup,
    remove_all,
    ssh,
    system_auto_updates,
    timeshift,
    unattended,
    verify,
    ydea_toolkit,
)


def bootstrap(env_file: Path, interactive: bool) -> None:
    if not env_file.exists() and not interactive:
        raise SystemExit(
            f"Env file not found: {env_file}. Run: ./installer.py init --interactive (or copy .env.example to .env)"
        )

    cfg = load_config(env_file=env_file, interactive=interactive)
    log_header(f"CheckMK Installation Bootstrap (Python v{VERSION})")

    ssh.run(cfg)
    ntp.run(cfg)
    packages.run(cfg)
    unattended.run(cfg)
    postfix.run(cfg)
    firewall.run(cfg)
    fail2ban.run(cfg)
    checkmk.run(cfg)
    dns_refresh.run(cfg)
    deploy_checks.run(cfg)
    auto_git_sync.run(cfg)
    apache.run(cfg)
    notify_scripts.run(cfg)
    certbot.bootstrap_step(cfg)
    ydea_toolkit.run(cfg)
    timeshift.run(cfg)
    system_auto_updates.run(cfg)
    checkmk_auto_upgrade.run(cfg)
    log_optimizer.run(cfg)
    backup_jobs.run(cfg)
    rclone_setup.run(cfg)
    config_backup.run(cfg)
    config_backup_minimal.run(cfg)
    config_backup_ultra_minimal.run(cfg)

    log_header("Installation Complete")
    log_success("CheckMK installation finished")

    log_header("Next Steps")
    if cfg.letsencrypt_email.strip() and cfg.letsencrypt_domains.strip():
        log_info("Certbot: you provided LETSENCRYPT_* values. Run: ./installer.py certbot run (or certbot auto)")
    else:
        log_info("Certbot: configure LETSENCRYPT_EMAIL/LETSENCRYPT_DOMAINS in .env or run with --interactive")
    log_info("Verify: ./installer.py verify")


def init_env(env_file: Path, interactive: bool) -> None:
    cfg = load_config(env_file=env_file, interactive=interactive)
    values = config_to_env(cfg)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    write_dotenv(env_file, values)
    log_success(f"Wrote env file: {env_file}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="installer.py", description="Python guided installer for CheckMK on Ubuntu")
    p.add_argument("--version", action="version", version=f"%(prog)s v{VERSION}")
    # Deliberately outside the repo clone (not Path(__file__).with_name(".env")):
    # /opt/checkmk-tools is kept in sync by auto-git-sync, and a stray sync
    # mechanism installed by install-checkmk-agent-linux.py runs git clean -fd
    # before it gets reconciled away, which wiped an in-repo .env twice during
    # a single bootstrap run (confirmed live on ubntmarzio 2026-08-03). A path
    # under /etc is immune to any git operation on the repo, by construction.
    p.add_argument("--env-file", default="/etc/checkmk-installer.env", help="Path to .env file")
    p.add_argument("--interactive", action="store_true", help="Prompt for key settings")
    sub = p.add_subparsers(dest="cmd", required=False)

    sub.add_parser("menu", help="Interactive menu (default when no command given)")

    # --interactive is also accepted AFTER these subcommands (e.g. "init
    # --interactive", as documented in README.md) using a separate dest so it
    # doesn't clobber the global --interactive flag when given before the
    # subcommand instead - argparse subparser defaults overwrite an
    # already-set same-named attribute, so a shared dest would silently
    # reset "--interactive bootstrap" back to False. See main() for the merge.
    init_p = sub.add_parser("init", help="Create/update .env with a guided prompt")
    init_p.add_argument("--interactive", action="store_true", dest="init_interactive", help="No-op: init always prompts interactively; accepted for convenience")

    boot_p = sub.add_parser("bootstrap", help="Run full installation")
    boot_p.add_argument("--interactive", action="store_true", dest="sub_interactive", help="Prompt for key settings (same as the global --interactive flag)")
    install_p = sub.add_parser("install", help="Alias for bootstrap")
    install_p.add_argument("--interactive", action="store_true", dest="sub_interactive", help="Prompt for key settings (same as the global --interactive flag)")

    sub.add_parser("verify", help="Verify installation")

    rm = sub.add_parser("remove-all", help="Remove CheckMK and related services")
    rm.add_argument("--assume-yes", action="store_true", help="Non-interactive (requires --confirm-hostname)")
    rm.add_argument("--confirm-hostname", default="", help="Hostname that must match (required with --assume-yes)")
    sub.add_parser("remove", help="Alias for remove-all (interactive confirmation)")
    sub.add_parser("deploy-checks", help="Deploy local checks (auto-deploy-checks.py --install-all). Waits for agent path.")

    cert = sub.add_parser("certbot", help="Certbot helpers")
    cert_sub = cert.add_subparsers(dest="cert_cmd", required=True)
    cert_sub.add_parser("install", help="Install certbot and plugin")
    run_p = cert_sub.add_parser("run", help="Obtain certificate")
    run_p.add_argument("--domain", action="append", dest="domains", help="Domain (repeatable)")
    run_p.add_argument("--email", help="Let's Encrypt email")
    run_p.add_argument("--webserver", choices=["apache", "nginx", "standalone"], help="Webserver plugin")
    cert_sub.add_parser("auto", help="Auto-detect domain from hostname -f and run")
    return p


def _require_root_or_reexec() -> None:
    """If not root, print hint and exit. (sudo -E is needed to preserve env)"""
    if not _is_root():
        import sys
        script = Path(__file__).resolve()
        print(f"[ERROR] Root required. Run: sudo -E python3 {script}")
        raise SystemExit(1)


def _menu_loop(env_file: Path) -> int:
    _require_root_or_reexec()

    _raw_env = str(env_file)
    env_display = _raw_env if len(_raw_env) <= 33 else "..." + _raw_env[-30:]
    omd_installed = _is_root() and os.path.exists("/usr/bin/omd")
    status = "INSTALLED" if omd_installed else "not installed"

    # Larghezza interna fissa: W caratteri tra i due ║
    W = 42

    def row(text: str = "") -> str:
        """Line with aligned edges: ║ text.ljust(W-4) ║"""
        return f"║  {text:<{W - 4}}  ║"

    sep_top = "╔" + "═" * W + "╗"
    sep_mid = "╠" + "═" * W + "╣"
    sep_bot = "╚" + "═" * W + "╝"

    while True:
        print("")
        print(sep_top)
        print(row(f"CheckMK Installer  v{VERSION}"))
        print(row(f"env: {env_display}"))
        print(row(f"CheckMK: {status}"))
        print(sep_mid)
        print(row("1) Configure .env  (guided wizard)"))
        print(row("2) Install         (full bootstrap)"))
        print(row("3) Verify installation"))
        print(row("4) SSL certificate (certbot)"))
        print(row("5) Remove / uninstall"))
        print(row("6) Deploy local checks"))
        print(row())
        print(row("0) Exit"))
        print(sep_bot)
        print("")
        try:
            choice = input("  Select [0-6]: ").strip()
        except EOFError:
            return 1

        if choice == "0":
            return 0

        if choice == "1":
            init_env(env_file, interactive=True)

        elif choice == "2":
            bootstrap(env_file, interactive=False)
            omd_installed = os.path.exists("/usr/bin/omd")
            status = "INSTALLED" if omd_installed else "not installed"

        elif choice == "3":
            cfg = load_config(env_file=env_file, interactive=False)
            verify.run(cfg)

        elif choice == "4":
            print("")
            print(" a) Install certbot packages only")
            print(" b) Obtain certificate (interactive)")
            print(" c) Auto-detect domain and obtain")
            print("")
            sub = input("Select [a/b/c]: ").strip().lower()
            cfg = load_config(env_file=env_file, interactive=False)
            if sub == "a":
                certbot.install(cfg)
            elif sub == "b":
                certbot.bootstrap_step(cfg)
            elif sub == "c":
                certbot.auto(cfg)
            else:
                print("Invalid selection")

        elif choice == "5":
            cfg = load_config(env_file=env_file, interactive=False)
            remove_all.run(cfg)
            omd_installed = os.path.exists("/usr/bin/omd")
            status = "INSTALLED" if omd_installed else "not installed"

        elif choice == "6":
            cfg = load_config(env_file=env_file, interactive=False)
            deploy_checks.run(cfg)

        else:
            print("Invalid selection")


def _is_root() -> bool:
    return os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    env_file = Path(args.env_file)
    # --interactive is accepted both before the subcommand (global flag) and
    # after it (bootstrap/install's own --interactive, dest="sub_interactive"
    # to avoid clobbering the global one - see build_parser()).
    interactive = bool(args.interactive) or bool(getattr(args, "sub_interactive", False))

    if args.cmd in {None, "menu"}:
        return _menu_loop(env_file)

    root_required = args.cmd in {"bootstrap", "install", "certbot", "verify", "remove-all", "remove", "deploy-checks"}
    if root_required and not _is_root():
        script_name = Path(__file__).name
        raise SystemExit(
            f"Root required. Run: sudo -E python3 {script_name} {args.cmd}"
        )

    if args.cmd == "init":
        init_env(env_file, interactive=True)
        return 0
    if args.cmd in {"bootstrap", "install"}:
        bootstrap(env_file, interactive)
        return 0
    if args.cmd == "deploy-checks":
        cfg = load_config(env_file=env_file, interactive=False)
        deploy_checks.run(cfg)
        return 0
    if args.cmd == "verify":
        cfg = load_config(env_file=env_file, interactive=False)
        return verify.run(cfg)
    if args.cmd in {"remove-all", "remove"}:
        cfg = load_config(env_file=env_file, interactive=False)
        remove_all.run(
            cfg,
            assume_yes=bool(getattr(args, "assume_yes", False)),
            confirm_hostname=str(getattr(args, "confirm_hostname", "") or "").strip(),
        )
        return 0
    if args.cmd == "certbot":
        cfg = load_config(env_file=env_file, interactive=interactive)
        if args.cert_cmd == "install":
            certbot.install(cfg)
            return 0
        if args.cert_cmd == "run":
            certbot.obtain(cfg, domains=args.domains, email=args.email, webserver=args.webserver)
            return 0
        if args.cert_cmd == "auto":
            certbot.auto(cfg)
            return 0
    raise SystemExit("Unhandled command")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
