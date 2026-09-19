#!/usr/bin/env python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#
# check_notification_limiter_status.py - Checkmk local check for M@il-20
#   and Telegram-20 notification delivery and rate-limiter monitoring.
#
# Reads the lifecycle logs written by M@il-20 and Telegram-20 and exposes
# four Checkmk services:
#
#   M@il-20 Delivery
#   M@il-20 Limiter
#   Telegram-20 Delivery
#   Telegram-20 Limiter
#
# Version: 1.0.0

import os
import sys
import json
import time
import re
import fcntl
import tempfile
import stat as statmod
from pathlib import Path

VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOG_ROOT = "/omd/sites/monitoring/var/log/notifications"
LOG_MAIL = os.path.join(LOG_ROOT, "mail-20.log")
LOG_TELEGRAM = os.path.join(LOG_ROOT, "telegram-20.log")
LOG_MAIL_LEGACY = "/omd/sites/monitoring/var/log/M@il-20.log"
LOG_TELEGRAM_LEGACY = "/omd/sites/monitoring/var/log/Telegram-20.log"

ADAPTIVE_DIR_MAIL = "/omd/sites/monitoring/var/check_mk/M@il-20"
ADAPTIVE_DIR_TELEGRAM = "/omd/sites/monitoring/var/check_mk/Telegram-20"

STATE_DIR = "/var/lib/checkmk-notification-monitor"

# Retention defaults (seconds)
WARN_RETENTION = 1800       # 30 min
CRIT_RETENTION = 3600       # 60 min
STALE_LOG_SECONDS = 86400   # 24 h

# First-run: only tail the last N bytes to avoid alert floods
FIRST_RUN_TAIL_BYTES = 1 * 1024 * 1024  # 1 MiB

# Max bytes read per file per execution
MAX_READ_BYTES = 512 * 1024  # 512 KiB

PARSER_VERSION = 1

# ---------------------------------------------------------------------------
# Log event patterns (derived from deployed M@il-20 / Telegram-20 code)
# ---------------------------------------------------------------------------

# NOTIFY_EVENT JSON line (new lifecycle logs, v1.3.1-beta)
RE_NOTIFY_EVENT = re.compile(
    r'^\S+\s+\[\w+\]\s+NOTIFY_EVENT\s+(\{.*\})\s*$'
)

# Plain KEY=VALUE decision line (historical M@il-20.log, v1.3.0-beta)
RE_DECISION_SEND = re.compile(
    r'DECISION=SEND\s+'
    r'host=(\S+)\s+'
    r'category=(\S+)\s+'
    r'old=(\S+)\s+'
    r'new=(\S+)\s+'
    r'transitions=(\d+)\s+'
    r'window=(\d+)\s+'
    r'suppress_until=(\d+)'
)

# Mode=audit / Mode=enforce (historical format)
RE_MODE = re.compile(
    r'Mode=(\S+)'
)

# Transition #N/M (historical format)
RE_TRANSITION = re.compile(
    r'Transition\s+#(\d+)/(\d+)'
)

# SUPPRESS line (historical format)
RE_SUPPRESS = re.compile(
    r'\bSUPPRESS\b'
)

# Provider delivery confirmation (historical format, Telegram-20)
RE_TELEGRAM_OK = re.compile(
    r'Telegram OK: message sent'
)

