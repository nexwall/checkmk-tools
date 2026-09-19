from __future__ import annotations

import os
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path


def parse_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
            value = value[1:-1]
        else:
            # Strip inline comments for unquoted values (dotenv common pattern: KEY=value  # comment)
            if "#" in value:
                value = value.split("#", 1)[0].rstrip()
        data[key] = value
    return data


def parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    v = value.strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    return default


def prompt_str(prompt: str, *, default: str | None = None) -> str:
    if default is not None and default != "":
        ans = input(f"{prompt} [{default}]: ").strip()
        return ans or default
    return input(f"{prompt}: ").strip()


def prompt_int(prompt: str, *, default: int) -> int:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            print("Please enter a valid integer.")


@dataclass(frozen=True)
class InstallerConfig:
    timezone: str
    ssh_port: int
    permit_root_login: str
    client_alive_interval: int
    client_alive_countmax: int
    login_grace_time: int
    root_password: str
    open_http_https: bool
    letsencrypt_email: str
    letsencrypt_domains: str
    webserver: str
    ntp_servers: list[str]
    checkmk_admin_password: str
    checkmk_deb_url: str
    cmk_version: str
    site_name: str
    redirect_to_site: bool
    deploy_local_checks: bool
    enable_auto_git_sync: bool
    auto_git_sync_interval_sec: int
    auto_git_sync_repo_url: str
    auto_git_sync_target_dir: str
    smtp_relayhost: str
    smtp_relay_user: str
    smtp_relay_password: str
    smtp_from_address: str
    fail2ban_ignoreip: str  # space-separated IPs/CIDRs to whitelist


def config_to_env(cfg: InstallerConfig) -> dict[str, str]:
    return {
        "TIMEZONE": cfg.timezone,
        "SSH_PORT": str(cfg.ssh_port),
        "PERMIT_ROOT_LOGIN": cfg.permit_root_login,
        "CLIENT_ALIVE_INTERVAL": str(cfg.client_alive_interval),
        "CLIENT_ALIVE_COUNTMAX": str(cfg.client_alive_countmax),
        "LOGIN_GRACE_TIME": str(cfg.login_grace_time),
        # Intentionally do not persist passwords by default
        "ROOT_PASSWORD": "",
        "OPEN_HTTP_HTTPS": "true" if cfg.open_http_https else "false",
        "LETSENCRYPT_EMAIL": cfg.letsencrypt_email,
        "LETSENCRYPT_DOMAINS": cfg.letsencrypt_domains,
        "WEBSERVER": cfg.webserver,
        "NTP_SERVERS": " ".join(cfg.ntp_servers),
        # Intentionally do not persist passwords by default
        "CHECKMK_ADMIN_PASSWORD": "",
        "CHECKMK_DEB_URL": cfg.checkmk_deb_url,
        "CMK_VERSION": cfg.cmk_version,
        "SITE_NAME": cfg.site_name,
        "REDIRECT_TO_SITE": "true" if cfg.redirect_to_site else "false",
        "DEPLOY_LOCAL_CHECKS": "true" if cfg.deploy_local_checks else "false",
        "ENABLE_AUTO_GIT_SYNC": "true" if cfg.enable_auto_git_sync else "false",
        "AUTO_GIT_SYNC_INTERVAL_SEC": str(cfg.auto_git_sync_interval_sec),
        "AUTO_GIT_SYNC_REPO_URL": cfg.auto_git_sync_repo_url,
        "AUTO_GIT_SYNC_TARGET_DIR": cfg.auto_git_sync_target_dir,
        "SMTP_RELAYHOST": cfg.smtp_relayhost,
        "SMTP_RELAY_USER": cfg.smtp_relay_user,
        # Intentionally do not persist relay password by default
        "SMTP_RELAY_PASSWORD": "",
        "SMTP_FROM_ADDRESS": cfg.smtp_from_address,
        "FAIL2BAN_IGNOREIP": cfg.fail2ban_ignoreip,
    }


