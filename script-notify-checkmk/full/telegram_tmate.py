#!/usr/bin/env python3
"""telegram_tmate.py - Telegram notifications for Check MK Tmate channel

TOKEN and CHAT_ID read from OMD standard environment file:
  /omd/sites/monitoring/etc/environment

Version: 1.5.3"""

import json
import os
import re
import sys
import socket
import urllib.parse
import urllib.request

VERSION = "1.5.7"

# === CONFIG ===
ENV_FILE = "/omd/sites/monitoring/etc/environment"
CMK_URL = os.environ.get("CMK_URL", "")
SITE = "monitoring"
# ==============


def _cmk_url_valid(url):
    return bool(url) and url.startswith(("http://", "https://")) and "<" not in url


_ISP_PTR = re.compile(
    r'\d{1,3}[.\-]\d{1,3}[.\-]\d{1,3}[.\-]\d{1,3}'  # IP octets in hostname
    r'|\.ppp\.'        # PPP/DSL pool
    r'|\.dsl\.'        # DSL
    r'|\.cable\.'      # Cable
    r'|\.pool\.'       # IP pool
    r'|\.dynamic\.'   # Dynamic IP
    r'|\.adsl\.'       # ADSL
    r'|\.broadband\.'  # Broadband
    r'|^(res|host|static|ip|ptr|dsl|cable|broadband|dynamic|pool|user|client|customer)[.\-_]',
    re.IGNORECASE
)


def get_reverse_dns_url():
    """Auto-discover CMK_URL via public IP + reverse DNS.
    Returns URL only if PTR hostname does not match ISP/generic patterns.
    Forward confirmation is skipped: /etc/hosts on the server itself maps
    its own hostname to 127.0.1.1, which would break the check."""
    try:
        req = urllib.request.Request("https://api.ipify.org")
        req.add_header("User-Agent", "CheckMK-Telegram-Notifier")
        with urllib.request.urlopen(req, timeout=5) as resp:
            public_ip = resp.read().decode().strip()
        hostname = socket.gethostbyaddr(public_ip)[0]
        if hostname and not _ISP_PTR.search(hostname):
            return f"https://{hostname}/monitoring"
    except Exception:
        pass
    return None


def load_env_file(path: str) -> None:
    """Load variables from .env file if not already present in the environment."""
    if not os.path.isfile(path):
        return
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def get_status_prefix(state: str) -> str:
    state = state.upper()
    if state in ("OK", "UP"):
        return "🟢 [OK]"
    elif state in ("WARN", "WARNING"):
        return "🟡 [WARN]"
    elif state in ("CRIT", "CRITICAL", "DOWN"):
        return "🔴 [CRIT]"
    elif state == "UNKNOWN":
        return "🟡 [UNKNOWN]"
    return "[?]"


def urlencode(value: str) -> str:
    return urllib.parse.quote(value, safe='')


def send_telegram(token: str, chat_id: str, text: str, reply_markup=None) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    params = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        params["reply_markup"] = reply_markup
    data = urllib.parse.urlencode(params).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        if '"ok":true' not in body and '"ok": true' not in body:
            sys.stderr.write(f"telegram_tmate v{VERSION}: Telegram API error: {body[:200]}\n")
            raise RuntimeError(f"Telegram API error: {body[:200]}")
    except Exception as e:
        sys.stderr.write(f"telegram_tmate v{VERSION}: send failed: {e}\n")
        raise


def main() -> int:
    # Upload .env file
    load_env_file(ENV_FILE)

    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        sys.stderr.write(
            f"telegram_tmate v{VERSION}: TOKEN o CHAT_ID mancanti. "
            f"Verifica {ENV_FILE}\n"
        )
        return 1

    global CMK_URL
    if not CMK_URL:
        CMK_URL = get_reverse_dns_url() or "__NOT_EXPOSED__"

    notify_what = os.environ.get("NOTIFY_WHAT", "SERVICE")
    hostname = os.environ.get("NOTIFY_HOSTNAME", "unknown")
    host_address = os.environ.get("NOTIFY_HOSTADDRESS", "")
    real_ip = os.environ.get("NOTIFY_HOSTLABEL_real_ip", host_address)

    if notify_what == "SERVICE":
        state = os.environ.get("NOTIFY_SERVICESTATE", "UNKNOWN")
        service = os.environ.get("NOTIFY_SERVICEDESC", "SERVICE")
        output = os.environ.get("NOTIFY_SERVICEOUTPUT", "N/A")
        prefix = get_status_prefix(state)

        msg = (
            f"{prefix} Servizio: {service}\n"
            f"Host: {hostname} ({real_ip})\n"
            f"Output: {output}"
        )
        if _cmk_url_valid(CMK_URL):
            service_enc = urlencode(service)
            service_link = (
                f"{CMK_URL}/check_mk/view.py?view_name=service"
                f"&host={hostname}&service={service_enc}&site={SITE}"
            )
            host_link = (
                f"{CMK_URL}/check_mk/view.py?view_name=host"
                f"&host={hostname}&site={SITE}"
            )
            button = json.dumps({
                "inline_keyboard": [[
                    {"text": "Servizio", "url": service_link},
                    {"text": "Host", "url": host_link},
                ]]
            })
        elif CMK_URL == "__NOT_EXPOSED__":
            button = json.dumps({
                "inline_keyboard": [[
                    {"text": "🔒 Panel unreachable (server not exposed)", "callback_data": "not_exposed"}
                ]]
            })
        else:
            button = None
    else:
        state = os.environ.get("NOTIFY_HOSTSTATE", "UNKNOWN")
        output = os.environ.get("NOTIFY_HOSTOUTPUT", "N/A")
        prefix = get_status_prefix(state)

        msg = (
            f"{prefix} Host: {hostname}\n"
            f"IP: {real_ip}\n"
            f"Output: {output}"
        )
        if _cmk_url_valid(CMK_URL):
            host_link = (
                f"{CMK_URL}/check_mk/view.py?view_name=host"
                f"&host={hostname}&site={SITE}"
            )
            button = json.dumps({
                "inline_keyboard": [[{"text": "Host", "url": host_link}]]
            })
        elif CMK_URL == "__NOT_EXPOSED__":
            button = json.dumps({
                "inline_keyboard": [[
                    {"text": "🔒 Panel unreachable (server not exposed)", "callback_data": "not_exposed"}
                ]]
            })
        else:
            button = None

    msg = f"[TMATE] {msg}"
    send_telegram(token, chat_id, msg, button)
    return 0


if __name__ == "__main__":
    sys.exit(main())
