#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Check host connectivity using nmap only (no subnet detection).
# nmap automatically selects ARP for same-subnet hosts and ICMP for cross-VLAN hosts
# when run as root/sudo - no manual layer-2 detection needed.
#
# Simpler variant of check_host_connectivity.py: one probe, let nmap decide the method.
#
# Deploy:
#   cp check_host_connectivity_nmap.py /omd/sites/monitoring/local/lib/nagios/plugins/check_host_connectivity_nmap
#   chmod +x /omd/sites/monitoring/local/lib/nagios/plugins/check_host_connectivity_nmap
#
# Requires: sudo nmap in /etc/sudoers.d/monitoring-nmap
#   monitoring ALL=(root) NOPASSWD: /usr/bin/nmap
#
# WATO (host check command):
#   Setup -> Hosts -> Host Check Command -> "Use a custom check plugin"
#   Plugin: check_host_connectivity_nmap
#   Arguments: -H $HOSTADDRESS$
#
# Version: 1.1.0

import argparse
import re
import socket
import subprocess
import sys
import time

VERSION = "1.1.0"

OK       = 0
WARNING  = 1
CRITICAL = 2
UNKNOWN  = 3


## Utils

def resolve_host(host):
    try:
        return socket.gethostbyname(host)
    except socket.gaierror:
        return ""


def nmap_probe(ip, timeout):
    """
    Run nmap -sn (ping scan) without forcing layer-2 or layer-3.
    When executed via sudo, nmap uses ARP for same-subnet hosts
    and ICMP echo for cross-VLAN hosts automatically.
    Returns (is_up, rtt_ms, method_str).
    """
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            ["sudo", "/usr/bin/nmap", "-sn", "-n", "--reason", ip],
            capture_output=True, text=True, timeout=timeout + 5
        )
        elapsed = (time.monotonic() - t0) * 1000

        if "Host is up" not in r.stdout:
            return False, -1, "nmap"

        m_rtt = re.search(r"\((\d+(?:\.\d+)?)s latency\)", r.stdout)
        rtt = float(m_rtt.group(1)) * 1000 if m_rtt else round(elapsed, 1)

        # Detect which method nmap actually used (for output label)
        method = "nmap"
        if "arp-response" in r.stdout.lower():
            method = "ARP"
        elif "echo-reply" in r.stdout.lower() or "icmp" in r.stdout.lower():
            method = "ICMP"

        return True, round(rtt, 2), method
    except subprocess.TimeoutExpired:
        return False, -1, "nmap"
    except Exception:
        return False, -1, "nmap"


## Check

def check():
    parser = argparse.ArgumentParser(
        description=f"CheckMK active check: nmap-only connectivity probe v{VERSION}")
    parser.add_argument("-H", "--host", required=True, help="Hostname or IP to check")
    parser.add_argument("--timeout", type=float, default=3.0,
                        help="Probe timeout in seconds (default: 3)")
    parser.add_argument("--retries", type=int, default=2,
                        help="Number of retry attempts on probe failure (default: 2)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = parser.parse_args()

    host = args.host.strip()

    ip = resolve_host(host)
    if not ip:
        print(f"CRITICAL - {host}: DNS resolution failed")
        sys.exit(CRITICAL)

    is_up, rtt, method = False, -1, "nmap"
    for attempt in range(1 + args.retries):
        is_up, rtt, method = nmap_probe(ip, args.timeout)
        if is_up:
            break
        if attempt < args.retries:
            time.sleep(1)

    if is_up:
        rtt_val = rtt if rtt >= 0 else 0
        print(f"OK - {host} reachable ({method}) | rta={rtt_val}ms;500;1000;0")
        sys.exit(OK)
    else:
        print(f"CRITICAL - {host} NOT reachable (no nmap response)")
        sys.exit(CRITICAL)


check()
