from __future__ import annotations

from pathlib import Path

from lib.common import backup_file, command_exists, log_header, log_info, log_success, run as run_cmd
from lib.config import InstallerConfig


def _first_domain(cfg: InstallerConfig) -> str:
    domains = [d.strip() for d in cfg.letsencrypt_domains.split(",") if d.strip()]
    return domains[0] if domains else "_default_"


def run_step(cfg: InstallerConfig) -> None:
    log_header("55-APACHE")
    log_info("Installing and configuring Apache reverse proxy for CheckMK...")

    if not command_exists("apache2"):
        run_cmd(["apt-get", "update"])
        run_cmd(["apt-get", "install", "-y", "apache2"])

    for mod in ["proxy", "proxy_http", "rewrite", "headers", "ssl"]:
        run_cmd(["a2enmod", mod], check=False)

    domain = _first_domain(cfg)
    default_site = cfg.site_name

    apache_conf = Path("/etc/apache2/sites-available/checkmk.conf")
    if apache_conf.exists():
        backup = backup_file(apache_conf)
        log_info(f"Backup created: {backup}")

    vhost: list[str] = [
        "<VirtualHost *:80>",
        f"    ServerName {domain}",
        "",
        "    RewriteEngine On",
        "    RewriteCond %{HTTPS} off",
        "    RewriteRule ^(.*)$ https://%{HTTP_HOST}$1 [R=301,L]",
        "</VirtualHost>",
        "",
        "<VirtualHost *:443>",
        f"    ServerName {domain}",
        "",
        "    SSLEngine on",
        "    SSLCertificateFile /etc/ssl/certs/ssl-cert-snakeoil.pem",
        "    SSLCertificateKeyFile /etc/ssl/private/ssl-cert-snakeoil.key",
        "",
    ]

    if cfg.redirect_to_site:
        vhost += [
            "    RewriteEngine On",
            f"    RewriteRule ^/?$ /{default_site}/ [R=301,L]",
            "",
            "    ProxyPreserveHost On",
            f"    ProxyPass /{default_site}/ http://127.0.0.1:5000/{default_site}/",
            f"    ProxyPassReverse /{default_site}/ http://127.0.0.1:5000/{default_site}/",
            "",
            "    RewriteCond %{HTTP:Upgrade} websocket [NC]",
            "    RewriteCond %{HTTP:Connection} upgrade [NC]",
            f"    RewriteRule ^/{default_site}/(.*) \"ws://127.0.0.1:5000/{default_site}/$1\" [P,L]",
        ]
    else:
        vhost += [
            "    ProxyPreserveHost On",
            "    ProxyPass / http://127.0.0.1:5000/",
            "    ProxyPassReverse / http://127.0.0.1:5000/",
            "",
            "    RewriteEngine On",
            "    RewriteCond %{HTTP:Upgrade} websocket [NC]",
            "    RewriteCond %{HTTP:Connection} upgrade [NC]",
            "    RewriteRule ^/?(.*) \"ws://127.0.0.1:5000/$1\" [P,L]",
        ]

    vhost += [
        "",
        '    Header always set Strict-Transport-Security "max-age=31536000"',
        '    Header always set X-Frame-Options "SAMEORIGIN"',
        '    Header always set X-Content-Type-Options "nosniff"',
        "</VirtualHost>",
        "",
    ]

    apache_conf.write_text("\n".join(vhost), encoding="utf-8")

    run_cmd(["a2ensite", "checkmk.conf"], check=False)
    run_cmd(["a2dissite", "000-default.conf"], check=False)
    run_cmd(["systemctl", "restart", "apache2"], check=False)
    run_cmd(["systemctl", "enable", "apache2"], check=False)

    log_success("Apache configured")


def run(cfg: InstallerConfig) -> None:
    run_step(cfg)
