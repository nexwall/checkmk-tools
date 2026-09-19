#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Correlate CheckMK notify.log with ydea-toolkit.log to produce a unified timeline.
# Each CheckMK notification that invoked ydea_la/ydea_ag is matched with its
# API outcome from ydea-toolkit.log, allowing fast diagnosis of failures.
#
# Usage:
#   ydea_notify_correlator.py [--date=YYYY-MM-DD] [--host=NAME]
#                             [--fail] [--ok] [--api|-a] [--help]

import sys
import os
import re
import gzip
from datetime import datetime, timedelta

VERSION = "1.0.0"

NOTIFY_LOG_BASE = "/omd/sites/monitoring/var/log/notify.log"
YDEA_TOOLKIT_LOG = "/var/log/ydea-toolkit.log"

# --- CLI args ---
ARGS = set(sys.argv[1:])
FILTER_DATE = None
FILTER_HOST = None
FILTER_OUTCOME = None   # "fail" | "ok"
SHOW_API = "--api" in ARGS or "-a" in ARGS
SHOW_OUTPUT = "--output" in ARGS or "-o" in ARGS

for arg in sys.argv[1:]:
    if arg.startswith("--date="):
        FILTER_DATE = arg.split("=", 1)[1]
    elif arg.startswith("--host="):
        FILTER_HOST = arg.split("=", 1)[1].lower()
    elif arg in ("--fail", "--failures"):
        FILTER_OUTCOME = "fail"
    elif arg == "--ok":
        FILTER_OUTCOME = "ok"


## Utils

def open_log(path):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "r", encoding="utf-8", errors="replace")


def parse_notify_ts(line):
    m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return None


def parse_ydea_ts(line):
    m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return None


def get_notify_log_files():
    files = []
    if os.path.exists(NOTIFY_LOG_BASE):
        files.append(NOTIFY_LOG_BASE)
    for i in range(1, 20):
        p = f"{NOTIFY_LOG_BASE}.{i}"
        if os.path.exists(p):
            files.append(p)
        p2 = f"{NOTIFY_LOG_BASE}.{i}.gz"
        if os.path.exists(p2):
            files.append(p2)
    return files


## ydea-toolkit.log index

def load_ydea_log():
    """Index ydea-toolkit.log by minute key -> list of lines."""
    idx = {}
    if not os.path.exists(YDEA_TOOLKIT_LOG):
        return idx
    try:
        with open(YDEA_TOOLKIT_LOG, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                ts = parse_ydea_ts(line)
                if ts:
                    key = ts.strftime("%Y-%m-%d %H:%M")
                    idx.setdefault(key, []).append(line.rstrip())
    except Exception as e:
        print(f"[WARN] Cannot read {YDEA_TOOLKIT_LOG}: {e}", file=sys.stderr)
    return idx


def get_api_context(ts, idx, window=2):
    """Return relevant ydea-toolkit.log lines within +/- window minutes of ts."""
    lines = []
    for delta in range(-1, window + 1):
        key = (ts + timedelta(minutes=delta)).strftime("%Y-%m-%d %H:%M")
        lines.extend(idx.get(key, []))

    # Drop repetitive token-renewal DEBUG lines
    relevant = []
    for l in lines:
        if "[DEBUG]" in l and ("Token valido" in l or "Token salvato" in l):
            continue
        if "[AUTH]" in l:
            continue
        relevant.append(l)
    return relevant


## notify.log parser

def iter_blocks(filepath):
    """Yield lists of lines representing one notification block."""
    try:
        with open_log(filepath) as f:
            lines = f.readlines()
    except Exception as e:
        print(f"[WARN] Cannot read {filepath}: {e}", file=sys.stderr)
        return

    current = []
    for line in lines:
        # Separator: line containing only dashes after the log prefix
        stripped = re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ \[\d+\] \[cmk[^\]]*\] ", "", line).rstrip()
        if stripped and all(c == "-" for c in stripped) and len(stripped) >= 20:
            if current:
                yield current
            current = [line]
        else:
            current.append(line)
    if current:
        yield current


