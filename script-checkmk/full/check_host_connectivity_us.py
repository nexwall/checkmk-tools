#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Check host connectivity: ARP for same-subnet hosts, ICMP fallback for cross-VLAN hosts.
# Variant for multi-VLAN environments where the monitoring server cannot reach
# remote subnets via ARP (layer-2 boundary).
#
# Deploy:
#   cp check_host_connectivity_us /omd/sites/monitoring/local/lib/nagios/plugins/check_host_connectivity_us
#   chmod +x /omd/sites/monitoring/local/lib/nagios/plugins/check_host_connectivity_us
#
# Requires: sudo nmap in /etc/sudoers.d/monitoring-nmap
#   monitoring ALL=(root) NOPASSWD: /usr/bin/nmap
#
# WATO (host check command):
#   Setup -> Hosts -> Host Check Command -> "Use a custom check plugin"
#   Plugin: check_host_connectivity_us
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


def get_local_networks():
    """Return list of (network_address, prefix_len) tuples for all local interfaces."""
    nets = []
    try:
        out = subprocess.run(
            ["ip", "-4", "addr", "show"],
            capture_output=True, text=True, timeout=5
        ).stdout
        for m in re.finditer(r"inet (\d+\.\d+\.\d+\.\d+)/(\d+)", out):
            ip_int = ip_to_int(m.group(1))
            prefix = int(m.group(2))
            mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
            nets.append((ip_int & mask, mask))
    except Exception:
        pass
    return nets


def ip_to_int(ip):
    parts = ip.split(".")
    r = 0
    for p in parts:
        r = (r << 8) | int(p)
    return r


def is_same_subnet(target_ip, local_nets):
    t = ip_to_int(target_ip)
    for net, mask in local_nets:
        if (t & mask) == net:
            return True
    return False


def nmap_arp(ip, timeout):
    """ARP scan (layer-2, same subnet only). Returns (is_up, rtt_ms)."""
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            ["sudo", "/usr/bin/nmap", "-sn", "-n", "--reason", ip],
            capture_output=True, text=True, timeout=timeout + 5
        )
        elapsed = (time.monotonic() - t0) * 1000
        if "Host is up" in r.stdout:
            m = re.search(r"\((\d+(?:\.\d+)?)s latency\)", r.stdout)
            rtt = float(m.group(1)) * 1000 if m else round(elapsed, 1)
            return True, round(rtt, 2)
        return False, -1
    except Exception:
        return False, -1


def nmap_icmp(ip, timeout):
    """ICMP ping via nmap --send-ip (crosses routers/VLANs). Returns (is_up, rtt_ms)."""
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            ["sudo", "/usr/bin/nmap", "-sn", "-n", "--send-ip", "--reason", ip],
            capture_output=True, text=True, timeout=timeout + 5
        )
        elapsed = (time.monotonic() - t0) * 1000
        if "Host is up" in r.stdout:
            m = re.search(r"\((\d+(?:\.\d+)?)s latency\)", r.stdout)
            rtt = float(m.group(1)) * 1000 if m else round(elapsed, 1)
            return True, round(rtt, 2)
        return False, -1
    except Exception:
        return False, -1


## Check

def check():
    parser = argparse.ArgumentParser(
        description=f"CheckMK active check: ARP (same subnet) or ICMP (cross-VLAN) v{VERSION}")
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

    local_nets = get_local_networks()
    same_l2 = is_same_subnet(ip, local_nets)
    method = "ARP" if same_l2 else "ICMP"

    is_up, rtt = False, -1
    for attempt in range(1 + args.retries):
        if same_l2:
            is_up, rtt = nmap_arp(ip, args.timeout)
        else:
            is_up, rtt = nmap_icmp(ip, args.timeout)
        if is_up:
            break
        if attempt < args.retries:
            time.sleep(1)

    if is_up:
        rtt_val = rtt if rtt >= 0 else 0
        print(f"OK - {host} reachable ({method}) | rta={rtt_val}ms;500;1000;0")
        sys.exit(OK)
    else:
        print(f"CRITICAL - {host} NOT reachable (no {method} response)")
        sys.exit(CRITICAL)


check()
