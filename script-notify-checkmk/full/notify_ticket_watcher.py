#!/usr/bin/env python3
"""notify_ticket_watcher.py - CheckMK log watcher for Telegram ticket notifications
Reads notify.log, intercepts ticket creation/reopen [TICKET-EVENT] lines and
ydea_la's "Private note added" confirmations, and sends a Telegram message for each.
Completely independent of the CheckMK notification system.

Version: 1.4.0"""

import os
import re
import json
import socket
import urllib.request
import urllib.parse
import sys

VERSION = "1.4.0"

LOG_FILE   = "/omd/sites/monitoring/var/log/notify.log"
STATE_FILE = "/omd/sites/monitoring/var/log/notify_ticket_watcher.json"

TOKEN    = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID  = os.environ.get("TELEGRAM_NOTIFY_CHAT_ID", "")
CMK_URL  = os.environ.get("CMK_URL", "")


def _cmk_url_valid(url):
    return bool(url) and url.startswith(("http://", "https://")) and "<" not in url

# Ticket creato/riaperto: host/servizio/stato sono già nella stessa riga [TICKET-EVENT],
# scritta da ydea_la via log_ticket_event() - match self-contained, nessuna correlazione.
EVENT_PATTERN = re.compile(
    r'\[cmk\.base\.notify\].*Output:.*\[TICKET-EVENT\] \[(CREATO|RIAPERTO)\] #(\d+) ([^/\n]+)/(.+?) (OK|UP|WARN\w*|CRIT\w*|DOWN\w*|CRITICAL)'
)

# Nota aggiunta a un ticket già aperto (cambio di stato su un ticket esistente):
# la riga "Private note added" di ydea_la non riporta host/servizio/stato, li
# recuperiamo dalla riga "SERVICE NOTIFICATION: ...;ydea_la;..." che la precede
# sempre, poche righe prima, nella stessa esecuzione del plugin.
NOTE_PATTERN = re.compile(
    r'SERVICE NOTIFICATION: [^;\n]+;([^;\n]+);([^;\n]+);([^;\n]+);ydea_la;.*?'
    r'Output: \[.*?\] Private note added to ticket #(\d+)',
    re.DOTALL
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


LIVESTATUS_SOCK = "/omd/sites/monitoring/tmp/run/live"


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


ACTION_TEXT = {
    "CREATO": "aperto",
    "RIAPERTO": "riaperto",
    "NOTA": "aggiornato",
}


def send_telegram(event_type: str, ticket_id: str, hostname: str, service: str, state_str: str,
                 host_address: str = "", svc_output: str = ""):
    state_up = state_str.upper()
    if state_up in ("OK", "UP"):
        emoji = "\U0001f7e2"
    elif "WARN" in state_up:
        emoji = "\U0001f7e0"
    else:
        emoji = "\U0001f534"
    host_enc = urllib.parse.quote(hostname, safe="")

    # Host line: «Hostname (IP)» if the IP is available
    host_line = f"{hostname} ({host_address})" if host_address else hostname

    # Output: truncate to 300 characters
    output_line = ""
    if svc_output:
        truncated = svc_output[:300]
        if len(svc_output) > 300:
            truncated += "…"
        output_line = f"\n<code>{truncated}</code>"

    cmk_link = ""
    if _cmk_url_valid(CMK_URL):
        cmk_link = f'\n<a href="{CMK_URL}/check_mk/view.py?view_name=host&host={host_enc}">Vai a CheckMK</a>'
    action_text = ACTION_TEXT.get(event_type, "aggiornato")
    text = (
        f"\U0001f3ab <b>Ticket #{ticket_id} {action_text}</b>\n"
        f"{emoji} <b>{state_str}</b> \u2014 {host_line}\n"
        f"\U0001f4cb {service}{output_line}{cmk_link}"
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

    # Log rotated (file smaller than pos)
    if file_size < pos:
        pos = 0

    with open(LOG_FILE, "r", errors="replace") as f:
        f.seek(pos)
        new_lines = f.read()
        new_pos = f.tell()

    errors = []
    seen_this_run = set()

    events = []
    for match in EVENT_PATTERN.finditer(new_lines):
        events.append((
            match.group(1),           # event_type: CREATO | RIAPERTO
            match.group(2),           # ticket_id
            match.group(3).strip(),   # hostname
            match.group(4).strip(),   # service
            match.group(5).strip(),   # state_str
        ))
    for match in NOTE_PATTERN.finditer(new_lines):
        events.append((
            "NOTA",
            match.group(4),           # ticket_id
            match.group(1).strip(),   # hostname
            match.group(2).strip(),   # service
            match.group(3).strip(),   # state_str
        ))

    for event_type, ticket_id, hostname, service, state_str in events:
        if event_type == "CREATO":
            # Un ticket viene creato una sola volta: dedup permanente su disco.
            key = f"CREATO:{ticket_id}"
            if key in sent:
                continue
        else:
            # RIAPERTO/NOTA si ripetono nel tempo per lo stesso ticket: dedup
            # solo all'interno di questa esecuzione, per collassare le righe
            # duplicate generate dai contatti multipli (cmkadmin/nick/massimo)
            # sullo stesso evento, senza bloccare i prossimi eventi reali.
            key = f"{event_type}:{ticket_id}:{hostname}:{service}:{state_str}"
            if key in seen_this_run:
                continue
            seen_this_run.add(key)

        try:
            host_address, svc_output = get_service_info(hostname, service)
            send_telegram(event_type, ticket_id, hostname, service, state_str, host_address, svc_output)
            if event_type == "CREATO":
                sent.add(key)
        except Exception as e:
            errors.append(str(e))

    state["pos"] = new_pos
    state["sent"] = list(sent)
    save_state(state)

    if errors:
        print(f"WARN: {errors}", file=sys.stderr)


if __name__ == "__main__":
    main()