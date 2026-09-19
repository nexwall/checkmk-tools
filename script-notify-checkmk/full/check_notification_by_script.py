#!/usr/bin/env python3
"""check_notification_by_script.py - Checkmk local check for notification activity
                                    grouped by notification script.

Parses notify.log (current + all rotated archives) and reports one service per
notification script type (e.g., ydea_la, asciimail, telegram, mail, etc.),
showing recent activity counts, last notification time, state distribution,
and the last few hosts/services that triggered notifications.

The lookback window is configurable via the environment variable
NOTIFY_LOOKBACK_MINUTES (default: 1440 = 24 hours).

Use on Checkmk monitoring servers (Ubuntu/Debian).

Version: 1.0.0"""

import os
import re
import sys
import gzip
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Dict, List, Tuple, Optional

VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Configuration (overridable via environment)
# ---------------------------------------------------------------------------

NOTIFY_LOG = os.environ.get(
    "NOTIFY_LOG_PATH",
    "/omd/sites/monitoring/var/log/notify.log"
)
LOOKBACK_MINUTES = int(os.environ.get("NOTIFY_LOOKBACK_MINUTES", "1440"))
MAX_LINES_PER_FILE = 100000  # safety cap per file

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Timestamp extraction: 2026-07-16 14:42:11,179
RE_TIMESTAMP = re.compile(r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})')

# "notifying X via Y" lines
RE_NOTIFICATION_VIA = re.compile(
    r'notifying\s+\S+\s+via\s+(\S+),'
)

# HOST NOTIFICATION: cmkadmin;HostName;DOWN;script_name;...
RE_HOST_NOTIFICATION = re.compile(
    r'sending command LOG;HOST NOTIFICATION: [^;]+;(?P<host>[^;]+);(?P<state>[^;]+);(?P<script>[^;]+);'
)

# SERVICE NOTIFICATION: cmkadmin;HostName;ServiceName;WARNING;script_name;...
RE_SERVICE_NOTIFICATION = re.compile(
    r'sending command LOG;SERVICE NOTIFICATION: [^;]+;(?P<host>[^;]+);(?P<service>[^;]+);(?P<state>[^;]+);(?P<script>[^;]+);'
)


def extract_timestamp(line: str) -> Optional[float]:
    """Extract the leading timestamp from a log line and return as UTC epoch."""
    m = RE_TIMESTAMP.match(line)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def update_stats(stats: dict, script: str, ts: float, ts_str: str,
                 host: str, service: Optional[str], state: str, 
                 now_ts: float, lookback: int) -> None:
    """Update the stats dict for a given script within the lookback window."""
    if ts < now_ts - lookback:
        return
    
    if script not in stats:
        stats[script] = {
            "total": 0,
            "hosts": set(),
            "services": set(),
            "states": defaultdict(int),
            "last_ts": ts_str,
            "last_host": "",
            "last_service_or_state": "",
            "details": [],
        }
    
    s = stats[script]
    s["total"] += 1
    s["hosts"].add(host)
    if service:
        s["services"].add(service)
    s["states"][state] += 1
    
    if ts_str > s["last_ts"]:
        s["last_ts"] = ts_str
        s["last_host"] = host
        s["last_service_or_state"] = f"{service} {state}" if service else f"HOST {state}"
    
    if len(s["details"]) < 5:
        label = f"{host}/{service} {state}" if service else f"{host} HOST {state}"
        if label not in s["details"]:
            s["details"].append(label)


def parse_lines(lines, stats: dict, now_ts: float, lookback: int) -> None:
    """Parse notification log lines and update stats."""
    for line in lines:
        ts = extract_timestamp(line)
        if ts is None:
            continue
        
        # Match HOST NOTIFICATION
        m = RE_HOST_NOTIFICATION.search(line)
        if m:
            update_stats(stats, m.group("script"), ts, 
                        datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                        m.group("host"), None, m.group("state"),
                        now_ts, lookback)
            continue
        
        # Match SERVICE NOTIFICATION
        m = RE_SERVICE_NOTIFICATION.search(line)
        if m:
            update_stats(stats, m.group("script"), ts,
                        datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                        m.group("host"), m.group("service"), m.group("state"),
                        now_ts, lookback)
            continue
        
        # Match "notifying via" lines (catch scripts without NOTIFICATION lines)
        m = RE_NOTIFICATION_VIA.search(line)
        if m:
            script = m.group(1)
            if ts < now_ts - lookback:
                continue
            if script not in stats:
                ts_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                stats[script] = {
                    "total": 0,
                    "hosts": set(),
                    "services": set(),
                    "states": defaultdict(int),
                    "last_ts": ts_str,
                    "last_host": "",
                    "last_service_or_state": "",
                    "details": [],
                }
            stats[script]["total"] += 1


