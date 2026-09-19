#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# CheckMK notification plugin - triggers Copilot CLI autonomous investigation and autofix
#
# Flow:
#   CMK alert → this script → spawn background worker → copilot CLI investigates+fixes
#   → background worker sends Telegram report when done
#
# Install:
#   cp notify_copilot_autofix.py /omd/sites/monitoring/local/share/check_mk/notifications/notify_copilot_autofix
#   chmod 755 /omd/sites/monitoring/local/share/check_mk/notifications/notify_copilot_autofix
#   chown monitoring:monitoring /omd/sites/monitoring/local/share/check_mk/notifications/notify_copilot_autofix
#
# Config file (KEY=VALUE, one per line):
#   /omd/sites/monitoring/etc/copilot-autofix.env
#
# Required vars:
#   TELEGRAM_TOKEN      - Telegram bot token
#   TELEGRAM_CHAT_ID    - Telegram channel/chat ID to send reports to
#   COPILOT_BIN         - Path to copilot CLI binary (default: /usr/local/bin/copilot)
#
# Optional vars:
#   COPILOT_LOG_DIR     - Log directory (default: /var/log/copilot-autofix)
#   COPILOT_ACTIVE_TYPES - Comma-separated notification types to act on (default: PROBLEM)
#   CMK_SITE            - OMD site name (default: monitoring)
#   CMK_URL             - CheckMK base URL for inline links in Telegram

import os
import sys
import json
import subprocess
import time
import urllib.request
import urllib.parse
from urllib.error import URLError

VERSION = "1.0.0"

OMD_ENV_FILE = "/omd/sites/monitoring/etc/environment"
AUTOFIX_ENV_FILE = "/omd/sites/monitoring/etc/copilot-autofix.env"

## Utils


def load_env(path):
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def cfg(key, default=""):
    return os.getenv(key, default)


def sanitize(s, max_len=500):
    if not s:
        return ""
    # Strip null bytes and non-printable control chars (keep newline/tab)
    s = "".join(c for c in str(s) if c >= " " or c in "\n\t")
    return s[:max_len]


def send_telegram(msg):
    token = cfg("TELEGRAM_TOKEN")
    chat_id = cfg("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": msg[:4096],
            "parse_mode": "HTML",
        }).encode("utf-8")
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except Exception:
        pass


def get_log_file():
    log_dir = cfg("COPILOT_LOG_DIR", "/var/log/copilot-autofix")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        log_dir = "/tmp"
    hostname = os.getenv("NOTIFY_HOSTNAME", "unknown")
    service = os.getenv("NOTIFY_SERVICEDESC", os.getenv("NOTIFY_WHAT", "host"))
    ts = int(time.time())
    safe = lambda s: "".join(c if c.isalnum() or c in "-." else "_" for c in s)
    return f"{log_dir}/{ts}_{safe(hostname)}_{safe(service)}.log"


def build_prompt():
    what = os.getenv("NOTIFY_WHAT", "SERVICE")
    hostname = sanitize(os.getenv("NOTIFY_HOSTNAME", "unknown"), 100)
    host_address = sanitize(os.getenv("NOTIFY_HOSTADDRESS", ""), 100)
    notif_type = os.getenv("NOTIFY_NOTIFICATIONTYPE", "PROBLEM")
    site = cfg("CMK_SITE", "monitoring")
    live_socket = f"/omd/sites/{site}/tmp/run/live"

    if what == "SERVICE":
        service_desc = sanitize(os.getenv("NOTIFY_SERVICEDESC", ""), 200)
        service_state = os.getenv("NOTIFY_SERVICESTATE", "UNKNOWN")
        service_output = sanitize(os.getenv("NOTIFY_SERVICEOUTPUT", ""), 500)
        prev_state = os.getenv("NOTIFY_PREVIOUSSERVICEHARDSTATE", "")

        return f"""You are an autonomous CheckMK monitoring agent running ON the CheckMK server itself (OMD site: {site}).

A CheckMK alert has fired:
- Notification type: {notif_type}
- Host: {hostname} ({host_address})
- Service: {service_desc}
- State: {service_state} (previous: {prev_state})
- Output: {service_output}

Resources available to you on this server:
- LiveStatus socket: {live_socket}
- OMD site directory: /omd/sites/{site}/
- CheckMK commands: su - {site} -c "cmk --check {hostname}"
- Site logs: /omd/sites/{site}/var/log/
- You may SSH to {hostname} if needed to investigate directly

Your task:
1. Investigate the root cause of this {service_state} state on service "{service_desc}" for host {hostname}
2. Apply a fix autonomously if one is clearly safe and appropriate
3. Verify the fix resolved the problem
4. Summarize: root cause, action taken, result

Act now. Be efficient."""

    else:
        host_state = os.getenv("NOTIFY_HOSTSTATE", "DOWN")
        host_output = sanitize(os.getenv("NOTIFY_HOSTOUTPUT", ""), 500)

        return f"""You are an autonomous CheckMK monitoring agent running ON the CheckMK server itself (OMD site: {site}).

A CheckMK HOST alert has fired:
- Notification type: {notif_type}
- Host: {hostname} ({host_address})
- State: {host_state}
- Output: {host_output}

Resources available:
- LiveStatus socket: {live_socket}
- OMD site: /omd/sites/{site}/
- CheckMK commands: su - {site} -c "cmk --check {hostname}"

Your task:
1. Investigate why host {hostname} ({host_address}) is {host_state}
2. Check if it is a real connectivity issue or a monitoring configuration problem
3. If safe and appropriate, apply a fix
4. Report: root cause, action taken, current status

Act now."""


