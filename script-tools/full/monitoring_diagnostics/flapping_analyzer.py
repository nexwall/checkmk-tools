#!/usr/bin/env python3
"""flapping_analyzer.py - Interactive flapping threshold analysis for CheckMK/Nagios

Analyses Nagios log archives and Livestatus data for specified hosts, computes
flap percentage distributions, and interactively recommends flapping detection
thresholds based on real historical data.

Usage:
    python3 flapping_analyzer.py marcatempo-colibri marcatempo-asilo
    python3 flapping_analyzer.py --hosts marcatempo-colibri,marcatempo-asilo
    python3 flapping_analyzer.py --all-marca-tempi

Run as the 'monitoring' user on the CheckMK server, or from root with:
    su - monitoring -c "python3 /opt/checkmk-tools/script-tools/full/monitoring_diagnostics/flapping_analyzer.py <hosts>"

Supports Ubuntu, Debian, RHEL, NethServer, and NethSecurity hosts.

Version: 1.0.0"""

import socket
import time
import argparse
import sys
import os
import re
import glob
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Paths (overridable via environment variables)
# ---------------------------------------------------------------------------
NAGIOS_CFG = os.environ.get(
    "NAGIOS_CFG",
    "/omd/sites/monitoring/etc/nagios/nagios.d/flapping.cfg",
)
LIVE_SOCKET = os.environ.get(
    "LIVE_SOCKET",
    "/omd/sites/monitoring/tmp/run/live",
)
NAGIOS_LOG = os.environ.get(
    "NAGIOS_LOG",
    "/omd/sites/monitoring/var/nagios/nagios.log",
)
NAGIOS_ARCHIVE = os.environ.get(
    "NAGIOS_ARCHIVE",
    "/omd/sites/monitoring/var/nagios/archive",
)

CHECK_INTERVAL = 300  # seconds between checks (configurable)
WINDOW_CHECKS = 21    # Nagios standard window size

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_ts(ts):
    """Return a human-readable UTC string from a Unix timestamp."""
    if ts == 0:
        return "N/A"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def plural(n, singular="", plural="s"):
    return singular if n == 1 else plural


def pct_bar(value, width=20):
    """Return a simple ASCII bar representing a percentage."""
    filled = int(value / 100 * width)
    return "[" + "#" * filled + "." * (width - filled) + f"] {value:5.1f}%"


# ---------------------------------------------------------------------------
# Livestatus queries
# ---------------------------------------------------------------------------

def livestatus_query(query):
    """Send a query to the Livestatus Unix socket and return response lines."""
    s = socket.socket(socket.AF_UNIX)
    try:
        s.settimeout(5)
        s.connect(LIVE_SOCKET)
        s.sendall(query.encode())
        s.shutdown(socket.SHUT_WR)
        data = b""
        while True:
            try:
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
            except socket.timeout:
                break
        return [line for line in data.decode().strip().split("\n") if line]
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Flapping configuration
# ---------------------------------------------------------------------------

def read_flapping_config():
    """Read the current flapping.cfg values and metadata."""
    result = {
        "low_service_flap_threshold": None,
        "high_service_flap_threshold": None,
        "low_host_flap_threshold": None,
        "high_host_flap_threshold": None,
        "enable_flap_detection": None,
        "owner": None,
        "mode": None,
        "mtime": None,
        "sha256": None,
        "path": NAGIOS_CFG,
    }
    path = Path(NAGIOS_CFG)
    if not path.exists():
        return result

    try:
        # Metadata
        st = path.stat()
        result["owner"] = f"{st.st_uid}:{st.st_gid}"
        result["mode"] = oct(st.st_mode & 0o777)
        result["mtime"] = st.st_mtime

        # SHA-256
        import hashlib
        h = hashlib.sha256()
        h.update(path.read_bytes())
        result["sha256"] = h.hexdigest()

        # Values
        for line in path.read_text().splitlines():
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                if k in result:
                    result[k] = v
    except Exception as e:
        print(f"Warning: could not read {NAGIOS_CFG}: {e}")

    return result


def find_backup_files():
    """List backup files of flapping.cfg in the same directory."""
    cfg_dir = Path(NAGIOS_CFG).parent
    pattern = Path(NAGIOS_CFG).name + ".bak*"
    backups = []
    for f in sorted(cfg_dir.glob(pattern)):
        backups.append({
            "path": str(f),
            "mtime": f.stat().st_mtime if f.exists() else 0,
        })
    return backups


def read_backup_values(backup_path):
    """Extract threshold values from a backup file."""
    values = {}
    try:
        for line in Path(backup_path).read_text().splitlines():
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                values[k] = v
    except Exception:
        pass
    return values


# ---------------------------------------------------------------------------
# Nagios log archive discovery
# ---------------------------------------------------------------------------

def find_nagios_logs():
    """Find the active log and all archived log files, sorted by age."""
    logs = []
    # Active log
    if os.path.isfile(NAGIOS_LOG):
        logs.append(NAGIOS_LOG)
    # Archived logs
    archive_dir = Path(NAGIOS_ARCHIVE)
    if archive_dir.is_dir():
        for f in sorted(archive_dir.glob("nagios-*.log")):
            logs.append(str(f))
    return logs


def get_log_time_range(log_path):
    """Extract first and last timestamp from a Nagios log file."""
    first_ts = None
    last_ts = None
    try:
        with open(log_path, "r") as f:
            for line in f:
                m = re.match(r"\[(\d+)\]", line)
                if m:
                    ts = int(m.group(1))
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts
    except Exception:
        pass
    return first_ts, last_ts


# ---------------------------------------------------------------------------
# Flapping event search
# ---------------------------------------------------------------------------