def read_file(path: str) -> List[str]:
    """Read lines from a text file, with a safety cap."""
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", errors="replace") as f:
            return [next(f) for _ in range(MAX_LINES_PER_FILE)
                    ] if os.path.getsize(path) > 0 else []
    except (OSError, IOError):
        return []


def read_file_lines(path: str) -> List[str]:
    """Read lines from a text file with a safety cap."""
    if not os.path.isfile(path):
        return []
    lines = []
    try:
        with open(path, "r", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= MAX_LINES_PER_FILE:
                    break
                lines.append(line)
    except (OSError, IOError):
        pass
    return lines


def read_gz_lines(path: str) -> List[str]:
    """Read lines from a gzipped file with a safety cap."""
    if not os.path.isfile(path):
        return []
    lines = []
    try:
        with gzip.open(path, "rt", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= MAX_LINES_PER_FILE:
                    break
                lines.append(line)
    except (OSError, IOError):
        pass
    return lines


def collect_log_files(log_path: str) -> List[str]:
    """Collect all available notify.log files (current + rotated)."""
    files = []
    
    # Current log
    if os.path.isfile(log_path):
        files.append(log_path)
    
    base_dir = os.path.dirname(log_path)
    base_name = os.path.basename(log_path)
    
    # Rotated: notify.log.1, notify.log.2.gz, etc.
    for n in range(1, 20):
        plain = os.path.join(base_dir, f"{base_name}.{n}")
        gz = os.path.join(base_dir, f"{base_name}.{n}.gz")
        if os.path.isfile(gz):
            files.append(gz)
        elif os.path.isfile(plain):
            files.append(plain)
        else:
            break  # Stop at first gap
    
    return files


def print_service(script: str, data: dict) -> None:
    """Print a single Checkmk local check service for a notification script."""
    service_name = f"Notification_{script}"
    total = data["total"]
    last_ts = data["last_ts"]
    host_count = len(data["hosts"])
    service_count = len(data["services"])
    states = dict(data["states"])
    last_host = data["last_host"]
    last_item = data["last_service_or_state"]
    details = data["details"]

    # Build state summary string
    state_order = ["CRITICAL", "DOWN", "WARNING", "UNKNOWN", "OK", "UP"]
    state_parts = [f"{s}={states[s]}" for s in state_order if s in states]
    state_str = ", ".join(state_parts)

    # Detail text
    parts = [f"{total} notifications in {LOOKBACK_MINUTES}m"]
    if state_str:
        parts.append(state_str)
    parts.append(f"hosts={host_count}")
    if service_count > 0:
        parts.append(f"services={service_count}")
    if last_host:
        parts.append(f"last: {last_host} {last_item}")
    parts.append(f"({last_ts})")
    
    # Add recent details
    if details:
        details_str = "; ".join(details)
        parts.append(f"e.g. {details_str}")

    detail_str = "; ".join(parts)
    perfdata = f"total={total} hosts={host_count}"

    # Status logic: WARN if there were critical/down notifications
    non_ok = states.get("CRITICAL", 0) + states.get("DOWN", 0) + \
             states.get("WARNING", 0)
    if non_ok > 0 and states.get("CRITICAL", 0) + states.get("DOWN", 0) > 0:
        status = 1  # WARN
    else:
        status = 0  # OK
    
    print(f"{status} {service_name} - {detail_str} | {perfdata}")


def main():
    now_dt = datetime.now(timezone.utc)
    now_ts = now_dt.timestamp()
    lookback = LOOKBACK_MINUTES * 60

    stats = {}

    # Collect all log files
    log_files = collect_log_files(NOTIFY_LOG)
    
    if not log_files:
        print(f"3 Notification_via - Cannot access notify log: {NOTIFY_LOG} | total=0")
        return 1

    # Parse each file
    for fpath in log_files:
        if fpath.endswith(".gz"):
            lines = read_gz_lines(fpath)
        else:
            lines = read_file_lines(fpath)
        
        if lines:
            parse_lines(lines, stats, now_ts, lookback)

    # Output
    if not stats:
        print(f"0 Notification_via - No notification activity in the last {LOOKBACK_MINUTES}m | total=0")
        return 0

    for script in sorted(stats.keys()):
        print_service(script, stats[script])

    return 0


if __name__ == "__main__":
    sys.exit(main())
