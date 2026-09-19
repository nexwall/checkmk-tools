#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""check_wan_status.py - CheckMK WAN status check.

Per-WAN state comes from `ubus call network.interface.<name> status` (the
same API NethSecurity itself uses), not from manual /proc or /sys parsing:
"up" and the gateway ("route"/"nexthop") are both authoritative fields from
that call. Only real internet reachability - which by definition cannot come
from any API/library, since it must be tested at the moment it's asked - is
checked by this script itself, via `ping -I <device>` (bound to the specific
WAN's egress device, not the default route) against the same host list
NethSecurity's own dashboard "Internet" indicator uses
(packages/ns-api/files/ns.dashboard: check_internet()).

Two services are reported per WAN, each name doing only what it says -
deliberately not one compound service:
- WAN.Interface.<label>: a single, simple fact - is the interface itself up
  or down (from ubus "up"). Nothing else.
- WAN.Status.<label>: the overall verdict for this WAN link - interface
  up/down plus internet reachability. A DOWN here means an actual local
  problem (cable, config, hardware); "UP" but no internet reachable through
  that device most likely means an upstream/ISP problem instead, since the
  interface itself is fine.
"""

import json
import math
import subprocess
import sys
from pathlib import Path

VERSION = "2.0.1"
SERVICE = "WAN.Status"

# Same targets and majority-vote rule as NethSecurity's own dashboard
# "Internet" check (packages/ns-api/files/ns.dashboard: check_internet()) -
# reused here instead of inventing a different host list, and bound per-WAN
# via `ping -I <device>` instead of testing only the default route.
INTERNET_HOSTS = ("8.8.8.8", "one.one.one.one", "www.nethserver.org", "gstatic.com")
PING_TIMEOUT = 2

try:
    from euci import EUci
    EUCI_AVAILABLE = True
except ImportError:
    EUci = None
    EUCI_AVAILABLE = False


def _ubus_interface_status(section):
    """Call `ubus call network.interface.<section> status` and return parsed JSON, or None."""
    try:
        result = subprocess.run(
            ["ubus", "call", f"network.interface.{section}", "status"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception:
        pass
    return None


def _resolve_runtime_device(status, configured_device):
    """Resolve the runtime device for a UCI interface section.

    For static/DHCP ethernet interfaces the configured device (e.g. eth1) is
    already the runtime device. For dynamic protocols (PPPoE and similar) the
    kernel creates a separate runtime device (e.g. pppoe-wan) once the
    interface comes up - that's what ubus's own "l3_device" field reports.
    """
    if status:
        l3_device = status.get("l3_device")
        if l3_device:
            return l3_device
    return configured_device


def find_wan_interfaces():
    """Find WAN (red-role) interfaces using nethsec library.

    Returns a list of dicts: {"label": <logical name>, "device": <runtime device>}.

    "label" is the UCI interface section name (e.g. "tim_fibra",
    "vodafone_adsl" - whatever the admin actually named the WAN, which is
    commonly the ISP/operator name, not literally "wan") - this is what gets
    shown in CheckMK, since "eth1: UP" tells an operator nothing about which
    line is up, while "tim_fibra: UP" does. Falls back to the device name
    only if no matching UCI section is found (should not normally happen).

    Primary: nethsec.inventory.get_networks() with role == "red".
    Fallback: /proc/net/route for backward compatibility (library unavailable)
    """
    wan = []

    # Method 1: Use nethsec library (primary, robust)
    if EUCI_AVAILABLE:
        try:
            from nethsec.inventory import get_networks
            from nethsec.utils import get_all_by_type
            with EUci() as u:
                networks = get_networks(u)
                for dev, net in networks.items():
                    if net.get("props", {}).get("role") != "red":
                        continue
                    section = None
                    for s in get_all_by_type(u, "network", "interface"):
                        if u.get("network", s, "device", default=None) == dev:
                            section = s
                            break
                    label = section or dev
                    if not any(w["label"] == label for w in wan):
                        wan.append({"label": label, "device": dev})
                if wan:
                    return wan  # Success - don't fall through
        except (ImportError, Exception):
            pass

    # Method 2: Fallback to /proc/net/route only if library unavailable
    # (no UCI section lookup possible here, so label == device)
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "00000000":
                iface = parts[0].strip()
                if iface and not any(w["device"] == iface for w in wan):
                    wan.append({"label": iface, "device": iface})
        return wan
    except Exception:
        pass

    return wan  # Return whatever we found (even if empty)


def get_gateway_fallback(iface):
    """Parse /proc/net/route for a device's default-route gateway.

    Only used when ubus is unavailable - normally the gateway comes from the
    ubus status call's own "route"/"nexthop" field (see check_wan_state()).
    """
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 8 and parts[0] == iface and parts[1] == "00000000":
                gw_hex = parts[2]
                return ".".join(str(int(gw_hex[i:i + 2], 16)) for i in range(6, -1, -2))
    except Exception:
        pass
    return None


def check_wan_state(label, configured_device):
    """Return (device, up, gateway) for one WAN, API-first.

    "up" and "gateway" come from `ubus call network.interface.<label>
    status` (the same source NethSecurity's own UI relies on) whenever
    available. Falls back to /sys/class/net operstate + /proc/net/route
    parsing only if ubus itself is unavailable (e.g. running off-device).
    """
    status = _ubus_interface_status(label)
    device = _resolve_runtime_device(status, configured_device)
    if status is not None:
        up = bool(status.get("up"))
        gateway = None
        for route in status.get("route") or []:
            if route.get("target") == "0.0.0.0":
                gateway = route.get("nexthop")
                break
        return device, up, gateway

    # ubus unavailable - fall back to manual /sys + /proc parsing
    operstate_path = Path(f"/sys/class/net/{device}/operstate")
    up = operstate_path.exists() and operstate_path.read_text().strip() == "up"
    gateway = get_gateway_fallback(device) if up else None
    return device, up, gateway


def has_internet(device):
    """Real internet reachability for one specific WAN device.

    No API/library can answer this - it's inherently something that must be
    tested at the moment it's asked. Reuses the exact host list and
    majority-vote rule NethSecurity's own dashboard "Internet" indicator uses
    (ns.dashboard: check_internet()), bound to this WAN's own egress device
    via `ping -I <device>` instead of testing only the default route - a
    plain TCP probe to the gateway (the previous approach) proves only that
    the first hop answers on some port, which is neither necessary (most
    gateways don't run services) nor sufficient (a public-IP pool's gateway
    responding says nothing about whether that IP block actually routes to
    the internet) for "this WAN has working internet".
    """
    # Matches ns.dashboard's check_internet() exactly: "success >= len(hosts)/2"
    # (2 of 4, not 3 of 4 - a wrong len//2 + 1 off-by-one was caught by the
    # unit test in tests/test_check_wan_status.py before this shipped).
    needed = math.ceil(len(INTERNET_HOSTS) / 2)
    success = 0
    for host in INTERNET_HOSTS:
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", str(PING_TIMEOUT), "-I", device, host],
                capture_output=True, timeout=PING_TIMEOUT + 2,
            )
            if result.returncode == 0:
                success += 1
                if success >= needed:
                    return True
        except Exception:
            continue
    return False


def main():
    wan = find_wan_interfaces()
    if not wan:
        print(f"0 {SERVICE} - No WAN interfaces found")
        return 0

    total = len(wan)
    up_count = 0
    down_count = 0
    degraded = 0

    for w in wan:
        label = w["label"]
        device, up, gateway = check_wan_state(label, w["device"])

        # WAN.Interface.<label>: a single, simple fact - is the interface
        # itself up or down (from ubus). Nothing else. DOWN here is a local
        # problem (cable, config, hardware).
        print(f"{0 if up else 2} WAN.Interface.{label} - {'UP' if up else 'DOWN'}")

        # WAN.Status.<label>: the overall verdict for this WAN link - adds
        # internet reachability on top of the interface fact, so the message
        # can tell apart "local problem" (interface down) from "likely
        # upstream/ISP problem" (interface up, no real internet through it).
        if not up:
            status_state, text = 2, "DOWN"
            down_count += 1
        elif has_internet(device):
            status_state, text = 0, "UP"
            up_count += 1
        else:
            gw_note = f" (gateway {gateway} configured)" if gateway else ""
            status_state, text = 1, f"UP - no internet reachability, likely an upstream/ISP issue{gw_note}"
            up_count += 1
            degraded += 1
        print(f"{status_state} {SERVICE}.{label} - {label}: {text}")

    # Perfdata must be the single whitespace-free 3rd field (CheckMK's local
    # check parser never re-scans the free-text field for a later "|").
    perfdata = f"total={total}|up={up_count}|down={down_count}|degraded={degraded}"
    print(f"0 WAN.Metrics {perfdata} Total={total} Up={up_count} Down={down_count} Degraded={degraded}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