# Provider failure / exception
RE_PROVIDER_FAILURE = re.compile(
    r'(?:sendmail not found|Connection refused|timeout|'
    r'exception|Traceback|RuntimeError|HTTP\s+\d+\s+|'
    r'delivery failed|FAILED|sendmail failed)',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now():
    return int(time.time())


def parse_notify_event_json(line):
    """Parse a NOTIFY_EVENT JSON line and return a normalized event dict.

    Format (from script code):
        TIMESTAMP [LEVEL] NOTIFY_EVENT {JSON}
    """
    m = RE_NOTIFY_EVENT.match(line)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return None
    return data


def parse_legacy_line(line, channel):
    """Parse a KEY=VALUE log line (historical M@il-20.log format).

    Returns a normalized event dict or None if no event is found.
    """
    if RE_TELEGRAM_OK.search(line):
        return {
            "status": "PROVIDER_CONFIRMED",
            "channel": channel,
            "_timestamp": None,
        }

    m = RE_DECISION_SEND.search(line)
    if not m:
        return None

    event = {
        "status": "DECISION",
        "channel": channel,
        "host": m.group(1),
        "category": m.group(2),
        "old_state": m.group(3),
        "new_state": m.group(4),
        "transition_count": int(m.group(5)),
        "window": int(m.group(6)),
        "suppress_until": int(m.group(7)),
        "decision": "SEND",
        "mode": "unknown",
    }

    mm = RE_MODE.search(line)
    if mm:
        event["mode"] = mm.group(1)

    tm = RE_TRANSITION.search(line)
    if tm:
        event["transition_current"] = int(tm.group(1))
        event["transition_threshold"] = int(tm.group(2))
    else:
        event["transition_current"] = 0
        event["transition_threshold"] = 0

    if RE_SUPPRESS.search(line):
        event["decision"] = "SUPPRESS"

    if RE_PROVIDER_FAILURE.search(line):
        event["provider_status"] = "FAILED"
    else:
        event["provider_status"] = None

    return event


def parse_log_timestamp(line):
    """Extract the timestamp from the beginning of a log line.

    Format: 'YYYY-MM-DD HH:MM:SS ...'
    Returns a Unix timestamp (int) or current time as fallback.
    """
    try:
        ts_str = line[:19]
        parsed = time.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        return int(time.mktime(parsed))
    except (ValueError, IndexError):
        return now()


# ---------------------------------------------------------------------------
# Channel state — retained between executions
# ---------------------------------------------------------------------------

class ChannelState:
    """Mutable state accumulated during one execution and then persisted."""

    def __init__(self, channel, log_path, legacy_path=None):
        self.channel = channel
        self.log_path = log_path
        self.legacy_path = legacy_path

        # Counters for the current reporting window
        self.authorized = 0
        self.confirmed = 0
        self.provider_failures = 0
        self.transitions = 0
        self.suppressions = 0
        self.would_suppress = 0
        self.latest_event_age = 0
        self.latest_log_mtime = 0

        # Unresolved events and their timestamps
        self.unresolved_crit = []   # list of (event_type, timestamp)
        self.unresolved_warn = []   # list of (event_type, timestamp)

        # Latest meaningful event per category
        self.latest_decision = None
        self.latest_transition = None
        self.latest_suppression = None
        self.latest_would_suppress = None
        self.latest_provider_attempt = None
        self.latest_provider_success = None
        self.latest_provider_failure = None

        # Staleness
        self.last_event_ts = 0
        self.log_mtime = 0


# ---------------------------------------------------------------------------
# File cursor management
# ---------------------------------------------------------------------------

def get_state_path(channel):
    """Return the path to the parser state file for *channel*."""
    return os.path.join(STATE_DIR, f"cursor_{channel}.json")


def read_cursor(channel):
    """Read the persisted parser cursor.  Returns a dict, possibly empty."""
    path = get_state_path(channel)
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {}


def write_cursor(channel, cursor):
    """Atomically write the parser cursor.  Returns True on success."""
    path = get_state_path(channel)
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(STATE_DIR))
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(cursor, f, indent=2)
            os.replace(tmp, path)
            os.chmod(path, 0o640)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except OSError:
        return False


def get_file_identity(path):
    """Return (device, inode, size, mtime) for *path* or None."""
    try:
        st = os.stat(path)
        return (st.st_dev, st.st_ino, st.st_size, int(st.st_mtime))
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Log reading and parsing
# ---------------------------------------------------------------------------

