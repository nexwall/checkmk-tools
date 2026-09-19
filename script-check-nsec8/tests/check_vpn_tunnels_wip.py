#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""check_vpn_tunnels.py - CheckMK VPN tunnels check.

OpenVPN: enumerates configured instances via UCI/nethsec, connected clients
via nethsec.ovpn.list_connected_clients() (openvpn-status socket).
IPsec: enumerates configured "remote" connections via UCI/nethsec, liveness
via 'swanctl --list-sas --pretty' (nethsec.ipsec exposes no status query).
"""

import re
import shutil
import subprocess
import sys

VERSION = "1.6.0"
OPENVPN_SERVICE_PREFIX = "VPN.Tunnel.OVPN"
IPSEC_SERVICE_PREFIX = "VPN.Tunnel.IPsec"

try:
    from euci import EUci
    EUCI_AVAILABLE = True
except ImportError:
    EUci = None
    EUCI_AVAILABLE = False


def list_openvpn_tunnels():
    """Per-tunnel detail for every enabled, non-road-warrior OpenVPN instance.

    Returns a list of {"name": section, "label": str, "up": bool, "clients":
    int} - "up" is a single yes/no fact for that one named tunnel (unlike the
    aggregate total/active counts in count_openvpn_tunnels(), which lump
    every tunnel together and can't tell an operator *which* tunnel, out of
    several, is the one that's down). "clients" is the connected-session
    count for subnet/routed servers (0 or 1 for p2p/client instances, since a
    p2p tunnel has exactly one remote peer by definition). "label" is the
    human-facing name - the "ns_name" field NethSecurity's own UI sets (e.g.
    "Checkmk" for UCI section "ns_Checkmk") when present, falling back to the
    raw UCI section name otherwise (e.g. instances predating that field, or
    ones configured outside the ns-openvpn API) - used for the CheckMK
    service name instead of "name" so it doesn't leak the "ns_" UCI-section
    prefix into what an operator sees.

    Road-warrior (host-to-net) servers are excluded entirely, same as
    /usr/libexec/rpcd/ns.ovpntunnel::list_tunnels() ("skip road warrior
    servers" via `if 'ns_auth_mode' in vpn: continue` - the field ns.ovpnrw
    sets on every road-warrior instance it creates). They're already covered
    by check_ovpn_host2net.py, which treats 0 connected clients as normal
    (road warriors connect ad-hoc); counting them here too meant the same
    instance got conflicting verdicts across the two checks - a road warrior
    with no client currently connected made this check report CRITICAL "All
    VPN down" even when every real site-to-site tunnel was healthy.

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
        return []
    try:
        from nethsec.utils import get_all_by_type
        from nethsec.ovpn import list_connected_clients
        with EUci() as u:
            instances = get_all_by_type(u, "openvpn", "openvpn")
    except Exception:
        return []

    details = []
    for section, fields in instances.items():
        if fields.get("enabled") != "1":
            continue
        if "ns_auth_mode" in fields:
            continue  # road warrior server - covered by check_ovpn_host2net
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
            clients = None

        if is_client:
            stats = (clients or {}).get("stats", {})
            up = stats.get("bytes_received", 0) > 0 and stats.get("bytes_sent", 0) > 0
            count = 1 if up else 0
        else:
            count = len(clients) if clients else 0
            up = count > 0
        label = fields.get("ns_name") or section
        details.append({"name": section, "label": label, "up": up, "clients": count})
    return details


def count_openvpn_tunnels():
    """Aggregate total/active OpenVPN tunnel counts - see list_openvpn_tunnels()
    for the per-tunnel breakdown this is derived from."""
    details = list_openvpn_tunnels()
    total = len(details)
    active = sum(d["clients"] for d in details)
    return total, active