def search_flapping_events(hosts, log_paths, days=90):
    """
    Search Nagios log files for STARTED/STOPPED FLAPPING events.

    Returns a dict keyed by host:
        host -> {"HOST": {"STARTED": [...], "STOPPED": [...]},
                 "SERVICE": {"PING": {"STARTED": [...], "STOPPED": [...]}}}
    """
    now = time.time()
    cutoff = now - days * 86400

    flapping = {}
    for h in hosts:
        flapping[h] = {
            "HOST": {"STARTED": [], "STOPPED": []},
            "SERVICE": {},  # service_desc -> {"STARTED": [...], "STOPPED": [...]}
        }

    patterns = [
        # HOST FLAPPING ALERT: hostname;STARTED; ...
        re.compile(
            r"\[(\d+)\]\s+HOST\s+FLAPPING\s+ALERT:\s+(\S+);(STARTED|STOPPED);"
        ),
        # SERVICE FLAPPING ALERT: hostname;service_desc;STARTED|STOPPED; ...
        re.compile(
            r"\[(\d+)\]\s+SERVICE\s+FLAPPING\s+ALERT:\s+(\S+);(\S+);(STARTED|STOPPED);"
        ),
    ]

    host_set = set(hosts)

    for log_path in log_paths:
        try:
            with open(log_path, "r", errors="replace") as f:
                for line in f:
                    m1 = patterns[0].search(line)
                    if m1:
                        ts, hostname, event_type = m1.groups()
                        ts = int(ts)
                        if ts < cutoff:
                            continue
                        if hostname in host_set:
                            flapping[hostname]["HOST"][event_type].append((ts, log_path))
                        continue

                    m2 = patterns[1].search(line)
                    if m2:
                        ts, hostname, svc_desc, event_type = m2.groups()
                        ts = int(ts)
                        if ts < cutoff:
                            continue
                        if hostname in host_set:
                            svc_map = flapping[hostname]["SERVICE"]
                            if svc_desc not in svc_map:
                                svc_map[svc_desc] = {"STARTED": [], "STOPPED": []}
                            svc_map[svc_desc][event_type].append((ts, log_path))
        except Exception as e:
            print(f"  Warning: could not read {log_path}: {e}")

    return flapping


# ---------------------------------------------------------------------------
# State history analysis (Livestatus log table)
# ---------------------------------------------------------------------------

def get_state_changes(host, days=90):
    """Fetch host state change events from Livestatus log table."""
    now = int(time.time())
    since = now - days * 86400

    query = (
        f"GET log\n"
        f"Filter: host_name = {host}\n"
        f"Filter: service_description =\n"
        f"Filter: class = 1\n"
        f"Filter: time >= {since}\n"
        f"Columns: time state\n"
    )

    try:
        lines = livestatus_query(query)
    except Exception as e:
        print(f"  Livestatus query failed for {host}: {e}")
        return []

    entries = []
    for line in lines:
        parts = line.split(";")
        if len(parts) >= 2:
            try:
                ts = int(parts[0])
                state = int(parts[-1])
                entries.append((ts, state))
            except ValueError:
                continue
    return sorted(entries, key=lambda x: x[0])


def get_service_state_changes(host, service, days=90):
    """Fetch service state change events from Livestatus log table."""
    now = int(time.time())
    since = now - days * 86400

    query = (
        f"GET log\n"
        f"Filter: host_name = {host}\n"
        f"Filter: service_description = {service}\n"
        f"Filter: class = 1\n"
        f"Filter: time >= {since}\n"
        f"Columns: time state\n"
    )

    try:
        lines = livestatus_query(query)
    except Exception as e:
        return []

    entries = []
    for line in lines:
        parts = line.split(";")
        if len(parts) >= 2:
            try:
                ts = int(parts[0])
                state = int(parts[-1])
                entries.append((ts, state))
            except ValueError:
                continue
    return sorted(entries, key=lambda x: x[0])