def write_dotenv(path: Path, values: dict[str, str]) -> None:
    lines: list[str] = []
    for key, value in values.items():
        if any(ch.isspace() for ch in value):
            lines.append(f'{key}="{value}"')
        else:
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_config(*, env_file: Path, interactive: bool) -> InstallerConfig:
    env_from_file = parse_dotenv(env_file)
    env = {**env_from_file, **os.environ}

    def getv(key: str, default: str = "") -> str:
        return str(env.get(key, default)).strip()

    timezone = getv("TIMEZONE", "Europe/Rome")
    ssh_port = int(getv("SSH_PORT", "22") or "22")
    permit_root_login = getv("PERMIT_ROOT_LOGIN", "prohibit-password")
    client_alive_interval = int(getv("CLIENT_ALIVE_INTERVAL", "600") or "600")
    client_alive_countmax = int(getv("CLIENT_ALIVE_COUNTMAX", "2") or "2")
    login_grace_time = int(getv("LOGIN_GRACE_TIME", "30") or "30")
    root_password = getv("ROOT_PASSWORD", "")
    open_http_https = parse_bool(getv("OPEN_HTTP_HTTPS", "true"), default=True)
    letsencrypt_email = getv("LETSENCRYPT_EMAIL", "")
    letsencrypt_domains = getv("LETSENCRYPT_DOMAINS", "")
    webserver = getv("WEBSERVER", getv("WS", "apache"))
    ntp_raw = getv("NTP_SERVERS", "0.pool.ntp.org 1.pool.ntp.org 2.pool.ntp.org 3.pool.ntp.org")
    ntp_servers = [s for s in ntp_raw.split() if s]
    checkmk_admin_password = getv("CHECKMK_ADMIN_PASSWORD", "")
    checkmk_deb_url = getv("CHECKMK_DEB_URL", "")
    cmk_version = getv("CMK_VERSION", getv("CHECKMK_VERSION", "latest"))
    site_name = getv("SITE_NAME", getv("CHECKMK_SITE", "monitoring"))
    redirect_to_site = parse_bool(getv("REDIRECT_TO_SITE", "true"), default=True)

    deploy_local_checks = parse_bool(getv("DEPLOY_LOCAL_CHECKS", "true"), default=True)
    enable_auto_git_sync = parse_bool(getv("ENABLE_AUTO_GIT_SYNC", "true"), default=True)
    auto_git_sync_interval_sec = int(getv("AUTO_GIT_SYNC_INTERVAL_SEC", "60") or "60")
    auto_git_sync_repo_url = getv("AUTO_GIT_SYNC_REPO_URL", "https://github.com/nethesis/checkmk-tools.git")
    auto_git_sync_target_dir = getv("AUTO_GIT_SYNC_TARGET_DIR", "/opt/checkmk-tools")
    smtp_relayhost = getv("SMTP_RELAYHOST", "")
    smtp_relay_user = getv("SMTP_RELAY_USER", "")
    smtp_relay_password = getv("SMTP_RELAY_PASSWORD", "")
    smtp_from_address = getv("SMTP_FROM_ADDRESS", "")
    fail2ban_ignoreip = getv("FAIL2BAN_IGNOREIP", "")

    if interactive:
        timezone = prompt_str("Timezone", default=timezone)
        ssh_port = prompt_int("SSH Port", default=ssh_port)
        permit_root_login = prompt_str("PermitRootLogin (yes|no|prohibit-password)", default=permit_root_login)
        open_http_https = parse_bool(prompt_str("Open HTTP/HTTPS (true|false)", default=str(open_http_https).lower()), default=open_http_https)
        webserver = prompt_str("Webserver for Certbot (apache|nginx|standalone)", default=webserver)

        if root_password.upper().startswith("INSERISCI_"):
            root_password = ""
        if not root_password:
            if input("Change root password now? [y/N]: ").strip().lower() in {"y", "yes"}:
                root_password = getpass("root password (will not be echoed): ")

        if letsencrypt_email.upper().startswith("INSERISCI_"):
            letsencrypt_email = ""
        if letsencrypt_domains.upper().startswith("INSERISCI_"):
            letsencrypt_domains = ""

        # Optional: used when running certbot commands (can be left blank during bootstrap)
        letsencrypt_email = prompt_str("Let's Encrypt email (optional)", default=letsencrypt_email)
        letsencrypt_domains = prompt_str("Let's Encrypt domains comma-separated (optional)", default=letsencrypt_domains)

        if not checkmk_deb_url:
            checkmk_deb_url = prompt_str("CheckMK .deb URL (leave blank to build from CMK_VERSION)", default="")
        cmk_version = prompt_str("CheckMK version (used if URL not provided)", default=cmk_version)
        site_name = prompt_str("OMD site name", default=site_name)
        if not checkmk_admin_password:
            if input("Set cmkadmin password now? [y/N]: ").strip().lower() in {"y", "yes"}:
                checkmk_admin_password = getpass("cmkadmin password (will not be echoed): ")

        redirect_to_site = parse_bool(
            prompt_str("Redirect / to /<site>/ (true|false)", default=str(redirect_to_site).lower()),
            default=redirect_to_site,
        )

        # SMTP relay (optional)
        print("")
        print("Postfix SMTP relay (leave blank to use loopback-only mode):")
        smtp_relayhost = prompt_str("SMTP relayhost (e.g. [smtp.gmail.com]:587)", default=smtp_relayhost)
        if smtp_relayhost:
            smtp_relay_user = prompt_str("SMTP relay user/email", default=smtp_relay_user)
            if not smtp_relay_password:
                smtp_relay_password = getpass("SMTP relay password (will not be echoed): ")
        smtp_from_address = prompt_str("SMTP From address (e.g. no-reply@example.com)", default=smtp_from_address)

    return InstallerConfig(
        timezone=timezone,
        ssh_port=ssh_port,
        permit_root_login=permit_root_login,
        client_alive_interval=client_alive_interval,
        client_alive_countmax=client_alive_countmax,
        login_grace_time=login_grace_time,
        root_password=root_password,
        open_http_https=open_http_https,
        letsencrypt_email=letsencrypt_email,
        letsencrypt_domains=letsencrypt_domains,
        webserver=webserver,
        ntp_servers=ntp_servers,
        checkmk_admin_password=checkmk_admin_password,
        checkmk_deb_url=checkmk_deb_url,
        cmk_version=cmk_version,
        site_name=site_name,
        redirect_to_site=redirect_to_site,
        deploy_local_checks=deploy_local_checks,
        enable_auto_git_sync=enable_auto_git_sync,
        auto_git_sync_interval_sec=auto_git_sync_interval_sec,
        auto_git_sync_repo_url=auto_git_sync_repo_url,
        auto_git_sync_target_dir=auto_git_sync_target_dir,
        smtp_relayhost=smtp_relayhost,
        smtp_relay_user=smtp_relay_user,
        smtp_relay_password=smtp_relay_password,
        smtp_from_address=smtp_from_address,
        fail2ban_ignoreip=fail2ban_ignoreip,
    )
