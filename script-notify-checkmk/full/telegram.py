#!/usr/bin/python3
"""
telegram - Generic Telegram Notification
Bulk: no

CheckMK notification script - sends alerts to a Telegram channel.
Configured via OMD environment variables.

Version: 1.1.0
"""
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import socket

VERSION = "1.1.0"

# === CONFIG ===
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
CUSTOMER_NAME = os.environ.get("TELEGRAM_CUSTOMER_NAME", "")

CMK_URL = os.environ.get("CMK_URL", "")
SITE = "monitoring"

# Resilience: if the immediate send fails (e.g. NIC flap causing DNS/network
# errors), retry in a detached background process for up to RETRY_MAX_WAIT
# seconds instead of blocking (and failing) the CheckMK notification
# pipeline. The outcome (eventual success or permanent failure) is logged
# to the local Event Console so it stays observable even though CheckMK
# itself sees an immediate, successful exit.
EC_SOCKET = "/omd/sites/monitoring/tmp/run/mkeventd/eventsocket"
RETRY_INTERVAL = 15
RETRY_MAX_WAIT = 300
# ==============

## Utils

_ISP_PTR = re.compile(
    r'\d{1,3}[.\-]\d{1,3}[.\-]\d{1,3}[.\-]\d{1,3}'
    r'|\.ppp\.'
    r'|\.dsl\.'
    r'|\.cable\.'
    r'|\.pool\.'
    r'|\.dynamic\.'
    r'|\.adsl\.'
    r'|\.broadband\.'
    r'|^(res|host|static|ip|ptr|dsl|cable|broadband|dynamic|pool|user|client|customer)[.\-_]',
    re.IGNORECASE
)


def _cmk_url_valid(url):
    return bool(url) and url.startswith(("http://", "https://")) and "<" not in url


def get_reverse_dns_url():
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


def get_status_prefix(state):
    s = state.upper()
    if s in ("OK", "UP"):
        return "🟢 [OK]"
    elif s in ("WARN", "WARNING"):
        return "🟡 [WARN]"
    elif s in ("CRIT", "CRITICAL", "DOWN"):
        return "🔴 [CRIT]"
    elif s == "UNKNOWN":
        return "🟡 [UNKNOWN]"
    return "[?]"


def send_telegram(token, chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        params["reply_markup"] = reply_markup
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    if '"ok":true' not in body and '"ok": true' not in body:
        sys.stderr.write(f"telegram v{VERSION}: Telegram API error: {body[:200]}\n")
        raise RuntimeError(f"Telegram API error: {body[:200]}")
    sys.stdout.write("Telegram OK: message sent\n")


def _log_ec_event(priority, application, text):
    """Best-effort: write one syslog-formatted line to the local Event
    Console socket. Never raises - a logging failure must never affect
    the notification flow."""
    try:
        pri = 16 * 8 + priority  # facility local0 (16)
        hostname = os.environ.get("NOTIFY_HOSTNAME") or socket.gethostname()
        ts = time.strftime("%b %d %H:%M:%S")
        line = f"<{pri}>{ts} {hostname} {application}: {text}\n"
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(EC_SOCKET)
        s.sendall(line.encode("utf-8", errors="replace"))
        s.close()
    except Exception:
        pass


def send_telegram_resilient(token, chat_id, text, reply_markup=None):
    """Try to send immediately. On failure, detach a background process
    that keeps retrying for up to RETRY_MAX_WAIT seconds, and return right
    away so CheckMK's notification pipeline (and its plugin timeout) is
    never blocked by a transient flap. The final outcome (success after
    retry, or permanent failure) is logged to the Event Console."""
    try:
        send_telegram(token, chat_id, text, reply_markup)
        return
    except Exception as exc:
        sys.stderr.write(
            f"telegram v{VERSION}: initial send failed ({exc}), "
            "handing off to background retry\n"
        )

    try:
        pid = os.fork()
        if pid > 0:
            return  # parent: CheckMK sees a normal, successful exit now
    except OSError:
        return  # can't fork - nothing more we can do

    # First child: detach fully from the notification script's process
    # group/session so it survives after CheckMK reaps the parent.
    os.setsid()
    try:
        pid2 = os.fork()
        if pid2 > 0:
            os._exit(0)
    except OSError:
        os._exit(1)

    # Second child: the actual background retry worker, fully detached.
    os.chdir("/")
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)

    started = time.time()
    deadline = started + RETRY_MAX_WAIT
    attempt = 1
    last_exc = None
    while time.time() < deadline:
        time.sleep(RETRY_INTERVAL)
        attempt += 1
        try:
            send_telegram(token, chat_id, text, reply_markup)
            _log_ec_event(
                6, "telegram_retry",
                f"Telegram message delivered after {attempt} attempts "
                f"(~{int(time.time() - started)}s)"
            )
            os._exit(0)
        except Exception as exc:
            last_exc = exc

    _log_ec_event(
        3, "telegram_retry",
        f"Telegram message permanently failed after {attempt} attempts "
        f"over {RETRY_MAX_WAIT}s: {last_exc}"
    )
    os._exit(1)

## Check

def check():
    if not TOKEN or not CHAT_ID:
        sys.stderr.write(f"telegram v{VERSION}: TOKEN o CHAT_ID mancanti. Verifica /omd/sites/monitoring/etc/environment\n")
        return

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
            service_enc = urllib.parse.quote(service, safe='')
            service_link = f"{CMK_URL}/check_mk/view.py?view_name=service&host={hostname}&service={service_enc}&site={SITE}"
            host_link = f"{CMK_URL}/check_mk/view.py?view_name=host&host={hostname}&site={SITE}"
            button = json.dumps({"inline_keyboard": [[
                {"text": "Servizio", "url": service_link},
                {"text": "Host", "url": host_link},
            ]]})
        elif CMK_URL == "__NOT_EXPOSED__":
            button = json.dumps({"inline_keyboard": [[
                {"text": "🔒 Panel unreachable (server not exposed)", "callback_data": "not_exposed"}
            ]]})
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
            host_link = f"{CMK_URL}/check_mk/view.py?view_name=host&host={hostname}&site={SITE}"
            button = json.dumps({"inline_keyboard": [[{"text": "Host", "url": host_link}]]})
        elif CMK_URL == "__NOT_EXPOSED__":
            button = json.dumps({"inline_keyboard": [[
                {"text": "🔒 Panel unreachable (server not exposed)", "callback_data": "not_exposed"}
            ]]})
        else:
            button = None

    prefix_label = f"[{CUSTOMER_NAME}] " if CUSTOMER_NAME else ""
    msg = f"{prefix_label}{msg}"
    send_telegram_resilient(TOKEN, CHAT_ID, msg, button)

check()