def parse_block(lines):
    """
    Parse one notify.log block.
    Returns dict or None if block does not involve ydea_la/ydea_ag.
    """
    text = "".join(lines)

    # Only blocks that actually executed ydea_la or ydea_ag
    if not re.search(r"executing .*/ydea_(la|ag)", text):
        return None

    ts = None
    host = None
    service = None
    state = None
    plugin = None   # ydea_la or ydea_ag
    output_lines = []
    in_ydea_section = False

    for line in lines:
        if ts is None:
            ts = parse_notify_ts(line)

        # "Got raw notification (HOST) context" or "(HOST;SERVICE)"
        m = re.search(r"Got raw notification \(([^)]+)\) context", line)
        if m:
            target = m.group(1)
            if ";" in target:
                host, service = target.split(";", 1)
            else:
                host = target
                service = None

        # HOST NOTIFICATION (state, not result)
        # LOG;HOST NOTIFICATION: user;host;STATE;plugin;...
        m = re.search(r"LOG;HOST NOTIFICATION: [^;]+;[^;]+;([^;]+);(ydea_la|ydea_ag);", line)
        if m:
            state = m.group(1)
            plugin = m.group(2)

        # SERVICE NOTIFICATION: user;host;svc;STATE;plugin;...
        m = re.search(r"LOG;SERVICE NOTIFICATION: [^;]+;[^;]+;[^;]+;([^;]+);(ydea_la|ydea_ag);", line)
        if m:
            state = m.group(1)
            plugin = m.group(2)

        # Track when we enter the ydea execution section
        if re.search(r"executing .*/ydea_(la|ag)", line):
            in_ydea_section = True
            m2 = re.search(r"executing .+/(ydea_(?:la|ag))", line)
            if m2:
                plugin = m2.group(1)

        # Collect Output lines from the ydea execution
        if in_ydea_section:
            m3 = re.search(r"Output: (.+)$", line)
            if m3:
                output_lines.append(m3.group(1).strip())
            # Reset on next "notifying" line (another plugin starts)
            if re.search(r"notifying .* via (?!ydea)", line) and output_lines:
                in_ydea_section = False

    if not ts or not host:
        return None

    # Determine outcome
    full_output = " ".join(output_lines)
    outcome = "no_output"
    ticket_id = None

    if re.search(r"Ticket created|✅.*[Tt]icket.*#\d+", full_output):
        outcome = "created"
        m = re.search(r"#(\d+)", full_output)
        if m:
            ticket_id = int(m.group(1))
    elif re.search(r"Failed to create|❌", full_output):
        outcome = "failed"
    elif re.search(r"Private note added|Updating existing ticket", full_output):
        outcome = "updated"
        m = re.search(r"#(\d+)", full_output)
        if m:
            ticket_id = int(m.group(1))
    elif re.search(r"[Tt]icket.*già.*esist|already exist|skipped", full_output, re.I):
        outcome = "skipped"
        m = re.search(r"#(\d+)", full_output)
        if m:
            ticket_id = int(m.group(1))
    elif output_lines:
        outcome = "output"

    return {
        "ts": ts,
        "host": host,
        "service": service,
        "state": state or "?",
        "plugin": plugin or "ydea_la",
        "outcome": outcome,
        "ticket_id": ticket_id,
        "output_lines": output_lines,
    }


def load_events(files):
    events = []
    for filepath in files:
        for block in iter_blocks(filepath):
            ev = parse_block(block)
            if ev:
                events.append(ev)
    return sorted(events, key=lambda e: e["ts"])


## Formatting

OUTCOME_ICON = {
    "created": "✅",
    "updated": "🔄",
    "skipped": "⏭ ",
    "failed":  "❌",
    "output":  "ℹ️ ",
    "no_output": "⚠️ ",
}