def read_and_parse(channel, log_path, cursor, legacy_path=None):
    """Read new log entries since the last cursor position.

    Returns a list of normalized event dicts (oldest first) and updates
    *cursor* for the next execution.

    Handles log rotation (inode change, truncation) and first-run baseline.
    """
    events = []

    identity = get_file_identity(log_path)
    if identity is None and legacy_path:
        # Fall back to legacy log
        log_path = legacy_path
        identity = get_file_identity(log_path)
    if identity is None:
        return events  # No log to read

    dev, ino, size, mtime = identity
    cursor_dev = cursor.get("device")
    cursor_ino = cursor.get("inode")
    cursor_offset = cursor.get("offset", 0)
    first_run = cursor.get("parser_version") is None

    # Detect log rotation / truncation
    rotation = False
    if cursor_dev is not None and (cursor_dev != dev or cursor_ino != ino):
        rotation = True
    elif size < cursor_offset:
        rotation = True  # truncated

    if rotation or first_run:
        # Establish new baseline: read only the tail
        read_start = max(0, size - FIRST_RUN_TAIL_BYTES)
        cursor_offset = read_start
    elif cursor_offset < 0:
        cursor_offset = 0

    # Bound read to safe size
    if size - cursor_offset > MAX_READ_BYTES:
        read_end = cursor_offset + MAX_READ_BYTES
    else:
        read_end = size

    if read_end <= cursor_offset and not first_run:
        return events  # Nothing new

    try:
        with open(log_path) as f:
            if rotation or first_run:
                # Seek near the end for first-run / rotation
                f.seek(cursor_offset)
                # Skip first partial line
                f.readline()
            else:
                f.seek(cursor_offset)

            for line in f:
                line = line.rstrip("\n\r")
                if not line:
                    continue

                # Try NOTIFY_EVENT JSON format first
                ev = parse_notify_event_json(line)
                if ev is not None:
                    ev["channel"] = channel
                    ev["_timestamp"] = parse_log_timestamp(line)
                    events.append(ev)
                    continue

                # Legacy KEY=VALUE format
                ev = parse_legacy_line(line, channel)
                if ev is not None:
                    if "timestamp" in ev and ev["timestamp"] is None:
                        ev["_timestamp"] = parse_log_timestamp(line)
                    elif "timestamp" in ev:
                        ev["_timestamp"] = ev["timestamp"]
                    else:
                        ev["_timestamp"] = parse_log_timestamp(line)
                    events.append(ev)

            cursor_offset = f.tell()
    except OSError:
        return events

    # Update cursor
    cursor["device"] = dev
    cursor["inode"] = ino
    cursor["offset"] = cursor_offset
    cursor["parser_version"] = PARSER_VERSION
    cursor["last_read"] = now()
    cursor["log_mtime"] = mtime

    return events


# ---------------------------------------------------------------------------
# Event classification
# ---------------------------------------------------------------------------

