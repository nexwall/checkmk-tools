#!/usr/bin/env python3
"""check_hostgroup_service_status.py - Report service status for every host in a CheckMK hostgroup

PURPOSE:
  Read-only LiveStatus query that answers "what is the status of service X
  on every host belonging to hostgroup Y?". Produces a structured table with
  host state, service state, last check time, state age, and a short note
  extracted from the plugin output (e.g. "No route to host", "timed out").

  This does NOT modify any CheckMK/Nagios state. It only reads from the
  LiveStatus Unix socket.

USE (run as root or as the site user on the CheckMK server):
  python3 check_hostgroup_service_status.py --group workstation
  python3 check_hostgroup_service_status.py --group workstation --service "Check_MK Agent"
  python3 check_hostgroup_service_status.py --group workstation --service "Check_MK" --format csv
  python3 check_hostgroup_service_status.py --group workstation --site monitoring --socket /omd/sites/monitoring/tmp/run/live

ARGUMENTS:
  --group     Hostgroup name to inspect (required)
  --service   Service description to check (default: "Check_MK Agent")
  --site      OMD site name, used to derive the default socket path (default: monitoring)
  --socket    Explicit LiveStatus socket path (overrides --site derivation)
  --format    Output format: table (default) or csv
  --tz-offset Timezone offset in hours applied to displayed timestamps (default: 0 = UTC)

EXIT CODES:
  0 = query completed (regardless of service states found)
  1 = hostgroup not found / empty
  2 = LiveStatus connection error
  3 = invalid arguments

Version: 1.0.0
"""
import argparse
import socket as _socket
import sys
from datetime import datetime, timezone, timedelta

VERSION = "1.0.0"

STATE_MAP = {0: "OK", 1: "WARNING", 2: "CRITICAL", 3: "UNKNOWN"}
HOST_STATE_MAP = {0: "UP", 1: "DOWN", 2: "UNREACHABLE"}


def live_query(socket_path: str, query: str) -> str:
    """Send a LiveStatus query and return the raw response text."""
    if not query.endswith("\n\n"):
        query = query.rstrip("\n") + "\n\n"
    s = _socket.socket(_socket.AF_UNIX)
    s.settimeout(15)
    s.connect(socket_path)
    s.send(query.encode())
    s.shutdown(_socket.SHUT_WR)
    return s.makefile().read().strip()


def fmt_ts(ts: int, tz: timezone) -> str:
    if not ts:
        return "N/A"
    return datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d %H:%M")


def short_note(plugin_output: str) -> str:
    if not plugin_output:
        return ""
    if "No route to host" in plugin_output:
        return "No route to host (agent unreachable)"
    if "Timed Out" in plugin_output or "timed out" in plugin_output.lower():
        return "Service check timed out"
    if "Connection refused" in plugin_output:
        return "Connection refused"
    return plugin_output[:60]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report service status for every host in a CheckMK hostgroup (read-only LiveStatus query)."
    )
    parser.add_argument("--group", required=True, help="Hostgroup name to inspect")
    parser.add_argument("--service", default="Check_MK Agent",
                         help='Service description to check (default: "Check_MK Agent")')
    parser.add_argument("--site", default="monitoring", help="OMD site name (default: monitoring)")
    parser.add_argument("--socket", default=None,
                         help="Explicit LiveStatus socket path (overrides --site derivation)")
    parser.add_argument("--format", choices=["table", "csv"], default="table",
                         help="Output format (default: table)")
    parser.add_argument("--tz-offset", type=float, default=0,
                         help="Timezone offset in hours applied to displayed timestamps (default: 0 = UTC)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = parser.parse_args()

    socket_path = args.socket or f"/omd/sites/{args.site}/tmp/run/live"
    tz = timezone(timedelta(hours=args.tz_offset))

    try:
        hg_raw = live_query(
            socket_path,
            f"GET hostgroups\nFilter: name = {args.group}\nColumns: members num_hosts\nOutputFormat: python3\n",
        )
    except (OSError, ConnectionError) as exc:
        print(f"ERROR: cannot connect to LiveStatus socket '{socket_path}': {exc}", file=sys.stderr)
        return 2

    hg_rows = eval(hg_raw) if hg_raw else []
    if not hg_rows or hg_rows[0][1] == 0:
        print(f"ERROR: hostgroup '{args.group}' not found or has no members "
              f"(checked socket: {socket_path})", file=sys.stderr)
        return 1

    hosts_raw = live_query(
        socket_path,
        f"GET hosts\nFilter: host_groups >= {args.group}\nColumns: name state\nOutputFormat: python3\n",
    )
    host_rows = eval(hosts_raw) if hosts_raw else []
    host_state = {h[0]: h[1] for h in host_rows}

    svc_raw = live_query(
        socket_path,
        f"GET services\nFilter: host_groups >= {args.group}\nFilter: description = {args.service}\n"
        f"Columns: host_name state plugin_output last_check has_been_checked last_state_change checks_enabled\n"
        f"OutputFormat: python3\n",
    )
    svc_rows = eval(svc_raw) if svc_raw else []
    svc_map = {r[0]: r for r in svc_rows}

    names = sorted(host_state.keys())
    rows = []
    for name in names:
        hs = HOST_STATE_MAP.get(host_state[name], "?")
        svc = svc_map.get(name)
        if svc is None:
            rows.append((name, hs, "N/A", "N/A", "N/A", "N/A", "Service not present on this host"))
            continue
        _, state, plugin_output, last_check, has_been_checked, last_state_change, checks_enabled = svc
        if not has_been_checked:
            svc_state_str = "PENDING"
        else:
            svc_state_str = STATE_MAP.get(state, "?")
        monitored = "monitored" if checks_enabled else "unmonitored"
        rows.append((
            name, hs, svc_state_str, monitored,
            fmt_ts(last_check, tz), fmt_ts(last_state_change, tz),
            short_note(plugin_output),
        ))

    if args.format == "csv":
        print("host,host_state,service_state,monitoring_state,last_check,state_since,note")
        for r in rows:
            print(",".join(f'"{c}"' for c in r))
    else:
        header = f"{'HOST':<20}{'HOST_STATE':<13}{'SERVICE_STATE':<15}{'MONITORING':<13}{'LAST_CHECK':<18}{'STATE_SINCE':<18}NOTE"
        print(header)
        print("-" * len(header))
        for r in rows:
            print(f"{r[0]:<20}{r[1]:<13}{r[2]:<15}{r[3]:<13}{r[4]:<18}{r[5]:<18}{r[6]}")
        print()
        print(f"Total hosts in group '{args.group}': {len(rows)}")
        for state_label in ("OK", "WARNING", "CRITICAL", "UNKNOWN", "PENDING", "N/A"):
            count = sum(1 for r in rows if r[2] == state_label)
            if count:
                print(f"  {state_label}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
