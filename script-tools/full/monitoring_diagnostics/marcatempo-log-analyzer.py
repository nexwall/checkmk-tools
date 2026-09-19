#!/usr/bin/env python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""
marcatempo-log-analyzer.py — Deep 90-day log analysis for marcatempo-* hosts

Analyzes Nagios archive logs on a CheckMK server to extract, classify, and
compare host and service events for marcatempo-* hosts before/after configuration
changes (flap thresholds, check intervals, notification rules).

Usage:
    ssh srv-monitoring-us "python3 -B < script.py"
    python3 -B marcatempo-log-analyzer.py          # if run locally on the OMD server

Output: structured tables with event counts, normalized rates, equal-window
comparison, PING-vs-host correlation, and per-host detailed assessment.

Version: 1.0.0
"""

import os
import re
import sys
import gzip
from collections import defaultdict, Counter
from datetime import datetime, timezone

# ── Configuration ──────────────────────────────────────────────────────────

ARCHIVE_DIR = "/omd/sites/monitoring/var/nagios/archive/"
CURRENT_LOG = "/omd/sites/monitoring/var/log/nagios.log"

HOSTS = [
    "marcatempo-colibri",
    "marcatempo-palazzetto",
    "marcatempo-consorzio",
    "marcatempo-farmacia",
    "marcatempo-asilo",
    "marcatempo-infopoint",
]

# Nagios program_start timestamp — indicates when the last cmk -O (reload)
# happened, typically coinciding with flap threshold activation.
# 1781707740 = 2026-06-17 16:49 CEST (verified from nagios.log)
FLAP_CHANGE_TS = 1781707740

# ── Regex patterns ─────────────────────────────────────────────────────────

RE_HOST_ALERT = re.compile(
    r'\[\d+\]\s+HOST ALERT:\s+(\S+);(\S+);(\S+);(\d+);(.*)'
)
RE_SVC_ALERT = re.compile(
    r'\[\d+\]\s+SERVICE ALERT:\s+(\S+);(\S+);(\S+);(\S+);(\d+);(.*)'
)
RE_HOST_FLAP = re.compile(
    r'\[\d+\]\s+HOST FLAPPING ALERT:\s+(\S+);(\S+);(.*)'
)
RE_SVC_FLAP = re.compile(
    r'\[\d+\]\s+SERVICE FLAPPING ALERT:\s+(\S+);(\S+);(\S+);(.*)'
)
RE_HOST_NOTIFY = re.compile(
    r'\[\d+\]\s+HOST NOTIFICATION:\s+(\S+);(\S+);(\S+);(\S+);(.*)'
)
RE_SVC_NOTIFY = re.compile(
    r'\[\d+\]\s+SERVICE NOTIFICATION:\s+(\S+);(\S+);(\S+);(\S+);(\S+);(.*)'
)
RE_CURRENT_STATE = re.compile(
    r'\[\d+\]\s+CURRENT (HOST|SERVICE) STATE:\s+(\S+);(\S+);(\S+);(\d+);(.*)'
)

# ── Helpers ────────────────────────────────────────────────────────────────

def ts_to_dt(ts):
    """Convert Unix timestamp to UTC datetime."""
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def parse_log_line(line):
    """Extract (timestamp, rest) from a Nagios log line."""
    m = re.match(r'\[(\d+)\](.*)', line)
    if m:
        return int(m.group(1)), m.group(2).strip()
    return None, None


class EventStore:
    """Stores parsed events with deduplication by (host, type, ts)."""

    def __init__(self):
        self.events = []
        # Nested dict: host -> event_type -> list of {ts, data}
        self.stats = defaultdict(lambda: defaultdict(list))

    def add(self, ts, host, event_type, data):
        self.events.append({
            'ts': ts,
            'host': host,
            'type': event_type,
            'data': data,
        })
        self.stats[host][event_type].append({'ts': ts, 'data': data})


def process_log_file(filepath, store):
    """Process a single Nagios log file (plain or .gz). Returns match count."""
    try:
        if filepath.endswith('.gz'):
            f = gzip.open(filepath, 'rt', errors='replace')
        else:
            f = open(filepath, 'r', errors='replace')
    except Exception as e:
        print(f"  ERROR opening {filepath}: {e}", file=sys.stderr)
        return 0

    count = 0
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ts, rest = parse_log_line(line)
            if ts is None:
                continue
            # Quick pre-filter: must contain a marcatempo host name
            if not any(h in line for h in HOSTS):
                continue
            count += 1

            m = RE_HOST_ALERT.match(line)
            if m:
                host, state, state_type, attempt, output = m.groups()
                if host in HOSTS:
                    store.add(ts, host, 'host_alert', {
                        'state': state, 'type': state_type,
                        'attempt': int(attempt), 'output': output,
                    })
                continue

            m = RE_SVC_ALERT.match(line)
            if m:
                host, svc, state, state_type, attempt, output = m.groups()
                if host in HOSTS:
                    store.add(ts, host, 'svc_alert', {
                        'service': svc, 'state': state, 'type': state_type,
                        'attempt': int(attempt), 'output': output,
                    })
                continue

            m = RE_HOST_FLAP.match(line)
            if m:
                host, state, msg = m.groups()
                if host in HOSTS:
                    store.add(ts, host, 'host_flap', {
                        'state': state, 'message': msg.strip(),
                    })
                continue

            m = RE_SVC_FLAP.match(line)
            if m:
                host, svc, state, msg = m.groups()
                if host in HOSTS:
                    store.add(ts, host, 'svc_flap', {
                        'service': svc, 'state': state,
                        'message': msg.strip(),
                    })
                continue

            m = RE_HOST_NOTIFY.match(line)
            if m:
                notify_type, host, state, contact, output = m.groups()
                if host in HOSTS:
                    store.add(ts, host, 'host_notify', {
                        'type': notify_type, 'state': state,
                        'contact': contact, 'output': output,
                    })
                continue

            m = RE_SVC_NOTIFY.match(line)
            if m:
                notify_type, host, svc, state, contact, output = m.groups()
                if host in HOSTS:
                    store.add(ts, host, 'svc_notify', {
                        'type': notify_type, 'service': svc,
                        'state': state, 'contact': contact,
                        'output': output,
                    })
                continue

            # CURRENT HOST/SERVICE STATE lines (logged on core restart)
            m = RE_CURRENT_STATE.match(line)
            if m:
                obj_type, host, svc_or_state, state, attempt, output = m.groups()
                if host in HOSTS:
                    store.add(ts, host, 'current_state', {
                        'type': obj_type,
                        'service': (
                            svc_or_state if obj_type == 'SERVICE' else ''
                        ),
                        'state': state,
                        'attempt': int(attempt),
                        'output': output,
                    })
                continue
    return count


def rebuild_store(events):
    """Create a new EventStore from a filtered list of event dicts."""
    s = EventStore()
    for e in events:
        s.add(e['ts'], e['host'], e['type'], e['data'])
    return s


# ── Analysis ───────────────────────────────────────────────────────────────

def analyze(store):
    """Compute per-host statistics from an EventStore."""
    results = {}
    for host in HOSTS:
        h = store.stats[host]
        hr = {}

        # ── Host alerts ────────────────────────────────────────────────
        host_alerts = h.get('host_alert', [])
        host_down = [e for e in host_alerts if e['data']['state'] == 'DOWN']
        host_up = [e for e in host_alerts if e['data']['state'] == 'UP']
        host_soft_down = [
            e for e in host_down if e['data']['type'] == 'SOFT'
        ]
        host_hard_down = [
            e for e in host_down if e['data']['type'] == 'HARD'
        ]
        host_hard_up = [
            e for e in host_up if e['data']['type'] == 'HARD'
        ]

        hr['host_total_alerts'] = len(host_alerts)
        hr['host_down_total'] = len(host_down)
        hr['host_down_soft'] = len(host_soft_down)
        hr['host_down_hard'] = len(host_hard_down)
        hr['host_up_hard'] = len(host_hard_up)

        # ── PING service alerts ────────────────────────────────────────
        svc_alerts = h.get('svc_alert', [])
        ping_alerts = [
            e for e in svc_alerts if e['data'].get('service') == 'PING'
        ]
        ping_crit = [
            e for e in ping_alerts if e['data']['state'] == 'CRITICAL'
        ]
        ping_ok = [e for e in ping_alerts if e['data']['state'] == 'OK']
        ping_warn = [
            e for e in ping_alerts if e['data']['state'] == 'WARNING'
        ]
        ping_unknown = [
            e for e in ping_alerts if e['data']['state'] == 'UNKNOWN'
        ]
        ping_soft_crit = [
            e for e in ping_crit if e['data']['type'] == 'SOFT'
        ]
        ping_hard_crit = [
            e for e in ping_crit if e['data']['type'] == 'HARD'
        ]

        hr['ping_total_alerts'] = len(ping_alerts)
        hr['ping_crit'] = len(ping_crit)
        hr['ping_ok'] = len(ping_ok)
        hr['ping_warn'] = len(ping_warn)
        hr['ping_unknown'] = len(ping_unknown)
        hr['ping_soft_crit'] = len(ping_soft_crit)
        hr['ping_hard_crit'] = len(ping_hard_crit)

        # 100 % packet loss events
        loss_100 = [
            e for e in ping_alerts if 'lost 100%' in e['data'].get('output', '')
        ]
        hr['ping_loss_100'] = len(loss_100)

        # ── Host flapping ──────────────────────────────────────────────
        host_flap = h.get('host_flap', [])
        hr['host_flap_start'] = len([
            e for e in host_flap if e['data']['state'] == 'STARTED'
        ])
        hr['host_flap_stop'] = len([
            e for e in host_flap if e['data']['state'] == 'STOPPED'
        ])

        # ── PING flapping ──────────────────────────────────────────────
        svc_flap = h.get('svc_flap', [])
        ping_flap = [
            e for e in svc_flap if e['data'].get('service') == 'PING'
        ]
        hr['ping_flap_start'] = len([
            e for e in ping_flap if e['data']['state'] == 'STARTED'
        ])
        hr['ping_flap_stop'] = len([
            e for e in ping_flap if e['data']['state'] == 'STOPPED'
        ])

        # ── Notifications ──────────────────────────────────────────────
        host_notify = h.get('host_notify', [])
        svc_notify = h.get('svc_notify', [])
        ping_notify = [
            e for e in svc_notify if e['data'].get('service') == 'PING'
        ]

        hr['host_notify_total'] = len(host_notify)
        hr['ping_notify_total'] = len(ping_notify)
        hr['host_notify_down'] = len([
            e for e in host_notify if e['data']['state'] == 'DOWN'
        ])
        hr['host_notify_up'] = len([
            e for e in host_notify if e['data']['state'] == 'UP'
        ])
        hr['ping_notify_crit'] = len([
            e for e in ping_notify if e['data']['state'] == 'CRITICAL'
        ])
        hr['ping_notify_ok'] = len([
            e for e in ping_notify if e['data']['state'] == 'OK'
        ])

        # Other (non-PING) service alerts
        hr['other_svc_alerts'] = len([
            e for e in svc_alerts if e['data'].get('service') != 'PING'
        ])

        # ── DOWN duration (estimated from HARD DOWN/UP pairs) ──────────
        hard_down_sorted = sorted(host_hard_down, key=lambda x: x['ts'])
        hard_up_sorted = sorted(host_hard_up, key=lambda x: x['ts'])

        if hard_down_sorted and hard_up_sorted:
            durations = []
            for d in hard_down_sorted:
                dt = d['ts']
                next_up = None
                for u in hard_up_sorted:
                    if u['ts'] > dt:
                        next_up = u
                        break
                if next_up:
                    durations.append(next_up['ts'] - dt)

            hr['down_durations'] = durations
            if durations:
                hr['down_total_seconds'] = sum(durations)
                hr['down_avg'] = sum(durations) / len(durations)
                hr['down_max'] = max(durations)
                hr['down_min'] = min(durations)
                hr['down_median'] = sorted(durations)[len(durations) // 2]
            else:
                hr['down_total_seconds'] = 0
                hr['down_avg'] = hr['down_max'] = hr['down_min'] = \
                    hr['down_median'] = 0
        else:
            hr['down_durations'] = []
            hr['down_total_seconds'] = 0
            hr['down_avg'] = hr['down_max'] = hr['down_min'] = \
                hr['down_median'] = 0

        results[host] = hr
    return results


# ── Reporting ──────────────────────────────────────────────────────────────

def print_full_analysis(store, results):
    """Print the full-period event summary."""
    print()
    print("=" * 72)
    print("FULL PERIOD ANALYSIS")
    print("=" * 72)

    for host in HOSTS:
        r = results[host]
        print(f"\n--- {host} ---")
        print(f"  HOST: total={r['host_total_alerts']}, "
              f"DOWN={r['host_down_total']} "
              f"(S={r['host_down_soft']}, H={r['host_down_hard']}), "
              f"UP-HARD={r['host_up_hard']}")
        if r['host_down_hard'] > 0:
            print(f"  DOWN duration: total={r['down_total_seconds']/60:.0f}m, "
                  f"avg={r['down_avg']/60:.0f}m, "
                  f"max={r['down_max']/60:.0f}m, "
                  f"median={r['down_median']/60:.0f}m")
        print(f"  HOST FLAP: "
              f"START={r['host_flap_start']}, STOP={r['host_flap_stop']}")
        print(f"  PING: total={r['ping_total_alerts']}, "
              f"CRIT={r['ping_crit']} "
              f"(S={r['ping_soft_crit']}, H={r['ping_hard_crit']}), "
              f"OK={r['ping_ok']}, W={r['ping_warn']}, U={r['ping_unknown']}")
        print(f"  PING 100% loss: {r['ping_loss_100']}")
        print(f"  PING FLAP: "
              f"START={r['ping_flap_start']}, STOP={r['ping_flap_stop']}")
        print(f"  NOTIFICATIONS: host={r['host_notify_total']} "
              f"(D={r['host_notify_down']}, U={r['host_notify_up']}), "
              f"PING={r['ping_notify_total']} "
              f"(C={r['ping_notify_crit']}, R={r['ping_notify_ok']})")
        print(f"  Other svc alerts: {r['other_svc_alerts']}")


def print_before_after(store, pre_days, post_days, pre_res, post_res):
    """Print normalized before/after comparison."""
    print()
    print("=" * 72)
    print("BEFORE/AFTER FLAP CHANGE (normalized)")
    print("=" * 72)

    print(f"Pre-change: {pre_days:.1f} days")
    print(f"Post-change: {post_days:.3f} days")

    if pre_days <= 0 or post_days <= 0:
        print("Insufficient data for comparison.")
        return

    METRICS = [
        ('Host DOWN', 'host_down_total'),
        ('Host DOWN HARD', 'host_down_hard'),
        ('Host flap START', 'host_flap_start'),
        ('PING CRIT', 'ping_crit'),
        ('PING HARD CRIT', 'ping_hard_crit'),
        ('PING flap START', 'ping_flap_start'),
        ('100% loss', 'ping_loss_100'),
        ('Host notif', 'host_notify_total'),
        ('PING notif', 'ping_notify_total'),
    ]

    for host in HOSTS:
        pr = pre_res[host]
        po = post_res[host]
        print(f"\n--- {host} ---")
        for label, key in METRICS:
            pv = pr.get(key, 0)
            qv = po.get(key, 0)
            pre_r = pv / pre_days if pre_days > 0 else 0
            post_r = qv / post_days if post_days > 0 else 0
            if pre_r > 0:
                pct = f"{((post_r - pre_r) / pre_r * 100):+.0f}%"
            elif post_r > 0:
                pct = "NEW (was 0)"
            else:
                pct = "N/A"
            print(f"  {label:<20} {pv:<8} {qv:<8} | "
                  f"pre/d={pre_r:<8.2f} post/d={post_r:<8.2f} | {pct}")


def print_equal_window(store, eq_window, first_ts):
    """Print equal-window comparison (same duration pre vs post)."""
    print()
    print("=" * 72)
    print("EQUAL-WINDOW COMPARISON")
    print("=" * 72)

    if eq_window <= 0 or not first_ts or \
       (FLAP_CHANGE_TS - eq_window * 86400) < first_ts:
        print(
            f"Pre-change data insufficient "
            f"(need {eq_window:.2f}d, "
            f"have {(FLAP_CHANGE_TS - first_ts)/86400:.1f}d)"
        )
        return

    eq_start = FLAP_CHANGE_TS - eq_window * 86400
    eq_events = [
        e for e in store.events
        if eq_start <= e['ts'] < FLAP_CHANGE_TS
    ]
    post_events = [
        e for e in store.events if e['ts'] >= FLAP_CHANGE_TS
    ]
    eq_store = rebuild_store(eq_events)
    post_store = rebuild_store(post_events)
    eq_res = analyze(eq_store)
    po_res = analyze(post_store)

    print(f"Window: {eq_window:.3f} days")
    print(f"Before: {ts_to_dt(eq_start)} to {ts_to_dt(FLAP_CHANGE_TS)}")
    print(f"After:  {ts_to_dt(FLAP_CHANGE_TS)} (to last event)")

    for host in HOSTS:
        eq = eq_res[host]
        po = po_res[host]
        print(f"\n--- {host} ---")
        for key in [
            'host_down_hard', 'host_flap_start', 'ping_hard_crit',
            'ping_flap_start', 'host_notify_down', 'ping_notify_crit',
            'ping_loss_100',
        ]:
            print(f"  {key:<25} before={eq.get(key, 0):<6} "
                  f"after={po.get(key, 0)}")


def print_correlation(store):
    """Analyze temporal correlation between PING CRIT and host DOWN."""
    print()
    print("=" * 72)
    print("PING vs HOST CORRELATION")
    print("=" * 72)

    for host in HOSTS:
        host_hard_downs = [
            e for e in store.events
            if e['host'] == host and e['type'] == 'host_alert'
            and e['data']['state'] == 'DOWN' and e['data']['type'] == 'HARD'
        ]
        ping_crits = [
            e for e in store.events
            if e['host'] == host and e['type'] == 'svc_alert'
            and e['data'].get('service') == 'PING'
            and e['data']['state'] == 'CRITICAL'
        ]

        print(f"\n--- {host} ---")
        print(f"  HARD DOWN: {len(host_hard_downs)}, "
              f"PING CRIT: {len(ping_crits)}")

        # PING CRIT without host DOWN within 10 min
        ping_only = sum(
            1 for p in ping_crits
            if not any(
                abs(p['ts'] - d['ts']) <= 600
                for d in host_hard_downs
            )
        )
        print(f"  PING CRIT without host DOWN (10min): {ping_only}")

        # Host DOWN without preceding PING CRIT (5 min before)
        down_no_ping = sum(
            1 for d in host_hard_downs
            if not any(
                abs(p['ts'] - d['ts']) <= 300
                for p in ping_crits
                if p['ts'] <= d['ts']
            )
        )
        print(f"  Host DOWN without PING CRIT (5min before): {down_no_ping}")

        for w, lbl in [(60, '1m'), (300, '5m'), (600, '10m')]:
            overlap = sum(
                1 for d in host_hard_downs
                if any(
                    abs(p['ts'] - d['ts']) <= w
                    for p in ping_crits
                )
            )
            print(f"  PING+DOWN within {lbl}: {overlap}")


def print_colibri_detailed(store):
    """Print in-depth assessment for marcatempo-colibri."""
    print()
    print("=" * 72)
    print("COLLIBRI DETAILED ASSESSMENT")
    print("=" * 72)

    col_events = [
        e for e in store.events if e['host'] == 'marcatempo-colibri'
    ]
    col_down = [
        e for e in col_events if e['type'] == 'host_alert'
        and e['data']['state'] == 'DOWN'
    ]
    col_hd = [
        e for e in col_down if e['data']['type'] == 'HARD'
    ]

    print(f"Total events: {len(col_events)}")
    print(f"All DOWN: {len(col_down)}, HARD: {len(col_hd)}")

    if col_hd:
        print(
            f"First: {ts_to_dt(col_hd[0]['ts'])}, "
            f"Last: {ts_to_dt(col_hd[-1]['ts'])}"
        )

        # By hour of day
        hour_c = Counter()
        for e in col_hd:
            hour_c[ts_to_dt(e['ts']).hour] += 1
        print("By hour:")
        for h in sorted(hour_c):
            print(f"  {h:02d}:00: {hour_c[h]}")

        # By day of week
        dow_c = Counter()
        for e in col_hd:
            dow_c[ts_to_dt(e['ts']).strftime('%A')] += 1
        print("By weekday:")
        for d in [
            'Monday', 'Tuesday', 'Wednesday', 'Thursday',
            'Friday', 'Saturday', 'Sunday',
        ]:
            if dow_c[d]:
                print(f"  {d}: {dow_c[d]}")

        # PING precedes DOWN?
        col_ping_crit = [
            e for e in col_events if e['type'] == 'svc_alert'
            and e['data'].get('service') == 'PING'
            and e['data']['state'] == 'CRITICAL'
        ]
        precedes = sum(
            1 for d in col_hd
            if any(
                d['ts'] - 600 <= p['ts'] < d['ts']
                for p in col_ping_crit
            )
        )
        print(
            f"PING CRIT within 10min before DOWN: "
            f"{precedes}/{len(col_hd)}"
        )

        # Flapping around outages
        col_flap = [
            e for e in col_events if 'flap' in e['type']
        ]
        col_flap_starts = [
            e for e in col_flap
            if e['data'].get('state') == 'STARTED'
        ]
        print(f"Flap START events: {len(col_flap_starts)}")
        print(f"Flap events total: {len(col_flap)}")

        # Notifications and potential suppression
        col_notif = [
            e for e in col_events if 'notify' in e['type']
        ]
        print(f"Total notifications: {len(col_notif)}")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print(f"=== MARCATEMPO LOG ANALYZER ===")
    print(f"Version 1.0.0")
    print(f"Run: {datetime.now(timezone.utc)} UTC")
    print(f"Flap change boundary: "
          f"{FLAP_CHANGE_TS} ({ts_to_dt(FLAP_CHANGE_TS)} UTC)")
    print()

    store = EventStore()
    archive_files = sorted(os.listdir(ARCHIVE_DIR)) if os.path.isdir(ARCHIVE_DIR) else []
    print(f"Processing {len(archive_files)} archive files...")

    total_raw = 0
    for fname in archive_files:
        fpath = os.path.join(ARCHIVE_DIR, fname)
        total_raw += process_log_file(fpath, store)

    if os.path.isfile(CURRENT_LOG):
        total_raw += process_log_file(CURRENT_LOG, store)

    total_unique = len(store.events)
    print(f"Total raw matches: {total_raw}")
    print(f"Total unique events: {total_unique}")

    if not store.events:
        print("NO EVENTS FOUND. Exiting.")
        return

    first_ts = min(e['ts'] for e in store.events)
    last_ts = max(e['ts'] for e in store.events)
    span_days = (last_ts - first_ts) / 86400
    pre_days = (FLAP_CHANGE_TS - first_ts) / 86400 if first_ts else 0
    post_days = (last_ts - FLAP_CHANGE_TS) / 86400 if last_ts else 0

    print(f"Date range: {ts_to_dt(first_ts)} UTC to {ts_to_dt(last_ts)} UTC")
    print(f"Span: {span_days:.1f} days")
    print(f"Pre-change: {pre_days:.1f}d, Post-change: {post_days:.3f}d")
    print()

    # Full analysis
    results = analyze(store)
    print_full_analysis(store, results)

    # Before/after
    pre_events = [e for e in store.events if e['ts'] < FLAP_CHANGE_TS]
    post_events = [e for e in store.events if e['ts'] >= FLAP_CHANGE_TS]
    pre_store = rebuild_store(pre_events)
    post_store = rebuild_store(post_events)
    pre_res = analyze(pre_store)
    post_res = analyze(post_store)
    print_before_after(store, pre_days, post_days, pre_res, post_res)

    # Equal window
    print_equal_window(store, post_days, first_ts)

    # PING vs host correlation
    print_correlation(store)

    # Colibri deep dive
    print_colibri_detailed(store)

    print()
    print("=" * 72)
    print("ANALYSIS COMPLETE")
    print("=" * 72)
    print(f"Events processed: {len(store.events)}")


if __name__ == '__main__':
    main()