def classify_event(ev, state):
    """Update *state* (a ChannelState) based on one normalized event.

    This is called for every parsed event and maintains unresolved
    event lists with retention-based expiry.
    """
    channel = state.channel
    ts = ev.get("_timestamp", now())
    status = ev.get("status", "")
    decision = ev.get("decision", "")
    mode = ev.get("mode", "unknown")
    provider_status = ev.get("provider_status")
    transition_cur = ev.get("transition_current", 0)
    transition_total = ev.get("transition_threshold", 0)
    category = ev.get("category", "")
    result = ev.get("result", "")
    exit_code = ev.get("exit_code", None)
    delivery_attempted = ev.get("delivery_attempted", False)
    delivery_result = ev.get("delivery_result", "")

    state.last_event_ts = max(state.last_event_ts, ts)

    # --- NOTIFY_EVENT JSON processing ---

    if status == "DECISION":
        state.latest_decision = decision
        state.latest_event_age = ts
        state.authorized += 1

        tc = ev.get("transition_count", 0)
        if tc > 0:
            state.transitions += 1
            state.latest_transition = tc
            _add_unresolved(state, "warn", "transition", ts)

        if decision == "SEND":
            pass  # Normal
        elif decision == "SUPPRESS":
            state.suppressions += 1
            state.latest_suppression = ts
            _add_unresolved(state, "crit", "suppression", ts)
        elif decision == "WOULD_SUPPRESS":
            state.would_suppress += 1
            state.latest_would_suppress = ts
            _add_unresolved(state, "warn", "would_suppress", ts)

    elif status in ("DELIVERED", "COMPLETE"):
        if result in ("DELIVERED",) and exit_code == 0 and delivery_attempted:
            state.confirmed += 1
            state.latest_provider_success = ts
            # Clear prior provider failure for this channel
            _remove_unresolved(state, "crit", "provider_failure")
        elif result in ("FAILED",) or exit_code != 0:
            state.provider_failures += 1
            state.latest_provider_failure = ts
            _add_unresolved(state, "crit", "provider_failure", ts)

    elif status == "DELIVERING":
        state.latest_provider_attempt = ts

    elif status == "FAILED":
        state.provider_failures += 1
        state.latest_provider_failure = ts
        _add_unresolved(state, "crit", "provider_failure", ts)

    # --- Legacy format processing ---

    if decision == "SEND":
        state.authorized += 1
        state.latest_decision = "SEND"
        state.latest_event_age = ts

        if transition_cur > 0:
            state.transitions += 1
            state.latest_transition = transition_cur
            _add_unresolved(state, "warn", "transition", ts)

    if decision == "SUPPRESS":
        state.suppressions += 1
        state.latest_suppression = ts
        _add_unresolved(state, "crit", "suppression", ts)
    elif RE_SUPPRESS.search(str(ev)):
        # SUPPRESS found in legacy message but not in decision field
        state.suppressions += 1
        state.latest_suppression = ts
        _add_unresolved(state, "crit", "suppression", ts)

    # Provider confirmation in legacy format
    if provider_status == "CONFIRMED":
        state.confirmed += 1
        state.latest_provider_success = ts
        _remove_unresolved(state, "crit", "provider_failure")

    # Provider failure
    if provider_status == "FAILED":
        state.provider_failures += 1
        state.latest_provider_failure = ts
        _add_unresolved(state, "crit", "provider_failure", ts)


def _add_unresolved(state, severity, event_type, timestamp):
    """Add an unresolved event with retention.

    Duplicates (same type already pending) are replaced with the newer
    timestamp.
    """
    lst = state.unresolved_crit if severity == "crit" else state.unresolved_warn
    # Replace duplicate type
    for i, (t, _) in enumerate(lst):
        if t == event_type:
            lst[i] = (event_type, timestamp)
            return
    lst.append((event_type, timestamp))


def _remove_unresolved(state, severity, event_type):
    """Remove a specific unresolved event (e.g. after provider success)."""
    lst = state.unresolved_crit if severity == "crit" else state.unresolved_warn
    state.unresolved_crit[:] = [(t, ts) for (t, ts) in state.unresolved_crit
                                 if t != event_type]
    state.unresolved_warn[:] = [(t, ts) for (t, ts) in state.unresolved_warn
                                 if t != event_type]


def expire_unresolved(state, now_ts):
    """Remove unresolved events whose retention has expired."""
    state.unresolved_crit[:] = [
        (t, ts) for (t, ts) in state.unresolved_crit
        if now_ts - ts < CRIT_RETENTION
    ]
    state.unresolved_warn[:] = [
        (t, ts) for (t, ts) in state.unresolved_warn
        if now_ts - ts < WARN_RETENTION
    ]


# ---------------------------------------------------------------------------
# Adaptive learning state read (read-only)
# ---------------------------------------------------------------------------