def format_event(ev, api_ctx):
    ts_str = ev["ts"].strftime("%Y-%m-%d %H:%M:%S")
    host = ev["host"]
    svc = ev["service"] or "HOST"
    state = ev["state"]
    outcome = ev["outcome"]
    ticket_id = ev.get("ticket_id")
    plugin = ev.get("plugin", "ydea_la")
    icon = OUTCOME_ICON.get(outcome, "?")

    if outcome == "created":
        outcome_str = f"Ticket #{ticket_id} created"
    elif outcome == "updated":
        outcome_str = f"Ticket #{ticket_id} note added"
    elif outcome == "skipped":
        outcome_str = f"Ticket #{ticket_id} already open (skipped)"
    elif outcome == "failed":
        outcome_str = "Failed to create ticket"
    elif outcome == "no_output":
        outcome_str = "No output captured"
    else:
        short = " | ".join(ev["output_lines"])[:100]
        outcome_str = short

    parts = [f"[{ts_str}] {host}/{svc}  {state}  [{plugin}]  {icon}  {outcome_str}"]

    if SHOW_OUTPUT and ev["output_lines"]:
        for ol in ev["output_lines"]:
            parts.append(f"  out> {ol}")

    if SHOW_API and api_ctx:
        api_relevant = [
            l for l in api_ctx
            if any(tag in l for tag in ("[API]", "[ERROR]", "[INFO]", "[WARN]"))
            and "SUCCESS: Login" not in l
            and "Token scaduto" not in l
        ]
        if api_relevant:
            parts.append("  api>")
            for al in api_relevant[:10]:
                # Shorten timestamp and PID for readability
                al_clean = re.sub(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[(\w+)\] \[PID:\d+\] ", r"[\1] ", al)
                parts.append(f"       {al_clean}")

    return "\n".join(parts)


## Main

def print_help():
    print(f"ydea_notify_correlator.py v{VERSION}")
    print()
    print("Correlates CheckMK notify.log with ydea-toolkit.log.")
    print("Shows every notification that invoked ydea_la/ydea_ag and its outcome.")
    print()
    print("Usage:")
    print("  ydea_notify_correlator.py [OPTIONS]")
    print()
    print("Options:")
    print("  --date=YYYY-MM-DD   Filter by date")
    print("  --host=HOSTNAME     Filter by host (case-insensitive)")
    print("  --fail              Show only failed ticket creations")
    print("  --ok                Show only successful outcomes")
    print("  --api, -a           Show API call details from ydea-toolkit.log")
    print("  --output, -o        Show raw output lines from ydea_la/ydea_ag")
    print("  --help, -h          This help")
    print()
    print("Examples:")
    print("  # All failures with API details")
    print("  ydea_notify_correlator.py --fail --api")
    print()
    print("  # All events for a specific host today")
    print("  ydea_notify_correlator.py --host=ns8 --date=2026-04-10")
    print()
    print("  # Full output for a specific date")
    print("  ydea_notify_correlator.py --date=2026-04-08 --api --output")


def main():
    if "--help" in ARGS or "-h" in ARGS:
        print_help()
        return

    print("Loading ydea-toolkit.log...", end="", flush=True)
    ydea_idx = load_ydea_log()
    total_ydea = sum(len(v) for v in ydea_idx.values())
    print(f" {total_ydea} lines indexed across {len(ydea_idx)} minutes")

    print("Loading notify.log files...", end="", flush=True)
    notify_files = get_notify_log_files()
    events = load_events(notify_files)
    print(f" {len(events)} ydea_la/ydea_ag events found in {len(notify_files)} log files")

    # Apply filters
    filtered = events
    if FILTER_DATE:
        filtered = [e for e in filtered if e["ts"].strftime("%Y-%m-%d") == FILTER_DATE]
    if FILTER_HOST:
        filtered = [e for e in filtered if e["host"].lower() == FILTER_HOST]
    if FILTER_OUTCOME == "fail":
        filtered = [e for e in filtered if e["outcome"] == "failed"]
    elif FILTER_OUTCOME == "ok":
        filtered = [e for e in filtered if e["outcome"] in ("created", "updated", "skipped")]

    # Counts
    c_created = sum(1 for e in filtered if e["outcome"] == "created")
    c_updated = sum(1 for e in filtered if e["outcome"] == "updated")
    c_failed  = sum(1 for e in filtered if e["outcome"] == "failed")
    c_skipped = sum(1 for e in filtered if e["outcome"] == "skipped")
    c_other   = len(filtered) - c_created - c_updated - c_failed - c_skipped

    print()
    print("=" * 72)
    print(f"  YDEA NOTIFY CORRELATOR v{VERSION}")
    filters = []
    if FILTER_DATE:
        filters.append(f"date={FILTER_DATE}")
    if FILTER_HOST:
        filters.append(f"host={FILTER_HOST}")
    if FILTER_OUTCOME:
        filters.append(f"outcome={FILTER_OUTCOME}")
    if filters:
        print(f"  Filters: {', '.join(filters)}")
    print(f"  Events: {len(filtered)}  |  ✅ created: {c_created}  🔄 updated: {c_updated}"
          f"  ❌ failed: {c_failed}  ⏭  skipped: {c_skipped}"
          + (f"  ⚠️  other: {c_other}" if c_other else ""))
    print("=" * 72)
    print()

    if not filtered:
        print("No events match the given filters.")
        return

    for ev in filtered:
        api_ctx = get_api_context(ev["ts"], ydea_idx) if (SHOW_API or ev["outcome"] == "failed") else []
        print(format_event(ev, api_ctx))

    print()
    print("=" * 72)


main()
