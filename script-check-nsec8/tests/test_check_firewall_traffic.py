#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""Tests for check_firewall_traffic.py.

Covers: the /proc/net/dev padding regression (short interface names were
silently missed without .strip()), library-based WAN/LAN device discovery,
error thresholding, and the perfdata-placement regression (was after free
text, producing zero graphed metrics for every interface).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import check_firewall_traffic as ft
from checkmk_format import graphed_metric_names, parse_perfdata, split_check_result

DEV_TEXT = (
    "Inter-|   Receive\n"
    " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
    "    lo:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0\n"
    "  eth0: 1000000    1000    2    0    0     0          0         0   500000     500    3    0    0     0       0          0\n"
    "br-lan: 2000000    2000    0    0    0     0          0         0  1000000    1000    0    0    0     0       0          0\n"
)


# --- get_wan_lan_interfaces() -----------------------------------------------

def test_get_wan_lan_interfaces_uses_library(fake_nethsec, fake_euci):
    utils = SimpleNamespace(
        get_all_wan_devices=lambda u: ["eth1"],
        get_all_lan_devices=lambda u: ["br-lan"],
    )
    fake_nethsec.install(utils=utils)
    fake_euci(ft, uci_obj=MagicMock())

    ifaces = ft.get_wan_lan_interfaces()

    assert ifaces == ["br-lan", "eth1"]


def test_get_wan_lan_interfaces_empty_without_library(monkeypatch):
    monkeypatch.setattr(ft, "EUCI_AVAILABLE", False)

    assert ft.get_wan_lan_interfaces() == []


# --- get_counters(): the padding regression ---------------------------------

def test_get_counters_handles_short_padded_name(monkeypatch):
    # Regression: /proc/net/dev right-pads short names ("  eth0:") to align
    # columns. A bare `line.startswith(iface + ":")` (no .strip()) only ever
    # matched names long enough to fill the column (e.g. "br-lan:"),
    # silently missing eth0/eth1/eth2/etc - previously this check reported
    # nothing at all for any single/double-letter-digit device.
    monkeypatch.setattr(ft, "Path", lambda p: SimpleNamespace(exists=lambda: True, read_text=lambda: DEV_TEXT))

    result = ft.get_counters("eth0")

    assert result == (1000000, 1000, 2, 500000, 500, 3)


def test_get_counters_still_works_for_long_names(monkeypatch):
    monkeypatch.setattr(ft, "Path", lambda p: SimpleNamespace(exists=lambda: True, read_text=lambda: DEV_TEXT))

    result = ft.get_counters("br-lan")

    assert result == (2000000, 2000, 0, 1000000, 1000, 0)


def test_get_counters_missing_device_returns_none(monkeypatch):
    monkeypatch.setattr(ft, "Path", lambda p: SimpleNamespace(exists=lambda: True, read_text=lambda: DEV_TEXT))

    assert ft.get_counters("eth9") is None


def test_get_counters_missing_proc_file_returns_none(monkeypatch):
    monkeypatch.setattr(ft, "Path", lambda p: SimpleNamespace(exists=lambda: False))

    assert ft.get_counters("eth0") is None


# --- main(): thresholding + perfdata -----------------------------------------

def test_main_ok_below_error_threshold(monkeypatch, capsys):
    monkeypatch.setattr(ft, "get_wan_lan_interfaces", lambda: ["eth0"])
    monkeypatch.setattr(ft, "get_counters", lambda iface: (1000, 10, 0, 500, 5, 0))

    ft.main()
    line = capsys.readouterr().out.strip()

    state, service, perf, text = split_check_result(line)
    assert state == "0"
    assert service == "eth0.Traffic"
    # Regression: perfdata was previously placed after "- {label}", so field3
    # was just "-" and CheckMK graphed nothing for any interface.
    assert graphed_metric_names(line) == {
        "rx_bytes", "tx_bytes", "rx_packets", "tx_packets", "rx_errors", "tx_errors",
    }
    assert dict(parse_perfdata(perf))["rx_bytes"] == 1000.0


def test_main_warning_above_error_threshold(monkeypatch, capsys):
    monkeypatch.setattr(ft, "get_wan_lan_interfaces", lambda: ["eth0"])
    monkeypatch.setattr(ft, "get_counters", lambda iface: (1000, 10, ft.ERROR_WARN + 1, 500, 5, 0))

    ft.main()
    line = capsys.readouterr().out.strip()

    assert split_check_result(line)[0] == "1"
    assert "WARNING" in line


def test_main_multiple_interfaces_each_reported(monkeypatch, capsys):
    monkeypatch.setattr(ft, "get_wan_lan_interfaces", lambda: ["eth0", "eth1", "br-lan"])
    monkeypatch.setattr(ft, "get_counters", lambda iface: (1, 1, 0, 1, 1, 0))

    ft.main()
    lines = capsys.readouterr().out.strip().splitlines()

    services = [split_check_result(line)[1] for line in lines]
    assert services == ["eth0.Traffic", "eth1.Traffic", "br-lan.Traffic"]


def test_main_no_interfaces_found(monkeypatch, capsys):
    monkeypatch.setattr(ft, "get_wan_lan_interfaces", lambda: [])

    rc = ft.main()

    assert rc == 0
    assert "No WAN/LAN interfaces found" in capsys.readouterr().out


def test_main_skips_interface_with_unreadable_counters(monkeypatch, capsys):
    monkeypatch.setattr(ft, "get_wan_lan_interfaces", lambda: ["eth0", "eth1"])
    monkeypatch.setattr(ft, "get_counters", lambda iface: None if iface == "eth0" else (1, 1, 0, 1, 1, 0))

    ft.main()
    lines = capsys.readouterr().out.strip().splitlines()

    assert len(lines) == 1
    assert split_check_result(lines[0])[1] == "eth1.Traffic"
