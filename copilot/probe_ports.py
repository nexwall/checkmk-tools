#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Probe ports on a list of hosts to distinguish printers from PCs

import socket
import time

HOSTS = [
    "192.168.20.10",
    "192.168.20.33",
    "192.168.20.61",
    "192.168.20.62",
    "192.168.20.63",
    "192.168.20.64",
]

PORTS = {
    9100: "JetDirect(printer)",
    445:  "SMB(windows-pc)",
    631:  "IPP(printer)",
    3389: "RDP(pc)",
}


def tcp_open(ip, port, timeout=1.5):
    try:
        s = socket.socket()
        s.settimeout(timeout)
        s.connect((ip, port))
        s.close()
        return True
    except:
        return False


for host in HOSTS:
    found = []
    for port, label in PORTS.items():
        if tcp_open(host, port):
            found.append("p{}={}".format(port, label))
        time.sleep(0.3)
    result = ", ".join(found) if found else "no ports open"
    print("{:<18} {}".format(host, result))
