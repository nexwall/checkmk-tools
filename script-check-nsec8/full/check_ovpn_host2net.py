#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""check_ovpn_host2net.py - CheckMK OpenVPN check.

Enumerates enabled OpenVPN instances via UCI/nethsec, and their connected
clients via nethsec.ovpn.list_connected_clients() (openvpn-status socket).
"""

import sys
from pathlib import Path

VERSION = "1.3.0"
SERVICE = "OVPN.HostToNet"

try:
    from euci import EUci
    EUCI_AVAILABLE = True
except ImportError:
    EUci = None
    EUCI_AVAILABLE = False


def find_running_instances():
    """Enumerate enabled host-to-net (road warrior) OpenVPN instances that are running.

    The previous implementation grepped /proc for a process whose cmdline
    contains both "openvpn" and "--config" - this misses any instance
    started with discrete flags instead of a single config-file argument
    (how NethSecurity/procd typically launches openvpn instances), leaving
    a running instance invisible to this check even while its status/socket
    shows real connected clients.

    "Running" is instead inferred from the presence of the instance's
    openvpn-status management socket (/var/run/openvpn_<instance>.socket),
    the same runtime artifact nethsec.ovpn.list_connected_clients() itself
    reads from - if the socket exists, the instance's management interface
    is up.

    Only instances tagged as road warrior (ns_tag contains "automated") are
    considered: this is the same marker NethSecurity's own ns.ovpnrw rpcd
    backend uses in its list_instances() to tell host-to-net instances apart
    from net2net tunnels (ns.ovpntunnel, which uses ns_name/ns_client instead
    and never sets ns_tag) or any other manually-defined "openvpn" UCI
    section. Without this filter, an enabled net2net tunnel or custom config
    would be miscounted as a "host2net" instance.
    """
    if not EUCI_AVAILABLE:
        return []
    try:
        from nethsec.utils import get_all_by_type
        with EUci() as u:
            instances = get_all_by_type(u, "openvpn", "openvpn")
    except Exception:
        return []
    if not instances:
        return []

    running = []
    for section, fields in instances.items():
        if fields.get("enabled") != "1":
            continue
        if "automated" not in (fields.get("ns_tag") or ""):
            continue
        socket_path = Path(f"/var/run/openvpn_{section}.socket")
        if socket_path.exists():
            running.append(section)
    return running


def count_connected_clients(instance):
    try:
        from nethsec.ovpn import list_connected_clients
        clients = list_connected_clients(instance, type="subnet")
        return len(clients) if clients else 0
    except Exception:
        return 0


def main():
    running = find_running_instances()
    if not running:
        print(f"0 {SERVICE} - OpenVPN not configured or not running")
        return 0
    total_clients = sum(count_connected_clients(i) for i in running)
    instance_count = len(running)
    # Perfdata must be the single whitespace-free 3rd field (CheckMK's local
    # check parser never re-scans the free-text field for a later "|") -
    # putting it after the label as before produced zero graphed metrics.
    perfdata = f"instances={instance_count}|clients={total_clients}"
    print(f"0 {SERVICE} {perfdata} Active: {instance_count} instance(s), {total_clients} client(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
