#!/usr/bin/env python3
"""notify_ticket_watcher_sp.py - Telegram ticket notification watcher - Studio Paci
Reads notify.log, intercepts [TICKET-EVENT] [CREATED] and sends Telegram message.
Completely independent of the CheckMK notification system.

Studio Paci variant: CheckMK server not publicly exposed, no links.

Version: 1.0.0"""

import os
import re
import json
import socket
import urllib.request
import urllib.parse
import sys

VERSION = "1.0.0"

LOG_FILE   = "/omd/sites/monitoring/var/log/notify.log"
STATE_FILE = "/omd/sites/monitoring/var/log/notify_ticket_watcher_sp.json"

TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_NOTIFY_CHAT_ID", "")

LIVESTATUS_SOCK = "/omd/sites/monitoring/tmp/run/live"

# Match only lines [cmk.base.notify] Output: to avoid duplicates
PATTERN = re.compile(
    r'\[cmk\.base\.notify\].*Output:.*\[TICKET-EVENT\] \[CREATO\] #(\d+) ([^/\n]+)/(.+?) (CRIT\w*|DOWN\w*|CRITICAL)'
)


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"pos": 0, "sent": []}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def get_service_info(hostname: str, service: str) -> tuple[str, str]:
    """Query Livestatus to get (host_address, plugin_output)."""
    try:
        query = (
            f"GET services\n"
            f"Filter: host_name = {hostname}\n"
            f"Filter: description = {service}\n"
            f"Columns: host_address plugin_output\n"
            f"OutputFormat: json\n\n"
        )
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(5)
        s.connect(LIVESTATUS_SOCK)
        s.send(query.encode())
        s.shutdown(socket.SHUT_WR)
        raw = s.makefile().read().strip()
        rows = json.loads(raw) if raw else []
        if rows:
            return rows[0][0], rows[0][1]
    except Exception:
        pass
    return "", ""


def send_telegram(ticket_id: str, hostname: str, service: str, state_str: str,
                  host_address: str = "", svc_output: str = ""):
    emoji = "\U0001f534" if "CRIT" in state_str.upper() else "\U0001f7e0"

    # Host line: «Hostname (IP)» if the IP is available
    host_line = f"{hostname} ({host_address})" if host_address else hostname

    # Output: truncate to 300 characters
    output_line = ""
    if svc_output:
        truncated = svc_output[:300]
        if len(svc_output) > 300:
            truncated += "\u2026"
        output_line = f"\n<code>{truncated}</code>"

    text = (
        f"\U0001f3ab <b>Ticket #{ticket_id} aperto</b>\n"
        f"{emoji} <b>{state_str}</b> \u2014 {host_line}\n"
        f"\U0001f4cb {service}{output_line}"
    )

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    urllib.request.urlopen(req, timeout=10)


def main():
    if not os.path.exists(LOG_FILE):
        return

    state = load_state()
    pos = state.get("pos", 0)
    sent = set(state.get("sent", []))

    # Clear old sent (only keep last 500)
    if len(sent) > 500:
        sent = set(list(sent)[-500:])

    file_size = os.path.getsize(LOG_FILE)

    # Rotated log (file smaller than pos)
    if file_size < pos:
        pos = 0

    with open(LOG_FILE, "r", errors="replace") as f:
        f.seek(pos)
        new_lines = f.read()
        new_pos = f.tell()

    errors = []
    for match in PATTERN.finditer(new_lines):
        ticket_id = match.group(1)
        hostname  = match.group(2).strip()
        service   = match.group(3).strip()
        state_str = match.group(4).strip()

        if ticket_id in sent:
            continue

        try:
            host_address, svc_output = get_service_info(hostname, service)
            send_telegram(ticket_id, hostname, service, state_str, host_address, svc_output)
            sent.add(ticket_id)
        except Exception as e:
            errors.append(str(e))

    state["pos"] = new_pos
    state["sent"] = list(sent)
    save_state(state)

    if errors:
        print(f"WARN: {errors}", file=sys.stderr)


if __name__ == "__main__":
    main()