## Background worker (re-invoked with COPILOT_RUNNER=1)


def run_background():
    load_env(OMD_ENV_FILE)
    load_env(AUTOFIX_ENV_FILE)

    log_file = os.getenv("COPILOT_LOG_FILE", "/tmp/copilot-autofix.log")
    copilot_bin = cfg("COPILOT_BIN", "/usr/local/bin/copilot")
    hostname = os.getenv("NOTIFY_HOSTNAME", "unknown")
    service = os.getenv("NOTIFY_SERVICEDESC", "")
    what = os.getenv("NOTIFY_WHAT", "SERVICE")
    state = os.getenv("NOTIFY_SERVICESTATE", os.getenv("NOTIFY_HOSTSTATE", "?"))

    prompt = build_prompt()
    prompt_file = f"/tmp/copilot-autofix-prompt-{os.getpid()}.txt"

    try:
        with open(prompt_file, "w") as pf:
            pf.write(prompt)

        with open(log_file, "w") as lf:
            lf.write(f"=== Copilot Autofix - {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            lf.write(f"Host: {hostname} | Service: {service} | State: {state}\n")
            lf.write("=" * 60 + "\n\n")
            lf.flush()

            bash_cmd = (
                f'TERM=dumb {copilot_bin} --allow-all --autopilot '
                f'-p "$(cat {prompt_file})" 2>&1'
            )
            try:
                result = subprocess.run(
                    ["bash", "-c", bash_cmd],
                    stdout=lf,
                    stderr=subprocess.STDOUT,
                    timeout=600,
                )
                exit_code = result.returncode
            except subprocess.TimeoutExpired:
                lf.write("\n[TIMEOUT] Copilot exceeded 10 minutes\n")
                exit_code = 1
            except FileNotFoundError:
                lf.write(f"\n[ERROR] Copilot binary not found: {copilot_bin}\n")
                exit_code = 127
            except Exception as e:
                lf.write(f"\n[ERROR] {e}\n")
                exit_code = 1

            lf.write(f"\n=== Done (exit: {exit_code}) ===\n")

    finally:
        try:
            os.unlink(prompt_file)
        except Exception:
            pass

    # Build Telegram summary from last lines of log
    try:
        with open(log_file) as f:
            lines = f.readlines()
        tail = "".join(lines[-40:])[-2000:].strip()
    except Exception:
        tail = "Log not available"

    label = f"{hostname} / {service}" if what == "SERVICE" else hostname
    status_icon = "✅" if exit_code == 0 else "⚠️"
    msg = (
        f"🤖 <b>Copilot Autofix - Report</b>\n"
        f"{status_icon} {label} [{state}]\n"
        f"Log: <code>{log_file}</code>\n\n"
        f"<pre>{tail}</pre>"
    )
    send_telegram(msg)


## Notification entry point


def notify():
    load_env(OMD_ENV_FILE)
    load_env(AUTOFIX_ENV_FILE)

    notif_type = os.getenv("NOTIFY_NOTIFICATIONTYPE", "PROBLEM")
    hostname = sanitize(os.getenv("NOTIFY_HOSTNAME", "unknown"), 100)
    service = sanitize(os.getenv("NOTIFY_SERVICEDESC", ""), 200)
    what = os.getenv("NOTIFY_WHAT", "SERVICE")
    state = os.getenv("NOTIFY_SERVICESTATE", os.getenv("NOTIFY_HOSTSTATE", "?"))

    # Only trigger on configured notification types
    active_types = cfg("COPILOT_ACTIVE_TYPES", "PROBLEM").split(",")
    if notif_type not in [t.strip() for t in active_types]:
        return 0

    log_file = get_log_file()
    label = f"{hostname} / {service}" if what == "SERVICE" else hostname

    # Notify the user that autofix is starting
    send_telegram(
        f"🤖 <b>Copilot Autofix avviato</b>\n"
        f"🔴 {label} [{state}]\n"
        f"Analisi in corso...\nLog: <code>{log_file}</code>"
    )

    # Spawn background worker (same script, COPILOT_RUNNER=1)
    env = os.environ.copy()
    env["COPILOT_RUNNER"] = "1"
    env["COPILOT_LOG_FILE"] = log_file

    try:
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__)],
            env=env,
            start_new_session=True,
            stdout=open("/dev/null", "w"),
            stderr=subprocess.STDOUT,
            close_fds=True,
        )
    except Exception as e:
        send_telegram(f"🤖 [ERROR] Failed to spawn autofix worker: {e}")
        return 1

    return 0


## Dispatch

if os.getenv("COPILOT_RUNNER") == "1":
    run_background()
else:
    sys.exit(notify())