def _parse_swanctl_sas(text):
    """Parse `swanctl --list-sas --pretty` output into
    {conn_name: {"state": str | None, "children": [child_state, ...]}}.

    swanctl has no JSON output - --pretty is the indented vici event dump
    (2 spaces per nesting level, braces always closed at their opening
    line's indent), e.g.:

        list-sa event {
          ns_b4100974 {
            state = ESTABLISHED
            ...
            child-sas {
              ns_b4100974_tunnel_1 {
                state = INSTALLED
                ...
              }
            }
          }
        }

    Parsed by indent level rather than a general brace parser: a top-level
    connection block is a "  <name> {" line and its matching "  }" (same
    2-space indent); within it, only "    state = X" (the IKE_SA's own,
    4-space indent) is taken as the connection state - not any nested
    child-SA "state = X" at deeper indent, which would silently overwrite
    it and misreport the IKE_SA's own liveness.
    """
    lines = text.splitlines()
    n = len(lines)
    conns = {}
    i = 0
    while i < n:
        m = re.match(r'^  (\S+) \{$', lines[i])
        if not m:
            i += 1
            continue
        name = m.group(1)
        state = None
        children = []
        j = i + 1
        while j < n and lines[j] != '  }':
            sm = re.match(r'^    state = (\w+)$', lines[j])
            if sm:
                state = sm.group(1)
            cm = re.match(r'^      (\S+) \{$', lines[j])
            if cm:
                k = j + 1
                while k < n and lines[k] != '      }':
                    csm = re.match(r'^        state = (\w+)$', lines[k])
                    if csm:
                        children.append(csm.group(1))
                    k += 1
                j = k
            j += 1
        conns[name] = {"state": state, "children": children}
        i = j + 1
    return conns


def list_ipsec_tunnels():
    """Per-tunnel detail for every enabled IPsec (strongSwan) remote
    connection, same shape as list_openvpn_tunnels(): a list of {"name":
    section, "label": str, "up": bool}.

    "up" requires both the IKE_SA to be ESTABLISHED and at least one of its
    child SAs (the actual data tunnel) to be INSTALLED - an IKE_SA can
    finish negotiating (ESTABLISHED) while its child SA is still pending or
    was torn down (e.g. startaction=start racing the peer, or a rekey in
    flight), which would otherwise report a tunnel passing no traffic as up.

    "label" mirrors OpenVPN's: NethSecurity's own "ns_name" field when
    present, falling back to the raw UCI section name - so operators see
    the same human-facing name the UI shows them, not the internal
    "ns_<hash>" section id.
    """
    if not EUCI_AVAILABLE:
        return []
    try:
        from nethsec.utils import get_all_by_type
        with EUci() as u:
            remotes = get_all_by_type(u, "ipsec", "remote")
    except Exception:
        return []

    swanctl_bin = shutil.which("swanctl")
    sa_states = {}
    if swanctl_bin:
        try:
            result = subprocess.run([swanctl_bin, "--list-sas", "--pretty"],
                                     capture_output=True, text=True, timeout=10)
            sa_states = _parse_swanctl_sas(result.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            sa_states = {}

    details = []
    for section, fields in remotes.items():
        if fields.get("enabled") != "1":
            continue
        sa = sa_states.get(section, {})
        up = sa.get("state") == "ESTABLISHED" and "INSTALLED" in sa.get("children", [])
        label = fields.get("ns_name") or section
        details.append({"name": section, "label": label, "up": up})
    return details


def main():
    # One service per tunnel, named after it - with more than one
    # net-to-net/p2p tunnel, a single aggregate service could only ever say
    # "1 of 2 down", never which one. OpenVPN and IPsec are prefixed
    # separately ("VPN.Tunnel.OVPN.<label>" / "VPN.Tunnel.IPsec.<label>") so
    # the two label namespaces - both operator-chosen ns_name values - can't
    # collide.
    for tunnel in list_openvpn_tunnels():
        state = 0 if tunnel["up"] else 2
        text = "UP" if tunnel["up"] else "DOWN"
        print(f"{state} {OPENVPN_SERVICE_PREFIX}.{tunnel['label']} - {tunnel['label']}: {text}")

    for tunnel in list_ipsec_tunnels():
        state = 0 if tunnel["up"] else 2
        text = "UP" if tunnel["up"] else "DOWN"
        print(f"{state} {IPSEC_SERVICE_PREFIX}.{tunnel['label']} - {tunnel['label']}: {text}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
