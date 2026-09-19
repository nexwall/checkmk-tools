from __future__ import annotations

import shlex
from getpass import getpass
from pathlib import Path

from lib.common import command_exists, log_header, log_info, log_success, log_warn, run as run_cmd, run_capture
from lib.config import InstallerConfig


def _configure_relay(relayhost: str, relay_user: str, relay_password: str, from_address: str) -> None:
    """Configure Postfix SMTP relay with SASL authentication."""
    log_info(f"Configuring SMTP relay: {relayhost}")

    run_cmd(["postconf", "-e", f"relayhost = {relayhost}"])
    run_cmd(["postconf", "-e", "smtp_sasl_auth_enable = yes"])
    run_cmd(["postconf", "-e", "smtp_sasl_password_maps = hash:/etc/postfix/sasl_passwd"])
    run_cmd(["postconf", "-e", "smtp_sasl_security_options = noanonymous"])
    run_cmd(["postconf", "-e", "smtp_tls_security_level = encrypt"])
    run_cmd(["postconf", "-e", "smtp_tls_CAfile = /etc/ssl/certs/ca-certificates.crt"])
    run_cmd(["postconf", "-e", "inet_interfaces = loopback-only"])
    run_cmd(["postconf", "-e", "mydestination = $myhostname, localhost.$mydomain, localhost"])

    sasl_passwd = Path("/etc/postfix/sasl_passwd")
    sasl_passwd.write_text(f"{relayhost} {relay_user}:{relay_password}\n", encoding="utf-8")
    sasl_passwd.chmod(0o600)
    run_cmd(["postmap", str(sasl_passwd)])

    if from_address:
        log_info(f"Configuring sender address rewriting: {from_address}")
        generic_maps = Path("/etc/postfix/generic")
        generic_maps.write_text(f"@{run_capture(['hostname', '-f'], check=False) or 'localhost'} {from_address}\nroot {from_address}\n", encoding="utf-8")
        run_cmd(["postmap", str(generic_maps)])
        run_cmd(["postconf", "-e", "smtp_generic_maps = hash:/etc/postfix/generic"])

    log_success("SMTP relay configured")


def run(cfg: InstallerConfig) -> None:
    log_header("25-POSTFIX")
    log_info("Installing Postfix...")

    fqdn = run_capture(["hostname", "-f"], check=False) or "localhost"
    run_cmd(["bash", "-lc", f"debconf-set-selections <<< 'postfix postfix/mailname string {shlex.quote(fqdn)}'"])
    run_cmd(["bash", "-lc", "debconf-set-selections <<< \"postfix postfix/main_mailer_type string 'Internet Site'\""])

    run_cmd(["apt-get", "install", "-y", "postfix", "mailutils"])
    run_cmd(["postconf", "-e", "inet_interfaces = loopback-only"])
    run_cmd(["postconf", "-e", "mydestination = $myhostname, localhost.$mydomain, localhost"])

    # Strip placeholders
    relayhost = cfg.smtp_relayhost.strip()
    relay_user = cfg.smtp_relay_user.strip()
    relay_password = cfg.smtp_relay_password.strip()
    from_address = cfg.smtp_from_address.strip()

    if relayhost.upper().startswith("INSERISCI_"):
        relayhost = ""
    if relay_user.upper().startswith("INSERISCI_"):
        relay_user = ""
    if from_address.upper().startswith("INSERISCI_"):
        from_address = ""

    if relayhost:
        # Configured in .env - use directly (password may still need prompting)
        if not relay_password:
            relay_password = getpass(f"SMTP relay password for {relay_user}@{relayhost} (will not be echoed): ").strip()
        if not from_address:
            from_address = input("From address (e.g. no-reply@example.com, leave blank to skip): ").strip()
        _configure_relay(relayhost, relay_user, relay_password, from_address)
    else:
        # Not configured - ask interactively
        print("")
        log_warn("No SMTP relay configured. Postfix will be loopback-only (local delivery only).")
        print("You can configure an SMTP relay to send emails (alerts, notifications).")
        print("")
        ans = input("Configure SMTP relay now? [y/N]: ").strip().lower()
        if ans in {"y", "yes"}:
            relayhost = input("Relayhost (e.g. [smtp.gmail.com]:587): ").strip()
            relay_user = input("Relay username/email: ").strip()
            relay_password = getpass("Relay password (will not be echoed): ").strip()
            from_address = input("From address (e.g. no-reply@example.com, leave blank to skip): ").strip()
            if relayhost and relay_user and relay_password:
                _configure_relay(relayhost, relay_user, relay_password, from_address)
            else:
                log_warn("Incomplete relay config - using loopback-only mode")
        else:
            log_info("Using loopback-only mode (no relay configured)")

    if command_exists("systemctl"):
        run_cmd(["systemctl", "restart", "--no-block", "postfix"], check=False)
        run_cmd(["systemctl", "enable", "postfix"], check=False)

    log_success("Postfix configured")