def simulate_flap_windows(events, check_interval=CHECK_INTERVAL, window_checks=WINDOW_CHECKS):
    """
    Simulate Nagios flapping detection over reconstructed check timeline.

    Returns a list of (timestamp, flap_percentage) for each check result,
    starting from the first full window.
    """
    if not events or len(events) < 2:
        return []

    first_ts = events[0][0]
    last_ts = events[-1][0]
    window_duration = check_interval * window_checks

    # Start a bit before the first event to build up initial state
    check_start = first_ts - window_duration
    if check_start < 0:
        check_start = 0
    check_start = (check_start // check_interval) * check_interval

    results = []
    ct = check_start
    while ct <= last_ts:
        state = 0
        for et, es in events:
            if et <= ct:
                state = es
            else:
                break
        results.append((ct, state))
        ct += check_interval

    flap_windows = []
    for i in range(window_checks, len(results)):
        window = results[i - window_checks:i + 1]
        changes = sum(1 for j in range(1, len(window)) if window[j][1] != window[j - 1][1])
        pct = (changes / (window_checks - 1)) * 100
        flap_windows.append((results[i][0], pct))

    return flap_windows


def compute_flap_stats(events, host, label="HOST", check_interval=CHECK_INTERVAL, window_checks=WINDOW_CHECKS):
    """
    Compute comprehensive flap statistics from state change events.

    Returns a dict with all statistics, or None if insufficient data.
    """
    if not events:
        return {
            "label": label,
            "total_changes": 0,
            "note": "NO STATE CHANGES FOUND",
        }

    flap_windows = simulate_flap_windows(events, check_interval, window_checks)

    if not flap_windows:
        return {
            "label": label,
            "total_changes": len(events),
            "note": "INSUFFICIENT DATA for flap% simulation",
        }

    pcts = [p for _, p in flap_windows]
    sorted_pcts = sorted(pcts)
    n = len(pcts)

    state0 = sum(1 for _, s in events if s == 0)
    state1 = sum(1 for _, s in events if s == 1)
    state2 = sum(1 for _, s in events if s == 2)

    # Zero-flap run analysis
    zero_runs = []
    current_run = 0
    for _, p in flap_windows:
        if p == 0:
            current_run += 1
        else:
            if current_run > 0:
                zero_runs.append(current_run * check_interval)
            current_run = 0
    if current_run > 0:
        zero_runs.append(current_run * check_interval)

    # Distribution buckets (in 5% increments)
    buckets = {}
    for threshold in range(0, 101, 5):
        count = sum(1 for p in pcts if p > threshold)
        buckets[threshold] = count

    return {
        "label": label,
        "total_changes": len(events),
        "total_checks": n + window_checks,
        "flap_windows": n,
        "mean": sum(pcts) / n,
        "median": sorted_pcts[n // 2],
        "min": min(pcts),
        "max": max(pcts),
        "pct_1": sorted_pcts[int(n * 0.01)],
        "pct_5": sorted_pcts[int(n * 0.05)],
        "pct_10": sorted_pcts[int(n * 0.10)],
        "pct_25": sorted_pcts[int(n * 0.25)],
        "pct_50": sorted_pcts[int(n * 0.50)],
        "pct_75": sorted_pcts[int(n * 0.75)],
        "pct_90": sorted_pcts[int(n * 0.90)],
        "pct_95": sorted_pcts[int(n * 0.95)],
        "pct_99": sorted_pcts[int(n * 0.99)],
        "pct_0": sum(1 for p in pcts if p == 0),
        "pct_gt_0": sum(1 for p in pcts if p > 0),
        "state0": state0,
        "state1": state1,
        "state2": state2,
        "zero_run_count": len(zero_runs),
        "zero_run_min": min(zero_runs) if zero_runs else 0,
        "zero_run_max": max(zero_runs) if zero_runs else 0,
        "zero_run_median": sorted(zero_runs)[len(zero_runs) // 2] if zero_runs else 0,
        "buckets": buckets,
    }


# ---------------------------------------------------------------------------
# Current runtime state
# ---------------------------------------------------------------------------

def get_current_state(hosts):
    """Query Livestatus for current flapping state and thresholds."""
    state = {}
    for h in hosts:
        state[h] = {"host": {}, "services": {}}

    for h in hosts:
        try:
            lines = livestatus_query(
                f"GET hosts\n"
                f"Filter: name = {h}\n"
                f"Columns: name is_flapping flappiness flap_detection_enabled state\n"
            )
            if lines:
                parts = lines[0].split(";")
                if len(parts) >= 5:
                    state[h]["host"] = {
                        "is_flapping": int(parts[1]),
                        "flappiness": float(parts[2]),
                        "flap_detection_enabled": int(parts[3]),
                        "state": int(parts[4]),
                    }
        except Exception as e:
            state[h]["host"]["error"] = str(e)

        try:
            lines = livestatus_query(
                f"GET services\n"
                f"Filter: host_name = {h}\n"
                f"Columns: host_name description is_flapping flappiness flap_detection_enabled state\n"
            )
            for line in lines:
                parts = line.split(";")
                if len(parts) >= 6:
                    svc_name = parts[1]
                    state[h]["services"][svc_name] = {
                        "is_flapping": int(parts[2]),
                        "flappiness": float(parts[3]),
                        "flap_detection_enabled": int(parts[4]),
                        "state": int(parts[5]),
                    }
        except Exception as e:
            pass

    return state


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def print_header(title):
    """Print a section header."""
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def print_subheader(title):
    print()
    print(f"--- {title} ---")


def report_flapping_events(flapping_data, hosts):
    """Print a summary of flapping events found."""
    print_header("HISTORICAL FLAPPING EVENTS")

    for h in hosts:
        data = flapping_data.get(h, {})
        host_data = data.get("HOST", {})
        services_data = data.get("SERVICE", {})

        started = len(host_data.get("STARTED", []))
        stopped = len(host_data.get("STOPPED", []))

        print(f"\n  {h} (HOST):")
        if started == 0 and stopped == 0:
            print(f"    No flapping events found in the search window.")
        else:
            if started:
                first_s = host_data["STARTED"][0][0]
                last_s = host_data["STARTED"][-1][0]
                print(f"    STARTED: {started} (first: {fmt_ts(first_s)}, last: {fmt_ts(last_s)})")
            if stopped:
                first_p = host_data["STOPPED"][0][0]
                last_p = host_data["STOPPED"][-1][0]
                print(f"    STOPPED: {stopped} (first: {fmt_ts(first_p)}, last: {fmt_ts(last_p)})")

        if services_data:
            for svc, svc_data in sorted(services_data.items()):
                s_started = len(svc_data.get("STARTED", []))
                s_stopped = len(svc_data.get("STOPPED", []))
                print(f"  {h} SERVICE [{svc}]:")
                if s_started or s_stopped:
                    if s_started:
                        first_s = svc_data["STARTED"][0][0]
                        last_s = svc_data["STARTED"][-1][0]
                        print(f"    STARTED: {s_started} (first: {fmt_ts(first_s)}, last: {fmt_ts(last_s)})")
                    if s_stopped:
                        first_p = svc_data["STOPPED"][0][0]
                        last_p = svc_data["STOPPED"][-1][0]
                        print(f"    STOPPED: {s_stopped} (first: {fmt_ts(first_p)}, last: {fmt_ts(last_p)})")
                else:
                    print(f"    No flapping events found.")


def report_flap_stats(stats, host_label=""):
    """Print flap statistics in a readable format."""
    if stats is None:
        return

    if "note" in stats:
        print(f"  {stats.get('label', '')}: {stats['note']}")
        return

    label = stats.get("label", "")
    print(f"\n  {label}:")
    print(f"    Total state changes: {stats['total_changes']}")
    print(f"    Simulated checks:    ~{stats.get('total_checks', 'N/A')}")
    print(f"    Flap% windows:       {stats['flap_windows']}")
    print(f"    State distribution:  UP={stats['state0']} DOWN={stats['state1']} OTHER={stats['state2']}")
    print()
    print(f"    Flap% statistics:")
    print(f"      Mean:   {stats['mean']:6.1f}%")
    print(f"      Median: {stats['median']:6.1f}%")
    print(f"      Min:    {stats['min']:6.1f}%")
    print(f"      Max:    {stats['max']:6.1f}%")
    print(f"      Percentiles:")
    print(f"         1st:  {stats['pct_1']:5.1f}%      5th:  {stats['pct_5']:5.1f}%     10th: {stats['pct_10']:5.1f}%")
    print(f"        25th:  {stats['pct_25']:5.1f}%     50th:  {stats['pct_50']:5.1f}%     75th: {stats['pct_75']:5.1f}%")
    print(f"        90th:  {stats['pct_90']:5.1f}%     95th:  {stats['pct_95']:5.1f}%     99th: {stats['pct_99']:5.1f}%")

    print(f"\n    Flap% distribution:")
    total = stats['flap_windows']
    for threshold in range(0, 100, 5):
        count = stats['buckets'].get(threshold, 0)
        if threshold == 0:
            pct = (stats['pct_0'] / total) * 100
            print(f"      Flap% = 0:    {stats['pct_0']:>6} ({pct:>5.1f}%)")
        else:
            pct = (count / total) * 100
            if pct > 0.05 or count > 0:
                print(f"      Flap% > {threshold:3}:    {count:>6} ({pct:>5.1f}%)")

    if stats.get("zero_run_count", 0) > 0:
        print(f"\n    Stable periods (0% flap):")
        print(f"      Count:   {stats['zero_run_count']}")
        print(f"      Min:     {stats['zero_run_min']:.0f}s ({stats['zero_run_min']/60:.1f}min)")
        print(f"      Max:     {stats['zero_run_max']:.0f}s ({stats['zero_run_max']/3600:.1f}h)")
        print(f"      Median:  {stats['zero_run_median']:.0f}s ({stats['zero_run_median']/60:.1f}min)")


def report_current_state(current_state, hosts):
    """Print current runtime flapping state."""
    print_header("CURRENT RUNTIME STATE")

    for h in hosts:
        host_info = current_state.get(h, {}).get("host", {})
        services = current_state.get(h, {}).get("services", {})

        if "error" in host_info:
            print(f"\n  {h}: Livestatus unavailable ({host_info['error']})")
            continue

        state_names = {0: "UP/OK", 1: "DOWN/WARN", 2: "UNREACHABLE/CRIT"}

        print(f"\n  {h} (HOST):")
        print(f"    is_flapping:          {host_info.get('is_flapping', '?')}")
        print(f"    flappiness:           {host_info.get('flappiness', '?')}%")
        print(f"    flap_detection:       {'ON' if host_info.get('flap_detection_enabled') else 'OFF'}")
        print(f"    current state:        {state_names.get(host_info.get('state', -1), '?')}")

        for svc, svc_info in sorted(services.items()):
            print(f"\n  {h} SERVICE [{svc}]:")
            print(f"    is_flapping:          {svc_info.get('is_flapping', '?')}")
            print(f"    flappiness:           {svc_info.get('flappiness', '?')}%")
            print(f"    flap_detection:       {'ON' if svc_info.get('flap_detection_enabled') else 'OFF'}")
            print(f"    current state:        {state_names.get(svc_info.get('state', -1), '?')}")


# ---------------------------------------------------------------------------
# Threshold recommendation engine
# ---------------------------------------------------------------------------

def recommend_thresholds(stats_map, hosts, current_config=None):
    """
    Analyze flap statistics for all hosts and recommend thresholds.

    Returns dict with recommendations and rationale.
    """
    print_header("THRESHOLD RECOMMENDATION ANALYSIS")

    # Collect all flap% distributions for analysis
    all_pcts = []
    host_max = {}
    host_95th = {}
    host_99th = {}
    host_info = {}

    for h in hosts:
        st = stats_map.get(h, {})
        host_info[h] = st
        if st and "note" not in st:
            # Reconstruct the full pct list from the flap_windows we already computed
            pcts = []
            # We can't get them from the stats dict alone
            pass

    # For each host, compute recommended thresholds
    host_recs = {}

    for h in hosts:
        st = stats_map.get(h, {})
        if not st or "note" in st:
            host_recs[h] = {"error": "Insufficient data"}
            continue

        max_pct = st["max"]
        pct_95 = st["pct_95"]
        pct_99 = st["pct_99"]
        mean = st["mean"]
        median = st["median"]
        pct_0 = st["pct_0"]
        total = st["flap_windows"]
        pct_0_frac = pct_0 / total if total > 0 else 1.0

        # Determine candidate thresholds
        # High threshold: should catch most bursts but not be too sensitive
        # We look at where the flap% distribution jumps

        # Find the lowest threshold where at least 5% of windows are below it
        # (meaning 95% of windows show higher flap% - too aggressive)
        # And the highest threshold where at least 95% of windows are below it
        # (meaning only 5% of windows trigger - not sensitive enough)

        # Strategy: high threshold near the 75th-90th percentile
        # low threshold near the median of non-zero values

        # Recommended high: round up pct_75 to nearest 5, but at least 5
        rec_high = max(5, ((st["pct_75"] + 4) // 5) * 5)
        # Alternative high: at pct_90 to be more permissive
        alt_high = max(5, ((st["pct_90"] + 4) // 5) * 5)
        # Conservative high: at pct_95
        cons_high = max(5, ((pct_95 + 4) // 5) * 5)

        # Low threshold: below typical non-zero flap%, but above 0
        # If median is 0, use mean of non-zero windows
        if median == 0 and st.get("pct_gt_0", 0) > 0:
            # Approximate mean of non-zero values
            # (mean * total - 0 * pct_0) / (total - pct_0)
            if total > pct_0:
                non_zero_mean = (mean * total) / (total - pct_0)
            else:
                non_zero_mean = 0
            rec_low = max(0, ((non_zero_mean - 2) // 5) * 5)
            # Round down to nearest 5, minimum 0
            if rec_low < 0:
                rec_low = 0
        elif median > 0:
            rec_low = max(0, ((median - 2) // 5) * 5)
        else:
            rec_low = 5  # default low

        # Ensure low < high
        if rec_low >= rec_high:
            rec_low = max(0, rec_high - 5)

        # Also provide a "recommended" set (balanced)
        # and a "sensitive" set (lower, for quick flapping detection)
        # and a "conservative" set (higher, for avoiding false positives)

        if rec_high >= 20:
            # High flap%, use the recommendations as-is
            recommended = {"high": rec_high, "low": rec_low}
            sensitive = {"high": max(5, rec_high - 10), "low": max(0, rec_low - 5)}
            conservative = {"high": rec_high + 5, "low": rec_low + 5}
        elif rec_high >= 10:
            recommended = {"high": rec_high, "low": rec_low}
            sensitive = {"high": max(5, rec_high - 5), "low": max(0, rec_low - 5)}
            conservative = {"high": rec_high + 5, "low": rec_low + 5}
        else:
            # Very low flap%, thresholds need to be sensitive
            recommended = {"high": 10, "low": 5}
            sensitive = {"high": 5, "low": 0}
            conservative = {"high": 15, "low": 10}

        host_recs[h] = {
            "recommended": recommended,
            "sensitive": sensitive,
            "conservative": conservative,
            "mean": mean,
            "median": median,
            "max": max_pct,
            "pct_95": pct_95,
            "pct_99": pct_99,
            "pct_0_frac": pct_0_frac,
            "stable_pct": 1.0 - pct_0_frac,
        }

    return host_recs


def print_recommendations(host_recs, hosts):
    """Print threshold recommendations for each host."""
    print_header("RECOMMENDED THRESHOLDS PER HOST")

    for h in hosts:
        rec = host_recs.get(h, {})
        if "error" in rec:
            print(f"\n  {h}: {rec['error']}")
            continue

        print(f"\n  {h}:")
        print(f"    Current statistics: mean={rec['mean']:.1f}%  median={rec['median']:.1f}%  "
              f"max={rec['max']:.1f}%")
        print(f"    95th percentile: {rec['pct_95']:.1f}%  "
              f"99th percentile: {rec['pct_99']:.1f}%")
        print(f"    Time at 0% flap: {rec['pct_0_frac']*100:.1f}%")

        print()
        print(f"    RECOMMENDED (balanced):")
        print(f"      high={rec['recommended']['high']:3d}  low={rec['recommended']['low']:3d}")
        if rec['recommended']['high'] is not None:
            high = rec['recommended']['high']
            # Estimate % of windows that would trigger flapping
            # This is approximate since we don't have the full distribution
            if rec['pct_95'] >= high:
                print(f"      ~{rec['pct_95']:.0f}% of windows would be BELOW this threshold")
            else:
                print(f"      ~{(1 - rec['pct_0_frac'])*100:.0f}% of windows would be ABOVE this threshold "
                      f"during activity")

        print()
        print(f"    SENSITIVE (enter flapping quickly):")
        print(f"      high={rec['sensitive']['high']:3d}  low={rec['sensitive']['low']:3d}")

        print()
        print(f"    CONSERVATIVE (avoid false positives):")
        print(f"      high={rec['conservative']['high']:3d}  low={rec['conservative']['low']:3d}")


def print_cross_host_summary(host_recs, hosts):
    """Print a summary table comparing thresholds across hosts."""
    print_header("CROSS-HOST THRESHOLD SUMMARY")

    print(f"  {'Host':<22} {'Mean':>6} {'Med':>6} {'Max':>6} {'95th':>6} "
          f"{'Rec H':>6} {'Rec L':>6} {'Sens H':>6} {'Sens L':>6} {'Cons H':>6} {'Cons L':>6}")
    print(f"  {'-'*22} {'-'*6} {'-'*6} {'-'*6} {'-'*6} "
          f"{'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6}")

    for h in hosts:
        rec = host_recs.get(h, {})
        if "error" in rec:
            print(f"  {h:<22} {'N/A':>6}")
        else:
            print(f"  {h:<22} {rec['mean']:>5.1f}% {rec['median']:>5.1f}% {rec['max']:>5.1f}% "
                  f"{rec['pct_95']:>5.1f}% "
                  f"{rec['recommended']['high']:>5d}  {rec['recommended']['low']:>5d} "
                  f"{rec['sensitive']['high']:>5d}  {rec['sensitive']['low']:>5d} "
                  f"{rec['conservative']['high']:>5d}  {rec['conservative']['low']:>5d}")


# ---------------------------------------------------------------------------
# Configuration diff and application
# ---------------------------------------------------------------------------

def format_config_diff(current_values, new_values, label="Planned change"):
    """Show a diff-like comparison of threshold values."""
    lines = []
    lines.append(f"  --- Current ({label})")
    lines.append(f"  +++ Proposed")
    keys = [
        "enable_flap_detection",
        "low_service_flap_threshold",
        "high_service_flap_threshold",
        "low_host_flap_threshold",
        "high_host_flap_threshold",
    ]
    for k in keys:
        curr = current_values.get(k, "?")
        new = new_values.get(k, curr)
        if str(curr) != str(new):
            lines.append(f"  - {k}={curr}")
            lines.append(f"  + {k}={new}")
        elif curr is not None:
            lines.append(f"    {k}={curr}  (unchanged)")
    return "\n".join(lines)


def apply_config(file_path, new_values):
    """
    Write new threshold values to flapping.cfg.

    Performs validation before writing. Returns (success, message).
    """
    path = Path(file_path)
    if not path.exists():
        return False, f"File not found: {file_path}"

    try:
        content = path.read_text()
    except Exception as e:
        return False, f"Cannot read {file_path}: {e}"

    updated = content
    replacements = {
        "enable_flap_detection",
        "low_service_flap_threshold",
        "high_service_flap_threshold",
        "low_host_flap_threshold",
        "high_host_flap_threshold",
    }

    for key in replacements:
        if key in new_values and new_values[key] is not None:
            pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
            if pattern.search(updated):
                updated = pattern.sub(f"{key}={new_values[key]}", updated)

    if updated == content:
        return False, "No changes generated (values unchanged)"

    # Validate: check for required keys
    for key in ["low_service_flap_threshold", "high_service_flap_threshold",
                 "low_host_flap_threshold", "high_host_flap_threshold"]:
        if not re.search(rf"^{re.escape(key)}=[\d.]+$", updated, re.MULTILINE):
            return False, f"Validation failed: {key} missing or invalid after replacement"

    try:
        path.write_text(updated)
        return True, "Configuration written"
    except Exception as e:
        return False, f"Write failed: {e}"


def verify_config(file_path):
    """Verify that the config file has valid syntax (all required keys present)."""
    path = Path(file_path)
    if not path.exists():
        return False, "File not found"
    try:
        content = path.read_text()
    except Exception:
        return False, "Cannot read"

    required = [
        "enable_flap_detection",
        "low_service_flap_threshold",
        "high_service_flap_threshold",
        "low_host_flap_threshold",
        "high_host_flap_threshold",
    ]
    for key in required:
        if not re.search(rf"^{re.escape(key)}=[\d.]+$", content, re.MULTILINE):
            return False, f"Missing or invalid: {key}"
    return True, "Valid"


def run_cmk_o():
    """Run cmk -O to activate configuration. Returns (exit_code, stdout+stderr)."""
    import subprocess
    try:
        result = subprocess.run(
            ["cmk", "-O"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return -1, "cmk -O timed out after 60s"
    except FileNotFoundError:
        return -2, "cmk command not found (not running as monitoring user?)"
    except Exception as e:
        return -3, str(e)


# ---------------------------------------------------------------------------
# Interactive application
# ---------------------------------------------------------------------------

def interactive_apply(current_config, backup_path):
    """Interactively configure and optionally apply new thresholds."""
    print_header("APPLY NEW THRESHOLDS")

    print(f"\n  Current configuration:")
    print(f"    {format_config_diff(current_config, {})}")
    print(f"\n  Backup will be created at: {backup_path}")

    # We'll gather the new values interactively
    new_values = {}

    print()
    print("  Enter new values (or press Enter to keep current):")

    for key, label_str in [
        ("enable_flap_detection", "Enable flap detection (0/1)"),
        ("low_service_flap_threshold", "Low service flap threshold"),
        ("high_service_flap_threshold", "High service flap threshold"),
        ("low_host_flap_threshold", "Low host flap threshold"),
        ("high_host_flap_threshold", "High host flap threshold"),
    ]:
        current = current_config.get(key, "")
        prompt = f"    {label_str} [{current}]: "
        try:
            val = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if val:
            new_values[key] = val
        else:
            new_values[key] = current

    print()
    print("  Proposed changes:")
    print(f"    {format_config_diff(current_config, new_values)}")

    try:
        confirm = input("\n  Apply these changes? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return None

    if confirm != "y":
        print("  Aborted.")
        return None

    # Backup
    import shutil
    try:
        shutil.copy2(NAGIOS_CFG, backup_path)
        print(f"  Backup created: {backup_path}")
    except Exception as e:
        print(f"  Backup failed: {e}")
        return None

    # Apply
    success, msg = apply_config(NAGIOS_CFG, new_values)
    if not success:
        print(f"  Apply failed: {msg}")
        return None

    # Restore owner/permissions
    try:
        import pwd, grp, stat as stat_mod
        st = Path(NAGIOS_CFG).stat()
        # Try to find monitoring user
        try:
            uid = pwd.getpwnam("monitoring").pw_uid
            gid = grp.getgrnam("monitoring").gr_gid
            os.chown(NAGIOS_CFG, uid, gid)
        except (KeyError, ImportError):
            pass
        os.chmod(NAGIOS_CFG, 0o640)
    except Exception:
        pass

    print(f"  Applied successfully.")

    # cmk -O
    print("  Running cmk -O...")
    rc, output = run_cmk_o()
    print(f"    Exit code: {rc}")
    for line in output.strip().split("\n"):
        print(f"    {line}")

    if rc == 0:
        print("\n  Configuration activated successfully!")
    else:
        print("\n  WARNING: cmk -O failed. Restoring backup...")
        import shutil
        shutil.copy2(backup_path, NAGIOS_CFG)
        print("  Backup restored.")
        rc2, out2 = run_cmk_o()
        print(f"  Rollback cmk -O exit code: {rc2}")

    return new_values if rc == 0 else None


def interactive_suggestion(stats_map, host_recs, hosts):
    """Interactively present recommendations and let user choose values."""
    print_header("INTERACTIVE THRESHOLD SUGGESTION")

    print("\n  Based on the analysis, here are recommended thresholds for each host.")
    print("  The 'RECOMMENDED' values aim to balance detection sensitivity")
    print("  with false-positive avoidance.")
    print()
    print("  Use these as a guide when choosing global thresholds.")

    print()
    print("  Key: high = enter flapping, low = exit flapping")
    print("  Flap% values are multiples of 5 (the Nagios resolution).")
    print("  Only host thresholds are usually adjusted per-group;")
    print("  service thresholds are kept at defaults unless there's a specific need.")
    print()

    # Collect the most common recommended values
    rec_highs = []
    rec_lows = []
    sens_highs = []
    sens_lows = []

    for h in hosts:
        rec = host_recs.get(h, {})
        if "error" not in rec:
            rec_highs.append(rec["recommended"]["high"])
            rec_lows.append(rec["recommended"]["low"])
            sens_highs.append(rec["sensitive"]["high"])
            sens_lows.append(rec["sensitive"]["low"])

    if rec_highs:
        # Mode (most common) of recommendations
        from collections import Counter
        common_rec_high = Counter(rec_highs).most_common(1)[0][0] if rec_highs else 10
        common_rec_low = Counter(rec_lows).most_common(1)[0][0] if rec_lows else 5
        common_sens_high = Counter(sens_highs).most_common(1)[0][0] if sens_highs else 5
        common_sens_low = Counter(sens_lows).most_common(1)[0][0] if sens_lows else 0

        print(f"  Suggested global values:")
        print()
        print(f"    RECOMMENDED (balanced):  high_host={common_rec_high}  low_host={common_rec_low}")
        print(f"                               high_service=30 (unchanged)  low_service=15 (unchanged)")
        print()
        print(f"    SENSITIVE:               high_host={common_sens_high}  low_host={common_sens_low}")
        print(f"                               high_service=30 (unchanged)  low_service=15 (unchanged)")
        print()
        print(f"    CUSTOM:                  (enter your own values)")

        print()
        print("  Choose an option:")
        print(f"    1) Recommended ({common_rec_high}/{common_rec_low})")
        print(f"    2) Sensitive ({common_sens_high}/{common_sens_low})")
        print(f"    3) Enter custom values")
        print(f"    4) Keep current (skip)")
        print(f"    5) Show per-host details again")

        try:
            choice = input("\n  Choice [1-5]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if choice == "1":
            return {
                "high_host_flap_threshold": str(common_rec_high),
                "low_host_flap_threshold": str(common_rec_low),
                "_source": f"recommended ({common_rec_high}/{common_rec_low})",
            }
        elif choice == "2":
            return {
                "high_host_flap_threshold": str(common_sens_high),
                "low_host_flap_threshold": str(common_sens_low),
                "_source": f"sensitive ({common_sens_high}/{common_sens_low})",
            }
        elif choice == "3":
            print()
            print("  Enter custom values (press Enter to skip a value):")
            try:
                hh = input("    high_host_flap_threshold: ").strip()
                lh = input("    low_host_flap_threshold: ").strip()
                hs = input("    high_service_flap_threshold (Enter=keep): ").strip()
                ls = input("    low_service_flap_threshold (Enter=keep): ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return None

            result = {}
            if hh:
                result["high_host_flap_threshold"] = hh
            if lh:
                result["low_host_flap_threshold"] = lh
            if hs:
                result["high_service_flap_threshold"] = hs
            if ls:
                result["low_service_flap_threshold"] = ls
            result["_source"] = "custom"
            return result if len(result) > 1 else None
        elif choice == "4":
            return None
        elif choice == "5":
            print_cross_host_summary(host_recs, hosts)
            print()
            # Recursive call
            return interactive_suggestion(stats_map, host_recs, hosts)
        else:
            print("  Invalid choice.")
            return None

    return None


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Interactive flapping threshold analysis for CheckMK/Nagios",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s marcatempo-colibri marcatempo-asilo\n"
            "  %(prog)s --hosts marcatempo-colibri,marcatempo-asilo\n"
            "  %(prog)s --hosts host1,host2 --days 30 --no-recommend\n"
        ),
    )
    parser.add_argument("hostnames", nargs="*", help="Host names to analyze")
    parser.add_argument("--hosts", help="Comma-separated list of host names")
    parser.add_argument("--days", type=int, default=90, help="Analysis window in days (default: 90)")
    parser.add_argument("--no-recommend", action="store_true",
                        help="Skip the recommendation phase (audit only)")
    parser.add_argument("--no-apply", action="store_true",
                        help="Skip the apply/activation phase")
    parser.add_argument("--check-interval", type=int, default=CHECK_INTERVAL,
                        help=f"Check interval in seconds (default: {CHECK_INTERVAL})")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")

    args = parser.parse_args()

    # Collect hostnames
    if args.hosts:
        hosts = [h.strip() for h in args.hosts.split(",") if h.strip()]
    else:
        hosts = args.hostnames

    if not hosts:
        parser.print_help()
        print("\nError: specify at least one host name")
        sys.exit(1)

    print(f"flapping_analyzer.py v{VERSION}")
    print(f"Analysis window: {args.days} days")
    print(f"Hosts: {', '.join(hosts)}")
    print()

    # -----------------------------------------------------------------------
    # 1. Configuration
    # -----------------------------------------------------------------------
    print_header("CURRENT FLAPPING CONFIGURATION")
    cfg = read_flapping_config()
    if cfg["path"] and Path(cfg["path"]).exists():
        print(f"\n  File: {cfg['path']}")
        print(f"  Owner: {cfg['owner']}  Mode: {cfg['mode']}  "
              f"Modified: {fmt_ts(cfg['mtime']) if cfg['mtime'] else '?'}")
        print(f"  SHA256: {cfg['sha256']}")
        print()
        print(f"  enable_flap_detection       = {cfg.get('enable_flap_detection', '?')}")
        print(f"  low_service_flap_threshold  = {cfg.get('low_service_flap_threshold', '?')}")
        print(f"  high_service_flap_threshold = {cfg.get('high_service_flap_threshold', '?')}")
        print(f"  low_host_flap_threshold     = {cfg.get('low_host_flap_threshold', '?')}")
        print(f"  high_host_flap_threshold    = {cfg.get('high_host_flap_threshold', '?')}")

        # Backup files
        backups = find_backup_files()
        if backups:
            print(f"\n  Backup files found: {len(backups)}")
            for b in backups[-5:]:  # show last 5
                vals = read_backup_values(b["path"])
                bname = Path(b["path"]).name
                bvals = "; ".join(f"{k}={v}" for k, v in sorted(vals.items()))
                print(f"    {bname}: {bvals}")
    else:
        print(f"\n  Config file not found: {cfg['path']}")
        print("  (This script should be run on the CheckMK server.)")

    # -----------------------------------------------------------------------
    # 2. Nagios logs
    # -----------------------------------------------------------------------
    print_header("NAGIOS LOG ANALYSIS")
    log_paths = find_nagios_logs()
    print(f"\n  Active log: {os.path.basename(NAGIOS_LOG) if os.path.isfile(NAGIOS_LOG) else 'NOT FOUND'}")
    archive_count = sum(1 for p in log_paths if "archive" in p)
    print(f"  Archived logs: {archive_count}")

    if not log_paths:
        print("\n  No Nagios logs found. Analysis cannot continue.")
        sys.exit(1)

    # Show time range
    first_ts, last_ts = None, None
    for lp in log_paths[:3]:  # first few
        ft, lt = get_log_time_range(lp)
        if ft is not None:
            if first_ts is None or ft < first_ts:
                first_ts = ft
        if lt is not None:
            if last_ts is None or lt > last_ts:
                last_ts = lt
    if first_ts and last_ts:
        print(f"  Log range: {fmt_ts(first_ts)} to {fmt_ts(last_ts)}")

    # -----------------------------------------------------------------------
    # 3. Flapping events search
    # -----------------------------------------------------------------------
    print(f"\n  Searching for flapping events in {len(log_paths)} log files...")
    flapping_data = search_flapping_events(hosts, log_paths, days=args.days)
    report_flapping_events(flapping_data, hosts)

    # -----------------------------------------------------------------------
    # 4. Current runtime state
    # -----------------------------------------------------------------------
    print("\n  Querying Livestatus for current state...")
    current_state = get_current_state(hosts)
    report_current_state(current_state, hosts)

    # -----------------------------------------------------------------------
    # 5. State history analysis
    # -----------------------------------------------------------------------
    print_header("STATE HISTORY ANALYSIS")

    stats_map = {}
    for h in hosts:
        print(f"\n  Analyzing {h}...")

        # Host state changes
        events = get_state_changes(h, days=args.days)
        print(f"    Host state changes found: {len(events)}")

        if events and len(events) >= 2:
            span = events[-1][0] - events[0][0]
            print(f"    Data span: {span / 86400:.1f} days")
            stats = compute_flap_stats(
                events, h, label="HOST",
                check_interval=args.check_interval,
            )
            stats_map[f"{h}_HOST"] = stats
            report_flap_stats(stats)
        else:
            print(f"    Insufficient data for flap% simulation.")

        # Service state changes (PING)
        svc_events = get_service_state_changes(h, "PING", days=args.days)
        if svc_events:
            print(f"    PING service changes found: {len(svc_events)}")
            svc_stats = compute_flap_stats(
                svc_events, h, label="PING",
                check_interval=args.check_interval,
            )
            stats_map[f"{h}_PING"] = svc_stats
            report_flap_stats(svc_stats)
        else:
            print(f"    No PING service state changes found.")

        # Look for other interesting services
        for svc_name, svc_info in current_state.get(h, {}).get("services", {}).items():
            if svc_name != "PING":
                other_events = get_service_state_changes(h, svc_name, days=args.days)
                if other_events:
                    print(f"\n    {svc_name} changes found: {len(other_events)}")
                    other_stats = compute_flap_stats(
                        other_events, h, label=svc_name,
                        check_interval=args.check_interval,
                    )
                    stats_map[f"{h}_{svc_name}"] = other_stats
                    report_flap_stats(other_stats)

    # -----------------------------------------------------------------------
    # 6. Recommendation phase
    # -----------------------------------------------------------------------
    if not args.no_recommend:
        # Build host-level stats map for recommendation
        host_stats = {}
        for h in hosts:
            host_key = f"{h}_HOST"
            if host_key in stats_map:
                host_stats[h] = stats_map[host_key]
            else:
                host_stats[h] = {}

        recs = recommend_thresholds(host_stats, hosts, current_config=cfg)
        print_recommendations(recs, hosts)
        print_cross_host_summary(recs, hosts)

        # Interactive suggestion
        if not args.no_apply:
            suggestion = interactive_suggestion(stats_map, recs, hosts)

            if suggestion:
                print_header("APPLYING THRESHOLD CHANGES")

                # Build the new values (preserve services, override hosts)
                new_values = {
                    "enable_flap_detection": cfg.get("enable_flap_detection", "1"),
                    "low_service_flap_threshold": cfg.get("low_service_flap_threshold", "15.0"),
                    "high_service_flap_threshold": cfg.get("high_service_flap_threshold", "30.0"),
                    "low_host_flap_threshold": cfg.get("low_host_flap_threshold", "15.0"),
                    "high_host_flap_threshold": cfg.get("high_host_flap_threshold", "30.0"),
                }
                # Apply the chosen host values
                for k in ["low_host_flap_threshold", "high_host_flap_threshold",
                          "low_service_flap_threshold", "high_service_flap_threshold",
                          "enable_flap_detection"]:
                    if k in suggestion:
                        new_values[k] = suggestion[k]

                print(f"\n  Planned changes (source: {suggestion.get('_source', '?')}):")
                print(f"    {format_config_diff(cfg, new_values)}")

                from datetime import datetime as dt
                ts_str = dt.now().strftime("%Y-%m-%d_%H%M%S")
                backup_path = f"{NAGIOS_CFG}.bak.{ts_str}"

                print(f"\n  Backup: {backup_path}")

                try:
                    confirm = input("\n  Apply and activate? [y/N]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print()
                    confirm = "n"

                if confirm == "y":
                    # Backup
                    import shutil
                    try:
                        shutil.copy2(NAGIOS_CFG, backup_path)
                        print(f"  Backup created.")
                    except Exception as e:
                        print(f"  Backup failed: {e}")
                        sys.exit(1)

                    # Write
                    success, msg = apply_config(NAGIOS_CFG, new_values)
                    if success:
                        # Fix perms
                        try:
                            import pwd, grp
                            uid = pwd.getpwnam("monitoring").pw_uid
                            gid = grp.getgrnam("monitoring").gr_gid
                            os.chown(NAGIOS_CFG, uid, gid)
                        except Exception:
                            pass
                        os.chmod(NAGIOS_CFG, 0o640)
                        print(f"  Configuration written.")

                        # cmk -O
                        print("  Running cmk -O...")
                        rc, output = run_cmk_o()
                        print(f"    Exit code: {rc}")
                        for line in output.strip().split("\n"):
                            if line.strip():
                                print(f"    {line}")

                        if rc == 0:
                            print("\n  SUCCESS: Thresholds applied and activated!")
                        else:
                            print("\n  ERROR: cmk -O failed. Restoring backup...")
                            shutil.copy2(backup_path, NAGIOS_CFG)
                            print("  Backup restored.")
                    else:
                        print(f"  Failed to write configuration: {msg}")
                else:
                    print("  Skipped.")
    else:
        print_header("RECOMMENDATION PHASE SKIPPED (--no-recommend)")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print_header("ANALYSIS COMPLETE")
    print(f"\n  Hosts analyzed: {', '.join(hosts)}")
    print(f"  Analysis window: {args.days} days")
    print(f"  Log files searched: {len(log_paths)}")


main()
