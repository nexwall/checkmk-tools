#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# CheckMK local check: OpenVPN net-to-net tunnel status
# Pings the gateway of each remote subnet to verify the tunnel is up.
# One CheckMK service per tunnel.

import subprocess
import sys

VERSION = "1.7.0"

# Remote subnet gateways — one entry per VPN tunnel.
# Format: (service_name, gateway_ip)
# Local subnet 192.168.10.0/24 is excluded (it is the monitoring server LAN).
TUNNELS = [
    ("Infra-Sede-Farmacia",                "192.168.1.254"),
    ("Infra-Sede-Consorzio",               "192.168.30.1"),
    ("Infra-Sede-Palazzetto-Dello-Sport-01", "192.168.40.1"),
    ("Infra-Sede-Palazzetto-Dello-Sport-02", "192.168.50.1"),
    ("Infra-Sede-Asilo",                   "192.168.60.1"),
    ("Infra-Sede-Colibri",                 "192.168.61.1"),
]

PING_COUNT = 1
PING_TIMEOUT = 1   # seconds per ping attempt — kept low to stay within check_mk_agent 10s timeout
# 6 tunnels × ~1s each = ~6s total, safely within agent timeout
# WATO max_check_attempts=5 + retry_interval=2min handles resilience at agent level


## Utils

def ping(ip):
    """Ping an IP address. Returns (reachable, rtt_avg_ms float or None, packet_loss_pct int)."""
    try:
        r = subprocess.run(
            ["ping", "-c", str(PING_COUNT), "-W", str(PING_TIMEOUT), "-q", ip],
            capture_output=True,
            text=True,
            timeout=PING_COUNT * PING_TIMEOUT + 3,
        )
        rtt_avg = None
        packet_loss = 100
        for line in r.stdout.splitlines():
            # Parse packet loss: "3 packets transmitted, 3 received, 0% packet loss"
            if "packet loss" in line:
                try:
                    packet_loss = int(line.split("%")[0].split()[-1])
                except:
                    pass
            # Parse avg rtt: "rtt min/avg/max/mdev = 1.2/2.3/3.4/0.1 ms"
            if "rtt min/avg/max" in line or "round-trip" in line:
                try:
                    rtt_avg = float(line.split("=")[1].strip().split("/")[1])
                except:
                    pass
        reachable = r.returncode == 0
        return reachable, rtt_avg, packet_loss
    except:
        return False, None, 100


## Check

def check():
    for name, gateway in TUNNELS:
        ok, rtt, pl = ping(gateway)
        rtt_val = rtt if rtt is not None else 0.0
        if ok:
            # FORMAT: STATE "SERVICE_NAME" perfdata status_text
            # perfdata: rtt (ms) and pl (packet loss %) separated by pipe (NO spaces)
            print('0 "{}" rtt={}|pl={} OK: tunnel UP (rtt={:.1f}ms, loss={}%)'.format(
                name, round(rtt_val, 2), pl, rtt_val, pl))
        else:
            print('2 "{}" rtt=0|pl=100 CRITICAL: tunnel DOWN - gateway {} unreachable'.format(
                name, gateway))


check()