def read_adaptive_state(channel):
    """Read the adaptive learning state file for a channel.

    Returns a dict with learning summary or empty dict on failure.
    """
    ad_dir = ADAPTIVE_DIR_MAIL if channel == "mail" else ADAPTIVE_DIR_TELEGRAM
    path = os.path.join(ad_dir, "state.json")
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

    summary = {
        "total_samples": 0,
        "highest_bucket_samples": 0,
        "max_learning_days": 0.0,
        "recommendation_status": None,
        "configured_min_days": 14,
        "configured_min_samples": 20,
        "recommendation_ready": False,
    }

    for entity, hd in data.items():
        if entity.startswith("_") or entity == "schema_version":
            continue
        if not isinstance(hd, dict):
            continue
        for cat, cd in hd.items():
            if not isinstance(cd, dict):
                continue
            ad = cd.get("adaptive", {})
            if not isinstance(ad, dict):
                continue
            samples = ad.get("transition_samples", [])
            n = len(samples)
            summary["total_samples"] += n
            if n > summary["highest_bucket_samples"]:
                summary["highest_bucket_samples"] = n

            fo = ad.get("first_observation", 0)
            if fo:
                days = (now() - fo) / 86400
                if days > summary["max_learning_days"]:
                    summary["max_learning_days"] = round(days, 1)

            rs = ad.get("recommendation_status")
            if rs:
                summary["recommendation_status"] = rs
                if rs == "OK" or rs == "RECOMMENDED":
                    summary["recommendation_ready"] = True

    return summary


# ---------------------------------------------------------------------------
# Checkmk output generation
# ---------------------------------------------------------------------------

def produce_services(state_mail, state_telegram, adaptive_mail, adaptive_telegram):
    """Produce the four Checkmk local-check output lines."""
    now_ts = now()
    expire_unresolved(state_mail, now_ts)
    expire_unresolved(state_telegram, now_ts)

    lines = []

    for channel, st, ad in [
        ("mail", state_mail, adaptive_mail),
        ("telegram", state_telegram, adaptive_telegram),
    ]:
        prefix = "M@il-20" if channel == "mail" else "Telegram-20"

        # --- Delivery service ---
        dl_status, dl_detail = _delivery_status(st, channel, ad)
        dl_metrics = (
            f"authorized={st.authorized}"
            f"|confirmed={st.confirmed}"
            f"|provider_failures={st.provider_failures}"
            f"|event_age={st.latest_event_age}"
        )
        if st.latest_log_mtime:
            dl_metrics += f"|log_age={now_ts - st.latest_log_mtime}"
        lines.append(f"{dl_status} \"{prefix} Delivery\" {dl_metrics} {dl_detail}")

        # --- Limiter service ---
        lm_status, lm_detail = _limiter_status(st, channel, ad)
        lm_metrics = (
            f"transitions={st.transitions}"
            f"|suppressions={st.suppressions}"
            f"|would_suppress={st.would_suppress}"
            f"|event_age={st.latest_event_age}"
        )
        if ad.get("total_samples", 0) > 0:
            lm_metrics += (
                f"|transition_samples={ad['total_samples']}"
                f"|learning_days={ad['max_learning_days']}"
            )
        lines.append(f"{lm_status} \"{prefix} Limiter\" {lm_metrics} {lm_detail}")

    return "\n".join(lines)


def _delivery_status(st, channel, ad):
    """Determine Delivery service state and detail text."""
    now_ts = now()

    # CRIT: unresolved provider failure
    for etype, ets in st.unresolved_crit:
        if etype == "provider_failure":
            age = now_ts - ets
            return (
                2,
                f"Provider failure retained for {age}s; "
                f"last confirmed={st.confirmed} failures={st.provider_failures}"
            )

    # CRIT: log not readable
    if st.log_path and not os.access(st.log_path, os.R_OK):
        return (2, f"Cannot read log: {st.log_path}")

    # CRIT: malformed — no events but log exists (potential issue)
    if st.last_event_ts == 0 and st.log_mtime > 0:
        log_age = now_ts - st.log_mtime
        if log_age > STALE_LOG_SECONDS:
            return (2, f"No events in {log_age}s; log may be stale or broken")

    # WARN: stale log
    if st.last_event_ts > 0:
        age = now_ts - st.last_event_ts
        if age > STALE_LOG_SECONDS:
            return (1, f"No recent events; last event {age}s ago (>{STALE_LOG_SECONDS}s threshold)")

    # WARN: adaptive learning incomplete
    rs = ad.get("recommendation_status")
    if rs == "INSUFFICIENT_DATA":
        return (
            1,
            f"authorized; learning INSUFFICIENT_DATA "
            f"({ad['total_samples']} samples, {ad['max_learning_days']}d, "
            f"need {ad['configured_min_samples']} samples / {ad['configured_min_days']}d)"
        )

    # OK: delivery confirmed
    if st.confirmed > 0 and st.provider_failures == 0:
        return (0, f"delivery confirmed; {st.confirmed} confirmations, {st.authorized} authorized")

    # OK: authorized but no confirmation yet (normal when idle)
    if st.authorized > 0 and st.provider_failures == 0:
        return (0, f"authorized; {st.authorized} events, awaiting provider confirmation")

    # WARN: authorized with both success and failure
    if st.authorized > 0 and st.provider_failures > 0:
        return (
            1,
            f"authorized={st.authorized} confirmed={st.confirmed} failures={st.provider_failures}; "
            f"mixed provider results"
        )

    # No data yet — first run or quiet
    if st.last_event_ts == 0:
        return (0, f"baseline established; waiting for first notification event")

    # Fallback OK
    return (0, f"authorized={st.authorized} confirmed={st.confirmed}")


