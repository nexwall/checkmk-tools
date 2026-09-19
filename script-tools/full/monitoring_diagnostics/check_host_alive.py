#!/usr/bin/env python3
"""check_host_alive.py - CheckMK/Nagios active check: host UP/DOWN via multi-layer probe

Replaces check_icmp for hosts that block ICMP ping
(NethSecurity, host behind NAT/VPN, Windows with firewall, etc.).

Multi-layer strategy (stops at the first positive result):
  1. ICMP Ping 3x (1s timeout each) → if responds → OK
  2. TCP fallback on configurable ports → if it responds (open or rejected) → OK
  3. All timeout → CRITICAL (host offline)

Deploy on CheckMK server:
  cp check_host_alive.py /omd/sites/monitoring/local/lib/nagios/plugins/check_host_alive
  chmod +x /omd/sites/monitoring/local/lib/nagios/plugins/check_host_alive

WATO (Host Check Command) configuration:
  Setup → Hosts → Host Check Command → "Use a custom check plugin"
  Plugin: check_host_alive
  Arguments: -H $HOSTADDRESS$

  For hosts without CMK agent (SSH only):
  Arguments: -H $HOSTADDRESS$ --ports 22 443

  For hosts that also block ping (NethSecurity with restrictive rules):
  Arguments: -H $HOSTADDRESS$ --no-ping

Usage:
  check_host_alive -H 192.0.2.100
  check_host_alive -H ns8.dominio.it --ports 22 6556 443
  check_host_alive -H 10.0.0.50 --no-ping --ports 22 443 80
  check_host_alive -H 192.0.2.1 --timeout 3

Version: 1.0.0"""

import argparse
import errno
import re
import socket
import subprocess
import sys
import time
from typing import List, Optional, Tuple

VERSION = "1.0.0"
SCRIPT_NAME = "check_host_alive"

# Exit codes Nagios/CheckMK
OK       = 0
WARNING  = 1
CRITICAL = 2
UNKNOWN  = 3

# Port labels for readable output
PORT_NAMES = {
    22:   "SSH",
    6556: "CMK-Agent",
    443:  "HTTPS",
    80:   "HTTP",
    3389: "RDP",
    8080: "HTTP-alt",
    5985: "WinRM",
    5986: "WinRM-SSL",
    2222: "SSH-alt",
    8443: "HTTPS-alt",
}


def resolve_host(host: str) -> Optional[str]:
    """Resolve hostname to IP. Returns None if DNS fails."""
    try:
        return socket.gethostbyname(host)
    except socket.gaierror:
        return None


def ping_check(ip: str, count: int = 3, timeout_sec: int = 1) -> Tuple[bool, float]:
    """ICMP multiple ping.

    Returns:
        (is_up, avg_rtt_ms) — rtt_ms = -1 if unresponsive or unmeasurable"""
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), "-W", str(timeout_sec), ip],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=count * (timeout_sec + 1) + 3
        )
        output = result.stdout.decode("utf-8", errors="replace")

        if result.returncode != 0:
            return False, -1

        # Packet loss
        loss_m = re.search(r"(\d+)%\s+packet loss", output)
        loss = int(loss_m.group(1)) if loss_m else 100
        if loss == 100:
            return False, -1

        # RTT medio (Linux: "rtt min/avg/max/mdev = 0.4/0.6/0.8/...")
        rtt_m = re.search(r"rtt \S+ = [\d.]+/([\d.]+)/", output)
        rtt = float(rtt_m.group(1)) if rtt_m else -1.0

        return True, rtt

    except (subprocess.TimeoutExpired, OSError, Exception):
        return False, -1


