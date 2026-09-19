#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""check_vpn_tunnels.py - CheckMK VPN tunnels check.

OpenVPN: enumerates configured instances via UCI/nethsec, connected clients
via nethsec.ovpn.list_connected_clients() (openvpn-status socket).
WireGuard: peer count via nethsec.inventory.fact_wireguard() (config-level,
authoritative), liveness/freshness via 'wg show' (not exposed by the library).
"""

import shutil
import subprocess
import sys
import time

VERSION = "1.3.0"
SERVICE = "VPN.Tunnels"

# A WireGuard peer is considered active if it handshaked within this window,
# per doc/check_vpn_tunnels.md. The previous implementation only checked
# "handshake timestamp is nonzero, ever" - a peer that handshaked once and
# then went silent stayed "active" forever (permanent false-OK).
WG_HANDSHAKE_FRESH_SECONDS = 180

try:
    from euci import EUci
    EUCI_AVAILABLE = True
except ImportError:
    EUci = None
    EUCI_AVAILABLE = False


def count_openvpn_tunnels():
    """Count enabled OpenVPN instances and their connected clients.

    Replaces the previous file-based "," + "Connected" substring heuristic,
    which miscounted the openvpn-status CSV header line as a connected
    client (the header itself contains "Connected Since" - both a comma and
    the word "Connected") while real client rows (whose "Connected Since"
    field is an actual timestamp, not the literal word "Connected") never
    matched at all.

    Also replaces a later bug where every instance was queried with a
    hardcoded type="subnet", regardless of its actual role/topology. Verified
    live: a healthy, ping-verified p2p (site-to-site) OpenVPN tunnel returns
    {} from list_connected_clients(section, type="subnet") - CLIENT_LIST
    lines (what "subnet" parses) are only ever emitted by routed/subnet
    servers, never by p2p instances - so every p2p tunnel was permanently
    reported as 0 active clients (false CRITICAL/"All VPN down"), the mirror
    image of the earlier WireGuard permanent-false-OK bug. Role/topology
    detection below mirrors /usr/libexec/rpcd/ns.ovpntunnel (list_tunnels):
    outbound "client"/"ns_client" instances are always queried with
    type="p2p" and are considered active only once real traffic has flowed
    in both directions (bytes_received > 0 and bytes_sent > 0); everything
    else is queried with its own "topology" (default "subnet" - matches the
    UCI default set by ns.ovpnrw for road-warrior servers).
    """
    if not EUCI_AVAILABLE:
        return 0, 0
    try:
        from nethsec.utils import get_all_by_type
        from nethsec.ovpn import list_connected_clients
        with EUci() as u:
            instances = get_all_by_type(u, "openvpn", "openvpn")
    except Exception:
        return 0, 0

    total = 0
    active = 0
    for section, fields in instances.items():
        if fields.get("enabled") != "1":
            continue
        total += 1
        is_client = fields.get("client") == "1" or fields.get("ns_client") == "1"
        if is_client:
            vpn_type = "p2p"
        else:
            vpn_type = fields.get("topology", "subnet")
            if vpn_type not in ("subnet", "p2p"):
                vpn_type = "subnet"
        try:
            clients = list_connected_clients(section, type=vpn_type)
        except Exception:
            continue
        if not clients:
            continue
        if is_client:
            stats = clients.get("stats", {})
            if stats.get("bytes_received", 0) > 0 and stats.get("bytes_sent", 0) > 0:
                active += 1
        else:
            active += len(clients)
    return total, active


def count_wireguard_tunnels():
    """Count WireGuard peers: total from nethsec (config, authoritative),
    active from 'wg show' handshake freshness (not covered by the library).

    The previous implementation derived "total" from the number of
    interfaces and "active" from a per-peer handshake check across all
    interfaces - mixing interface count and peer count made active > total
    possible whenever an interface had more than one peer. Now both are
    peer-level counts, comparable in the same unit.
    """
    if not EUCI_AVAILABLE:
        return 0, 0
    try:
        from nethsec.inventory import fact_wireguard
        with EUci() as u:
            wg_facts = fact_wireguard(u)
    except Exception:
        wg_facts = {}

    servers = wg_facts.get("servers", {}) if wg_facts else {}
    total = sum(v.get("peers", 0) for v in servers.values())
    if total == 0:
        return 0, 0

    wg_bin = shutil.which("wg")
    if not wg_bin:
        return total, 0
    active = 0
    now = int(time.time())
    try:
        result = subprocess.run([wg_bin, "show", "interfaces"],
                                capture_output=True, text=True, timeout=10)
        ifaces = result.stdout.strip().split()
        for iface in ifaces:
            r = subprocess.run([wg_bin, "show", iface, "latest-handshakes"],
                               capture_output=True, text=True, timeout=10)
            for line in r.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        handshake_ts = int(parts[1])
                    except ValueError:
                        continue
                    if handshake_ts != 0 and (now - handshake_ts) <= WG_HANDSHAKE_FRESH_SECONDS:
                        active += 1
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return total, active


def main():
    ovpn_total, ovpn_active = count_openvpn_tunnels()
    wg_total, wg_active = count_wireguard_tunnels()
    total = ovpn_total + wg_total
    active = ovpn_active + wg_active
    inactive = total - active

    # Perfdata must be the single whitespace-free 3rd field (CheckMK's local
    # check parser never re-scans the free-text field for a later "|") -
    # putting it after the label as before produced zero graphed metrics.
    perfdata = f"total={total}|active={active}|inactive={inactive}"
    if total == 0:
        print(f"0 {SERVICE} {perfdata} No VPN configured")
    elif active == 0:
        print(f"2 {SERVICE} {perfdata} CRITICAL - All VPN down")
    elif active < total:
        print(f"1 {SERVICE} {perfdata} WARNING - Some VPN down")
    else:
        print(f"0 {SERVICE} {perfdata} OK - All VPN active")

    return 0


if __name__ == "__main__":
    sys.exit(main())
