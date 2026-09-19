#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""check_firewall_connections.py - CheckMK conntrack check.

Reads /proc/sys/net/netfilter/ for connection tracking stats.
"""

import sys
from pathlib import Path

VERSION = "1.1.2"
SERVICE = "Firewall.Connections"


def main():
    cnt = Path("/proc/sys/net/netfilter/nf_conntrack_count")
    mx = Path("/proc/sys/net/netfilter/nf_conntrack_max")
    if not cnt.exists() or not mx.exists():
        print(f"1 {SERVICE} - Conntrack not available")
        return 0
    # Previously unguarded: an unreadable or unexpectedly-formatted sysctl
    # file crashed with a raw Python traceback, violating this project's own
    # "no Python traceback" rule (full/README.md).
    try:
        current = int(cnt.read_text().strip())
        maxval = int(mx.read_text().strip())
    except (OSError, ValueError) as e:
        print(f"3 {SERVICE} - UNKNOWN - Cannot read conntrack counters ({e})")
        return 0
    pct = int(current * 100 / maxval) if maxval > 0 else 0
    if pct >= 90:
        st, txt = 2, "CRITICAL"
    elif pct >= 80:
        st, txt = 1, "WARNING"
    else:
        st, txt = 0, "OK"
    warn = int(maxval * 80 / 100)
    crit = int(maxval * 90 / 100)
    # CheckMK's local-check parser only treats the 3rd whitespace-delimited
    # field as performance data (metrics separated by "|"); everything from
    # the 4th field onward is plain status text, even if it contains "|".
    # (Verified against cmk/plugins/checkmk/agent_based/local.py: text after
    # the pipe in field 4 is never parsed into Metric objects.) Previously,
    # "current"/"max"/"percent" were appended after a "|" inside the status
    # text, so they looked like perfdata but were never actually graphed.
    # "percent" is now a real field-3 metric so it is actually graphable;
    # "current"/"max" are dropped as separate metrics since they duplicate
    # the value/max already carried by the "connections" metric.
    print(
        f"{st} {SERVICE} connections={current};{warn};{crit};0;{maxval}|percent={pct};80;90;0;100 "
        f"Active connections: {current}/{maxval} ({pct}%) - {txt}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
