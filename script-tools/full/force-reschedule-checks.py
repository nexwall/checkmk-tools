#!/usr/bin/env python3
"""force-reschedule-checks.py - Force checks on all CheckMK hosts immediately

Usage:
    python3 force-reschedule-checks.py # force Check_MK on all hosts
    python3 force-reschedule-checks.py --service "PING" # force PING on all hosts
    python3 force-reschedule-checks.py --all # force ALL services on ALL hosts
    python3 force-reschedule-checks.py --host <hostname> # only a specific host

To be run as the 'monitoring' user on the CheckMK server.
Or from root: su - monitoring -c "python3 /opt/checkmk-tools/script-tools/full/force-reschedule-checks.py"

Version: 1.0.0"""

import socket
import select
import time
import argparse
import sys

VERSION = "1.0.0"
LIVE_SOCKET = "/omd/sites/monitoring/tmp/run/live"
NAGIOS_CMD = "/omd/sites/monitoring/tmp/run/nagios.cmd"


def livestatus_query(query: str) -> list[str]:
    """It sends a query to Livestatus and returns the response lines."""
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect(LIVE_SOCKET)
        s.sendall(query.encode())
        data = b""
        while True:
            r, _, __ = select.select([s], [], [], 2)
            if not r:
                break
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
        return [line for line in data.decode().split("\n") if line.strip()]
    finally:
        s.close()


def send_nagios_cmd(command: str) -> None:
    """Writes a command to the Nagios pipe."""
    with open(NAGIOS_CMD, "w") as f:
        f.write(command + "\n")


def force_service(host: str, service: str, ts: int) -> None:
    cmd = f"[{ts}] SCHEDULE_FORCED_SVC_CHECK;{host};{service};{ts}"
    send_nagios_cmd(cmd)


def force_host_check(host: str, ts: int) -> None:
    cmd = f"[{ts}] SCHEDULE_FORCED_HOST_CHECK;{host};{ts}"
    send_nagios_cmd(cmd)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"force-reschedule-checks.py v{VERSION} - Forza check CheckMK"
    )
    parser.add_argument(
        "--service", "-s",
        default="Check_MK",
        help="Nome servizio da forzare (default: Check_MK)"
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Limita a un solo host specifico"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        dest="all_services",
        help="Forza TUTTI i servizi di tutti gli host (più lento)"
    )
    parser.add_argument(
        "--ping",
        action="store_true",
        help="Forza anche il check PING (host check) per tutti gli host"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra cosa farebbe senza eseguire"
    )
    args = parser.parse_args()

    print(f"force-reschedule-checks.py v{VERSION}")
    print(f"Ora: {time.strftime('%Y-%m-%d %H:%M:%S')} (ts={int(time.time())})")
    print()

    ts = int(time.time())

    if args.all_services:
        # Force ALL services on all hosts
        if args.host:
            query = (
                "GET services\n"
                f"Filter: host_name = {args.host}\n"
                "Columns: host_name description\n"
                "OutputFormat: csv\n\n"
            )
        else:
            query = (
                "GET services\n"
                "Columns: host_name description\n"
                "OutputFormat: csv\n\n"
            )
        rows = livestatus_query(query)
        count = 0
        for row in rows:
            parts = row.split(";")
            if len(parts) < 2:
                continue
            host, service = parts[0], parts[1]
            if args.dry_run:
                print(f"  [DRY-RUN] SCHEDULE_FORCED_SVC_CHECK;{host};{service};{ts}")
            else:
                force_service(host, service, ts)
            count += 1
        print(f"{'[DRY-RUN] ' if args.dry_run else ''}Forzati {count} servizi su tutti gli host.")

    else:
        # Force the specified service (default: Check_MK)
        if args.host:
            query = (
                "GET services\n"
                f"Filter: description = {args.service}\n"
                f"Filter: host_name = {args.host}\n"
                "Columns: host_name\n"
                "OutputFormat: csv\n\n"
            )
        else:
            query = (
                "GET services\n"
                f"Filter: description = {args.service}\n"
                "Columns: host_name\n"
                "OutputFormat: csv\n\n"
            )
        hosts = livestatus_query(query)
        count = 0
        for host in hosts:
            if args.dry_run:
                print(f"  [DRY-RUN] SCHEDULE_FORCED_SVC_CHECK;{host};{args.service};{ts}")
            else:
                force_service(host, args.service, ts)
            count += 1
        print(f"{'[DRY-RUN] ' if args.dry_run else ''}Forzato '{args.service}' su {count} host.")

    # Optionally also forces host check (PING)
    if args.ping:
        if args.host:
            query = (
                "GET hosts\n"
                f"Filter: name = {args.host}\n"
                "Columns: name\n"
                "OutputFormat: csv\n\n"
            )
        else:
            query = (
                "GET hosts\n"
                "Columns: name\n"
                "OutputFormat: csv\n\n"
            )
        hosts = livestatus_query(query)
        count = 0
        for host in hosts:
            if args.dry_run:
                print(f"  [DRY-RUN] SCHEDULE_FORCED_HOST_CHECK;{host};{ts}")
            else:
                force_host_check(host, ts)
            count += 1
        print(f"{'[DRY-RUN] ' if args.dry_run else ''}Forzato host check (PING) su {count} host.")

    if not args.dry_run:
        print()
        print("Check forzati. Attendi 1-2 minuti e aggiorna la UI CheckMK.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
