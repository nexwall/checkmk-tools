#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""check_wan_throughput.py - CheckMK WAN throughput check.

Uses /proc/net/route for default route, /proc/net/dev for byte counters.
State persistence via JSON file (/tmp/wan_throughput_state.json).
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

VERSION = "1.14.1"
SERVICE = "WAN.Throughput"
STATE_FILE = "/tmp/wan_throughput_state.json"
PROC_NET_DEV = "/proc/net/dev"

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


def _resolve_runtime_device(uci, section, configured_device):
    """Resolve the runtime device for a UCI interface section (see check_wan_status.py)."""
    status = _ubus_interface_status(section)
    if status:
        l3_device = status.get("l3_device")
        if l3_device:
            return l3_device
    return configured_device


def get_wan_devices():
    """Get all WAN devices using nethsec library.

    Returns a list of dicts: {"label": <logical name>, "device": <runtime device>}.
    "label" is the UCI interface section name (e.g. "tim_fibra",
    "vodafone_adsl") - the name an admin actually gave the WAN, commonly the
    ISP/operator name, not literally "wan" - since that's what should be
    shown in CheckMK, not the raw device name. Falls back to the device name
    if no matching UCI section is found.

    Primary: nethsec.inventory.get_networks() with role == "red", resolved to
    the runtime device via ubus (handles PPPoE/dynamic protocols correctly).
    Fallback: /proc/net/route for backward compatibility (single device,
    library unavailable - no per-WAN label possible there).
    """
    wans = []

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
                    runtime_dev = _resolve_runtime_device(u, section, dev) if section else dev
                    label = section or runtime_dev
                    if not any(w["device"] == runtime_dev for w in wans):
                        wans.append({"label": label, "device": runtime_dev})
                if wans:
                    return wans  # Success - don't fall through
        except (ImportError, Exception):
            pass

    # Method 2: Fallback to /proc/net/route only if library unavailable
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "00000000":
                iface = parts[0].strip()
                if iface and not any(w["device"] == iface for w in wans):
                    wans.append({"label": iface, "device": iface})
    except Exception:
        pass

    return wans  # Return whatever we found (even empty)


def get_proc_net_dev_bytes(device):
    try:
        for line in Path(PROC_NET_DEV).read_text().splitlines():
            if line.strip().startswith(device + ":"):
                parts = line.split(":", 1)[1].split()
                if len(parts) >= 9:
                    return int(parts[0]), int(parts[8])
    except Exception:
        pass
    return None


def get_device_speed(device):
    """Return link speed in Mbps, or None if it cannot be determined.

    Does NOT default to a guessed value: a wrong assumed speed silently masks
    real saturation (thresholds become unreachable) or causes false alarms on
    devices without a meaningful /sys speed file (pppoe-*, virtual devices).
    """
    try:
        speed = int(Path(f"/sys/class/net/{device}/speed").read_text().strip())
        if speed > 0:
            return speed
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["ethtool", device], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            m = re.search(r"Speed:\s*(\d+)Mb/s", result.stdout)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return None


def load_state():
    """Returns {device: {rx_bytes, tx_bytes, timestamp}}, keyed per WAN device
    so multiple WANs each keep their own counter baseline."""
    try:
        if Path(STATE_FILE).exists():
            with open(STATE_FILE) as f:
                data = json.load(f)
            # Back-compat: a previous single-WAN state file had a flat
            # {"iface": ..., "rx_bytes": ..., ...} shape instead of being
            # keyed by device - treat it as empty rather than misreading it.
            if "iface" in data:
                return {}
            return data
    except Exception:
        pass
    return {}


def save_device_state(all_state, device, rx, tx, ts):
    all_state[device] = {"rx_bytes": rx, "tx_bytes": tx, "timestamp": ts}
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(all_state, f)
    except Exception:
        pass


def fmt_bps(bps):
    if bps < 1024:
        return f"{bps:.1f} B/s"
    elif bps < 1024 ** 2:
        return f"{bps / 1024:.1f} KiB/s"
    elif bps < 1024 ** 3:
        return f"{bps / 1024 ** 2:.2f} MiB/s"
    else:
        return f"{bps / 1024 ** 3:.2f} GiB/s"


def main():
    now = time.time()
    wans = get_wan_devices()
    if not wans:
        print(f'2 {SERVICE} if_in_octets=0|if_out_octets=0 No WAN device found')
        return 0

    all_state = load_state()
    for w in wans:
        label, device = w["label"], w["device"]
        service = f"{SERVICE}.{label}"
        result = get_proc_net_dev_bytes(device)
        if result is None:
            print(f'2 {service} if_in_octets=0|if_out_octets=0 Cannot read counters for {device}')
            continue
        rx_now, tx_now = result
        state = all_state.get(device)
        if state is None:
            save_device_state(all_state, device, rx_now, tx_now, now)
            print(f'1 {service} if_in_octets=0|if_out_octets=0 [{device}] Initializing')
            continue
        delta_sec = now - state["timestamp"]
        if delta_sec < 1:
            save_device_state(all_state, device, rx_now, tx_now, now)
            print(f'0 {service} if_in_octets=0|if_out_octets=0 [{device}] Interval too short ({delta_sec:.1f}s)')
            continue
        if rx_now < state["rx_bytes"] or tx_now < state["tx_bytes"]:
            # Counter reset (driver reload/hotplug): the new counter value is
            # NOT a valid delta for this interval - computing
            # "delta = new - 0" would fabricate a bogus multi-gigabyte spike.
            # Re-baseline instead.
            save_device_state(all_state, device, rx_now, tx_now, now)
            print(f'0 {service} if_in_octets=0|if_out_octets=0 [{device}] Counters reset, re-baselining')
            continue
        d_rx = rx_now - state["rx_bytes"]
        d_tx = tx_now - state["tx_bytes"]
        rx_bps = d_rx / delta_sec
        tx_bps = d_tx / delta_sec
        save_device_state(all_state, device, rx_now, tx_now, now)
        speed_mbps = get_device_speed(device)
        if speed_mbps is None:
            # Unknown link speed: report raw throughput without a %-of-speed
            # threshold rather than assuming a default that could either
            # mask real saturation or make thresholds unreachable.
            print(
                f'0 {service} if_in_octets={rx_bps:.2f}|if_out_octets={tx_bps:.2f} '
                f'[{device}] Speed: unknown, In: {fmt_bps(rx_bps)}, Out: {fmt_bps(tx_bps)}'
            )
            continue
        speed_bps = speed_mbps * 125_000
        speed_str = f"{speed_mbps // 1000} GBit/s" if speed_mbps >= 1000 else f"{speed_mbps} MBit/s"
        rx_pct = (rx_bps / speed_bps * 100) if speed_bps > 0 else 0.0
        tx_pct = (tx_bps / speed_bps * 100) if speed_bps > 0 else 0.0
        warn_bps = speed_bps * 0.80
        crit_bps = speed_bps * 0.95
        st = 2 if (rx_bps >= crit_bps or tx_bps >= crit_bps) else (1 if (rx_bps >= warn_bps or tx_bps >= warn_bps) else 0)
        print(
            f'{st} {service} if_in_octets={rx_bps:.2f}|if_out_octets={tx_bps:.2f} '
            f'[{device}] Speed: {speed_str}, In: {fmt_bps(rx_bps)} ({rx_pct:.2f}%), '
            f'Out: {fmt_bps(tx_bps)} ({tx_pct:.2f}%)'
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
