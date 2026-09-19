#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""Tests for check_wan_throughput.py.

Covers: library-first multi-WAN discovery, /proc/net/dev counter parsing,
device speed detection (sys -> ethtool -> unknown), counter-reset
re-baselining, and the service-naming regression (WAN.Throughput.<label>,
not <label>.WAN.Throughput - explicitly requested naming order).
"""

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import check_wan_throughput as wt
from checkmk_format import graphed_metric_names, split_check_result


# --- get_wan_devices() ------------------------------------------------------

def test_get_wan_devices_library_first_multi_wan(fake_nethsec, fake_euci):
    networks = {
        "eth1": {"props": {"role": "red"}},
        "eth2": {"props": {"role": "red"}},
        "eth0": {"props": {"role": "green"}},
    }
    inventory = SimpleNamespace(get_networks=lambda u: networks)

    def fake_all_by_type(u, config, kind):
        return {"tim_fibra": {}, "vodafone_adsl": {}}

    utils = SimpleNamespace(get_all_by_type=fake_all_by_type)
    fake_nethsec.install(inventory=inventory, utils=utils)

    def fake_get(config, section, option, default=None):
        return {"tim_fibra": "eth1", "vodafone_adsl": "eth2"}.get(section, default)

    uci_obj = MagicMock()
    uci_obj.get.side_effect = fake_get
    fake_euci(wt, uci_obj=uci_obj)

    with patch.object(subprocess, "run", MagicMock(side_effect=FileNotFoundError)):
        wans = wt.get_wan_devices()

    # Regression: an earlier version had a `break` after the first match,
    # silently limiting a multi-WAN box to only its first WAN.
    assert len(wans) == 2
    assert {w["label"] for w in wans} == {"tim_fibra", "vodafone_adsl"}


def test_get_wan_devices_falls_back_to_proc_net_route(monkeypatch):
    monkeypatch.setattr(wt, "EUCI_AVAILABLE", False)
    route_text = "Iface\tDest\tGW\n" + "eth1\t00000000\tFA0AA8C0\t0003\t0\t0\t0\t0\t0\t0\t0\n"
    monkeypatch.setattr(wt, "Path", lambda p: SimpleNamespace(read_text=lambda: route_text))

    wans = wt.get_wan_devices()

    assert wans == [{"label": "eth1", "device": "eth1"}]


# --- get_proc_net_dev_bytes() ------------------------------------------------

def test_get_proc_net_dev_bytes_handles_short_padded_names(monkeypatch):
    # Regression: /proc/net/dev right-pads short interface names with
    # leading spaces to align columns (e.g. "  eth0:") - a naive
    # `line.startswith(device + ":")` without stripping silently misses
    # eth0/eth1/etc while still matching longer names like "br-lan:".
    dev_text = (
        "Inter-|   Receive\n"
        " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
        "    lo:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0\n"
        "  eth1: 1234567     100    0    0    0     0          0         0   654321      50    0    0    0     0       0          0\n"
    )
    monkeypatch.setattr(wt, "Path", lambda p: SimpleNamespace(read_text=lambda: dev_text))

    result = wt.get_proc_net_dev_bytes("eth1")

    assert result == (1234567, 654321)


def test_get_proc_net_dev_bytes_missing_device_returns_none(monkeypatch):
    monkeypatch.setattr(wt, "Path", lambda p: SimpleNamespace(read_text=lambda: "    lo: 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n"))

    assert wt.get_proc_net_dev_bytes("eth9") is None


# --- get_device_speed() ------------------------------------------------------

def test_get_device_speed_from_sys(monkeypatch):
    monkeypatch.setattr(wt, "Path", lambda p: SimpleNamespace(read_text=lambda: "1000\n"))

    assert wt.get_device_speed("eth1") == 1000


def test_get_device_speed_falls_back_to_ethtool(monkeypatch):
    def fake_path(p):
        raise OSError("no such file")

    monkeypatch.setattr(wt, "Path", fake_path)
    monkeypatch.setattr(
        subprocess, "run",
        MagicMock(return_value=MagicMock(returncode=0, stdout="Speed: 100Mb/s\n")),
    )

    assert wt.get_device_speed("pppoe-wan") == 100


def test_get_device_speed_unknown_when_both_fail(monkeypatch):
    def fake_path(p):
        raise OSError("no such file")

    monkeypatch.setattr(wt, "Path", fake_path)
    monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=FileNotFoundError))

    # Must NOT default to a guessed value (e.g. 1000) - unknown stays unknown.
    assert wt.get_device_speed("tun0") is None


# --- load_state() back-compat -----------------------------------------------

def test_load_state_rejects_old_flat_single_wan_format(monkeypatch):
    old_format = json.dumps({"iface": "eth1", "rx_bytes": 1, "tx_bytes": 2})
    monkeypatch.setattr(wt.Path, "exists", lambda self: True)
    with patch("builtins.open", mock_open(read_data=old_format)):
        assert wt.load_state() == {}


def test_load_state_reads_new_per_device_format(monkeypatch):
    new_format = json.dumps({"eth1": {"rx_bytes": 1, "tx_bytes": 2, "timestamp": 100}})
    monkeypatch.setattr(wt.Path, "exists", lambda self: True)
    with patch("builtins.open", mock_open(read_data=new_format)):
        assert wt.load_state() == {"eth1": {"rx_bytes": 1, "tx_bytes": 2, "timestamp": 100}}


# --- main(): service naming + perfdata + counter-reset ----------------------

def test_main_service_name_order_is_service_dot_label(monkeypatch, capsys):
    # Regression: explicitly requested naming order is
    # "WAN.Throughput.<label>", not "<label>.WAN.Throughput".
    monkeypatch.setattr(wt, "get_wan_devices", lambda: [{"label": "tim_fibra", "device": "eth1"}])
    monkeypatch.setattr(wt, "load_state", lambda: {"eth1": {"rx_bytes": 1000, "tx_bytes": 500, "timestamp": 0}})
    monkeypatch.setattr(wt, "save_device_state", lambda *a, **k: None)
    monkeypatch.setattr(wt, "get_proc_net_dev_bytes", lambda device: (2000, 1500))
    monkeypatch.setattr(wt, "get_device_speed", lambda device: 1000)
    monkeypatch.setattr(wt.time, "time", lambda: 10.0)

    wt.main()
    line = capsys.readouterr().out.strip()

    state, service, perf, text = split_check_result(line)
    assert service == "WAN.Throughput.tim_fibra"
    assert graphed_metric_names(line) == {"if_in_octets", "if_out_octets"}


def test_main_counter_reset_rebaselines_instead_of_spiking(monkeypatch, capsys):
    # Regression: a naive "delta = new - old" on a counter reset (old > new,
    # e.g. after a driver reload) would fabricate a bogus multi-GB spike.
    monkeypatch.setattr(wt, "get_wan_devices", lambda: [{"label": "tim_fibra", "device": "eth1"}])
    monkeypatch.setattr(wt, "load_state", lambda: {"eth1": {"rx_bytes": 10_000_000, "tx_bytes": 5_000_000, "timestamp": 0}})
    saved = {}
    monkeypatch.setattr(wt, "save_device_state", lambda all_state, device, rx, tx, ts: saved.update(rx=rx, tx=tx))
    monkeypatch.setattr(wt, "get_proc_net_dev_bytes", lambda device: (100, 50))  # counters reset to near-zero
    monkeypatch.setattr(wt.time, "time", lambda: 10.0)

    wt.main()
    line = capsys.readouterr().out.strip()

    assert "re-baselining" in line
    assert graphed_metric_names(line) == {"if_in_octets", "if_out_octets"}
    perf = dict(__import__("checkmk_format").parse_perfdata(split_check_result(line)[2]))
    assert perf == {"if_in_octets": 0.0, "if_out_octets": 0.0}
    assert saved == {"rx": 100, "tx": 50}


def test_main_unknown_speed_has_no_percent_threshold(monkeypatch, capsys):
    monkeypatch.setattr(wt, "get_wan_devices", lambda: [{"label": "tim_fibra", "device": "pppoe-wan"}])
    monkeypatch.setattr(wt, "load_state", lambda: {"pppoe-wan": {"rx_bytes": 0, "tx_bytes": 0, "timestamp": 0}})
    monkeypatch.setattr(wt, "save_device_state", lambda *a, **k: None)
    monkeypatch.setattr(wt, "get_proc_net_dev_bytes", lambda device: (1000, 500))
    monkeypatch.setattr(wt, "get_device_speed", lambda device: None)
    monkeypatch.setattr(wt.time, "time", lambda: 10.0)

    wt.main()
    line = capsys.readouterr().out.strip()

    assert split_check_result(line)[0] == "0"
    assert "unknown" in line
