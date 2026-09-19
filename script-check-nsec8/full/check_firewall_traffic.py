#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""check_firewall_traffic.py - CheckMK firewall traffic check.

Uses nethsec (WAN/LAN zone-based device discovery) and /proc/net/dev for
byte/packet/error counters. No subprocess, no ubus.
"""

import sys
from pathlib import Path

VERSION = "1.4.0"
SERVICE = "Traffic"

# Alarm threshold for RX/TX error counters, per doc/check_firewall_traffic.md
ERROR_WARN = 100

try:
    from euci import EUci
    EUCI_AVAILABLE = True
except ImportError:
    EUci = None
    EUCI_AVAILABLE = False


def get_wan_lan_interfaces():
    """Restrict monitoring to real WAN/LAN devices via firewall zone membership.

    The previous implementation enumerated every device in /sys/class/net
    (minus a 4-name blocklist) - i.e. every interface on the box, not just
    WAN/LAN as documented. It also carried a second, dead UCI-based
    discovery function that was never called from main() and additionally
    had the same broken nested-dict euci usage seen in other checks
    (u.get("network") returns {section: {options}}, not flat dotted keys).
    """
    if not EUCI_AVAILABLE:
        return []
    try:
        from nethsec.utils import get_all_wan_devices, get_all_lan_devices
        with EUci() as u:
            ifaces = set(get_all_wan_devices(u)) | set(get_all_lan_devices(u))
        return sorted(ifaces)
    except Exception:
        return []


def get_counters(iface):
    """Return (rx_bytes, rx_packets, rx_errors, tx_bytes, tx_packets, tx_errors) or None."""
    dev_path = Path("/proc/net/dev")
    if not dev_path.exists():
        return None
    try:
        for line in dev_path.read_text().splitlines():
            # /proc/net/dev right-pads short interface names with leading
            # spaces (e.g. "  eth0:") to align columns - without stripping,
            # startswith() only matched names long enough to fill the
            # column (e.g. "br-lan:"), silently missing eth0/eth1/eth2/etc.
            stripped = line.strip()
            if stripped.startswith(iface + ":"):
                parts = stripped.split(":", 1)[1].split()
                if len(parts) >= 11:
                    return (
                        int(parts[0]), int(parts[1]), int(parts[2]),
                        int(parts[8]), int(parts[9]), int(parts[10]),
                    )
    except Exception:
        pass
    return None


def main():
    ifaces = get_wan_lan_interfaces()
    if not ifaces:
        print("1 Traffic - No WAN/LAN interfaces found")
        return 0
    for iface in ifaces:
        counters = get_counters(iface)
        if counters is None:
            continue
        rx_bytes, rx_packets, rx_errors, tx_bytes, tx_packets, tx_errors = counters
        st = 1 if (rx_errors > ERROR_WARN or tx_errors > ERROR_WARN) else 0
        label = "WARNING" if st else "OK"
        # Perfdata MUST be a single whitespace-free token (CheckMK's local check
        # parser takes the 3rd space-separated field as perfdata verbatim and
        # never re-scans the free-text field for a later "|" - putting it
        # after "- {label}" as before silently produced zero graphed metrics.
        perfdata = (
            f"rx_bytes={rx_bytes}|tx_bytes={tx_bytes}|rx_packets={rx_packets}"
            f"|tx_packets={tx_packets}|rx_errors={rx_errors}|tx_errors={tx_errors}"
        )
        print(f"{st} {iface}.{SERVICE} {perfdata} RX: {rx_bytes} bytes, TX: {tx_bytes} bytes - {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