def tcp_check(ip: str, port: int, timeout_sec: float = 2.0) -> Tuple[bool, str, float]:
    """Testing TCP connectivity on a port.

    Returns:
        (is_reachable, detail_msg, rtt_ms)
        is_reachable = True if port OPEN or REJECTED
                     (both indicate active host)"""
    port_name = PORT_NAMES.get(port, f"port-{port}")
    t0 = time.monotonic()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout_sec)
        err = sock.connect_ex((ip, port))
        sock.close()
        rtt = (time.monotonic() - t0) * 1000

        if err == 0:
            return True, f"TCP/{port_name} aperta", rtt
        elif err == errno.ECONNREFUSED:
            # Host responds with RST → is active, service not listening
            return True, f"TCP/{port_name} rifiutata (host attivo)", rtt
        else:
            return False, f"TCP/{port_name} timeout", -1

    except socket.timeout:
        return False, f"TCP/{port_name} timeout", -1
    except Exception as e:
        return False, f"TCP/{port_name} errore ({e})", -1


def build_perf_data(rtt_ms: float, packet_loss_pct: int) -> str:
    """Genera stringa performance data nel formato Nagios standard."""
    rta = f"{rtt_ms:.3f}" if rtt_ms >= 0 else "0.000"
    return f"rta={rta}ms;500.000;1000.000;0; pl={packet_loss_pct}%;20;80;0;100"


def main() -> int:
    parser = argparse.ArgumentParser(
        prog=SCRIPT_NAME,
        description=f"CheckMK active check: host UP/DOWN multi-layer v{VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  check_host_alive -H 192.0.2.100
  check_host_alive -H ns8.dominio.it --ports 22 6556 443
  check_host_alive -H 10.0.0.50 --no-ping --ports 22 443
  check_host_alive -H 192.0.2.1 --timeout 5"""
    )
    parser.add_argument(
        "-H", "--host", required=True,
        help="Hostname o indirizzo IP da controllare"
    )
    parser.add_argument(
        "--ports", nargs="+", type=int, default=[22, 6556, 443, 80],
        help="Porte TCP da provare se ping fallisce (default: 22 6556 443 80)"
    )
    parser.add_argument(
        "--no-ping", action="store_true",
        help="Salta ICMP ping (host che bloccano ICMP)"
    )
    parser.add_argument(
        "--timeout", type=float, default=2.0,
        help="Timeout TCP per porta in secondi (default: 2)"
    )
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s {VERSION}"
    )
    args = parser.parse_args()

    host = args.host.strip()

    # --- Risoluzione DNS ---
    ip = resolve_host(host)
    if not ip:
        print(f"CRITICAL - {host}: DNS non risolve (NXDOMAIN o timeout)")
        return CRITICAL

    # Label for output: show hostname if different from IP
    label = host if host != ip else ip

    # ─── Step 1: ICMP Ping ───────────────────────────────────────────────────
    if not args.no_ping:
        is_up, rtt = ping_check(ip, count=3, timeout_sec=1)
        if is_up:
            rtt_str = f"{rtt:.1f}ms" if rtt >= 0 else "n/a"
            perf = build_perf_data(rtt, 0)
            print(f"OK - {label} raggiungibile (ping {rtt_str}) | {perf}")
            return OK
        # Ping failed → try TCP fallback

    # ─── Step 2: TCP fallback ────────────────────────────────────────────────
    tcp_results: List[Tuple[bool, str, float]] = []
    for port in args.ports:
        reachable, detail, rtt = tcp_check(ip, port, args.timeout)
        tcp_results.append((reachable, detail, rtt))
        if reachable:
            ping_note = ", ping bloccato" if not args.no_ping else ""
            perf = build_perf_data(rtt, 100 if not args.no_ping else 0)
            print(f"OK - {label} raggiungibile ({detail}{ping_note}) | {perf}")
            return OK

    # ─── All timeout → CRITICAL ────────────────────── ──────────────────────
    fail_details = []
    if not args.no_ping:
        fail_details.append("ping 100% loss")
    fail_details += [d for _, d, _ in tcp_results]
    checks_summary = ", ".join(fail_details)

    perf = build_perf_data(-1, 100)
    print(f"CRITICAL - {label} NON raggiungibile ({checks_summary}) | {perf}")
    return CRITICAL


if __name__ == "__main__":
    sys.exit(main())
