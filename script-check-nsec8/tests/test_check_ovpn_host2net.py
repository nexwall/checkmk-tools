#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""Tests for check_ovpn_host2net.py.

Covers: the ns_tag-based road-warrior/net2net discrimination regression
(any enabled OpenVPN instance was previously miscounted as "host2net",
including net2net tunnels), socket-based running detection (vs the old
/proc cmdline grep that missed discrete-flag-launched instances), and the
perfdata-placement regression.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import check_ovpn_host2net as h2n
from checkmk_format import graphed_metric_names, split_check_result


# --- find_running_instances() -----------------------------------------------

def test_excludes_net2net_tunnels_without_automated_tag(fake_nethsec, fake_euci, monkeypatch):
    # Regression: net2net tunnels (ns.ovpntunnel) use ns_name/ns_client and
    # never set ns_tag - an enabled net2net section was previously miscounted
    # as a host2net (road warrior) instance.
    instances = {
        "ns_roadwarrior1": {"enabled": "1", "ns_tag": "automated_ns_roadwarrior1"},
        "site_b_tunnel": {"enabled": "1", "ns_name": "site_b", "ns_client": "1"},  # net2net, no ns_tag
    }
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)
    fake_nethsec.install(utils=utils)
    fake_euci(h2n, uci_obj=MagicMock())
    monkeypatch.setattr(Path, "exists", lambda self: True)

    running = h2n.find_running_instances()

    assert running == ["ns_roadwarrior1"]


def test_excludes_disabled_instances(fake_nethsec, fake_euci, monkeypatch):
    instances = {"ns_roadwarrior1": {"enabled": "0", "ns_tag": "automated_x"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)
    fake_nethsec.install(utils=utils)
    fake_euci(h2n, uci_obj=MagicMock())
    monkeypatch.setattr(Path, "exists", lambda self: True)

    assert h2n.find_running_instances() == []


def test_requires_management_socket_to_be_present(fake_nethsec, fake_euci, monkeypatch):
    # Regression: the old detection grepped /proc for a cmdline containing
    # both "openvpn" and "--config", missing instances procd launches with
    # discrete flags instead. Socket presence is what nethsec's own
    # list_connected_clients() reads from, so it's used here directly.
    instances = {"ns_roadwarrior1": {"enabled": "1", "ns_tag": "automated_x"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)
    fake_nethsec.install(utils=utils)
    fake_euci(h2n, uci_obj=MagicMock())
    monkeypatch.setattr(Path, "exists", lambda self: False)  # socket not present -> not running

    assert h2n.find_running_instances() == []


def test_empty_without_library(monkeypatch):
    monkeypatch.setattr(h2n, "EUCI_AVAILABLE", False)

    assert h2n.find_running_instances() == []


def test_empty_when_get_all_by_type_returns_none(fake_nethsec, fake_euci):
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: None)
    fake_nethsec.install(utils=utils)
    fake_euci(h2n, uci_obj=MagicMock())

    assert h2n.find_running_instances() == []


# --- count_connected_clients() ----------------------------------------------

def test_count_connected_clients_uses_library(fake_nethsec):
    ovpn = SimpleNamespace(list_connected_clients=lambda instance, type: {"a": {}, "b": {}})
    fake_nethsec.install(ovpn=ovpn)

    assert h2n.count_connected_clients("ns_roadwarrior1") == 2


def test_count_connected_clients_zero_on_error(fake_nethsec):
    def raises(*a, **k):
        raise RuntimeError("socket gone")

    fake_nethsec.install(ovpn=SimpleNamespace(list_connected_clients=raises))

    assert h2n.count_connected_clients("ns_roadwarrior1") == 0


# --- main(): perfdata regression ---------------------------------------------

def test_main_not_configured(monkeypatch, capsys):
    monkeypatch.setattr(h2n, "find_running_instances", lambda: [])

    rc = h2n.main()

    assert rc == 0
    assert "OpenVPN not configured or not running" in capsys.readouterr().out


def test_main_reports_real_perfdata_across_multiple_instances(monkeypatch, capsys):
    monkeypatch.setattr(h2n, "find_running_instances", lambda: ["ns_roadwarrior1", "ns_roadwarrior2"])
    monkeypatch.setattr(h2n, "count_connected_clients", lambda i: {"ns_roadwarrior1": 3, "ns_roadwarrior2": 2}[i])

    h2n.main()
    line = capsys.readouterr().out.strip()

    state, service, perf, text = split_check_result(line)
    assert state == "0"
    # Regression: perfdata was previously placed after "Active: ...", so
    # field3 was just "-" and nothing was graphed.
    assert graphed_metric_names(line) == {"instances", "clients"}
    assert dict(__import__("checkmk_format").parse_perfdata(perf)) == {"instances": 2.0, "clients": 5.0}
