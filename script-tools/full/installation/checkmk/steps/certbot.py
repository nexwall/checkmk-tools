from __future__ import annotations

import dataclasses

from lib.common import log_header, log_info, log_success, log_warn, require_root, run as run_cmd, run_capture
from lib.config import InstallerConfig


def install(cfg: InstallerConfig) -> None:
    require_root()
    log_header("50-CERTBOT")
    log_info("Installing certbot...")

    ws = cfg.webserver.strip().lower() or "apache"
    packages = ["certbot"]
    if ws == "apache":
        packages.append("python3-certbot-apache")
    elif ws == "nginx":
        packages.append("python3-certbot-nginx")
    elif ws == "standalone":
        pass
    else:
        raise SystemExit("Invalid WEBSERVER/WS. Use apache|nginx|standalone")
    run_cmd(["apt-get", "install", "-y", *packages])
    log_success("Certbot installed")


def obtain(cfg: InstallerConfig, *, domains: list[str] | None, email: str | None, webserver: str | None) -> None:
    require_root()
    domains = domains or [d.strip() for d in cfg.letsencrypt_domains.split(",") if d.strip()]
    if not domains:
        raise SystemExit("No domains provided. Use --domain or set LETSENCRYPT_DOMAINS")
    email = (email or cfg.letsencrypt_email).strip()
    if not email:
        raise SystemExit("No email provided. Use --email or set LETSENCRYPT_EMAIL")

    ws = (webserver or cfg.webserver).strip().lower() or "apache"
    install(InstallerConfig(**{**cfg.__dict__, "webserver": ws}))

    log_header("50-CERTBOT-RUN")
    base = ["certbot"]
    if ws == "apache":
        base += ["--apache"]
    elif ws == "nginx":
        base += ["--nginx"]
    elif ws == "standalone":
        base += ["certonly", "--standalone"]
    else:
        raise SystemExit("Invalid webserver. Use apache|nginx|standalone")
    for d in domains:
        base += ["-d", d]
    base += ["--non-interactive", "--agree-tos", "--email", email]

    import subprocess as _sp
    result = _sp.run(base)
    if result.returncode != 0:
        log_warn(f"Certbot non ha ottenuto il certificato (exit {result.returncode}).")
        log_warn("Cause tipiche: dominio non punta a questo server, porta 80 non raggiungibile.")
        log_warn("Riprova dopo aver configurato il DNS: ./installer.py certbot run")
        return
    log_success(f"Certificato SSL ottenuto per: {', '.join(domains)}")


def auto(cfg: InstallerConfig) -> None:
    require_root()
    domain = run_capture(["hostname", "-f"], check=False)
    if domain in {"localhost", ""}:
        log_warn("Cannot auto-detect domain; skipping")
        return
    obtain(cfg, domains=[domain], email=None, webserver=None)


def bootstrap_step(cfg: InstallerConfig) -> None:
    """Called during bootstrap. Always installs certbot package.
    Then interactively prompts for domain/email if not configured, and obtains cert.
    User can skip cert issuance and do it later with: ./installer.py certbot run"""
    install(cfg)

    email = cfg.letsencrypt_email.strip()
    domains_str = cfg.letsencrypt_domains.strip()

    # Strip placeholder values
    if email.upper().startswith("INSERISCI_"):
        email = ""
    if domains_str.upper().startswith("INSERISCI_"):
        domains_str = ""

    if not email or not domains_str:
        print("")
        log_header("50-CERTBOT: SSL Certificate")
        log_warn("LETSENCRYPT_EMAIL or LETSENCRYPT_DOMAINS not configured.")
        print("")
        ans = input("Configure SSL certificate now? [y/N]: ").strip().lower()
        if ans not in {"y", "yes"}:
            log_warn("Skipping certificate issuance. Run later: ./installer.py certbot run")
            return

        if not domains_str:
            domains_str = input("Domain(s) comma-separated (e.g. monitor.example.com): ").strip()
        if not email:
            email = input("Let's Encrypt email: ").strip()

        if not domains_str or not email:
            log_warn("Domain or email empty - skipping certificate issuance.")
            log_warn("Run later: ./installer.py certbot run --domain <dom> --email <mail>")
            return

    domains = [d.strip() for d in domains_str.split(",") if d.strip()]
    if not domains:
        log_warn("No valid domains - skipping certificate issuance.")
        return

    cfg_patched = dataclasses.replace(cfg, letsencrypt_email=email, letsencrypt_domains=domains_str)
    try:
        obtain(cfg_patched, domains=domains, email=email, webserver=None)
    except Exception as exc:  # noqa: BLE001
        log_warn(f"Certbot fallito: {exc}")
        log_warn("Puoi riprovare con: ./installer.py certbot run")