def _limiter_status(st, channel, ad):
    """Determine Limiter service state and detail text."""
    now_ts = now()

    # CRIT: unresolved real suppression
    for etype, ets in st.unresolved_crit:
        if etype == "suppression":
            age = now_ts - ets
            return (2, f"Notification suppressed {age}s ago; {st.suppressions} total suppressions")

    # WARN: unresolved would-suppress (audit mode)
    for etype, ets in st.unresolved_warn:
        if etype == "would_suppress":
            age = now_ts - ets
            return (
                1,
                f"Audit would-suppress {age}s ago; "
                f"would_suppress={st.would_suppress} suppressions={st.suppressions}"
            )

    # WARN: unresolved transition
    for etype, ets in st.unresolved_warn:
        if etype == "transition":
            age = now_ts - ets
            return (
                1,
                f"Transition observed {age}s ago; "
                f"{st.transitions} transitions, {st.suppressions} suppressions"
            )

    # WARN: adaptive learning incomplete
    rs = ad.get("recommendation_status")
    if rs == "INSUFFICIENT_DATA":
        return (
            1,
            f"No active limiter event; learning INSUFFICIENT_DATA "
            f"({ad['total_samples']} samples, {ad['max_learning_days']}d)"
        )

    # OK: idle
    if st.transitions == 0 and st.suppressions == 0 and st.would_suppress == 0:
        return (0, "No active limiter event")

    # OK: transitions observed but no longer within retention
    return (0, f"No active limiter event; {st.transitions} transitions aged out")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cursor_mail = read_cursor("mail")
    cursor_telegram = read_cursor("telegram")

    state_mail = ChannelState("mail", LOG_MAIL, LOG_MAIL_LEGACY)
    state_telegram = ChannelState("telegram", LOG_TELEGRAM, LOG_TELEGRAM_LEGACY)

    # Update log mtimes for staleness check
    for st in (state_mail, state_telegram):
        ident = get_file_identity(st.log_path)
        if ident:
            st.log_mtime = ident[3]

    # Parse new events
    mail_events = read_and_parse("mail", LOG_MAIL, cursor_mail, LOG_MAIL_LEGACY)
    telegram_events = read_and_parse("telegram", LOG_TELEGRAM, cursor_telegram, LOG_TELEGRAM_LEGACY)

    for ev in mail_events:
        classify_event(ev, state_mail)
    for ev in telegram_events:
        classify_event(ev, state_telegram)

    # Read adaptive state
    adaptive_mail = read_adaptive_state("mail")
    adaptive_telegram = read_adaptive_state("telegram")

    # Persist cursor
    write_cursor("mail", cursor_mail)
    write_cursor("telegram", cursor_telegram)

    # Produce output
    output = produce_services(state_mail, state_telegram, adaptive_mail, adaptive_telegram)
    print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
