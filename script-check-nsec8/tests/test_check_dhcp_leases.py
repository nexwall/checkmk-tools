#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""Tests for check_dhcp_leases.py.

Covers: the off-by-one pool-capacity regression (limit-1 vs limit), the
unguarded-None crash regression when get_all_by_type() errors internally,
pool filtering (ignore/disabled), lease parsing/counting, and the
perfdata-placement regression.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import check_dhcp_leases as dl
from checkmk_format import graphed_metric_names, parse_perfdata, split_check_result


# --- get_dhcp_pools() --------------------------------------------------------

def test_get_dhcp_pools_capacity_is_limit_not_limit_minus_one(fake_nethsec, fake_euci):
    # Regression: OpenWrt's dnsmasq init script computes end = start+limit-1
    # (inclusive range), so [start, start+limit-1] holds exactly `limit`
    # addresses - confirmed live with the device's own ipcalc.sh
    # (start=100 limit=150 -> 249-100+1 == 150). The old code stored
    # "limit": raw_limit - 1, undercounting every pool's capacity by 1.
    sections = {"lan": {"interface": "lan", "start": "100", "limit": "150"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: sections)
    fake_nethsec.install(utils=utils)
    fake_euci(dl, uci_obj=MagicMock())

    pools = dl.get_dhcp_pools()

    assert pools == [{"name": "lan", "interface": "lan", "start": 100, "limit": 150}]


def test_get_dhcp_pools_handles_none_from_get_all_by_type(fake_nethsec, fake_euci):
    # Regression: get_all_by_type() returns None (not {}) when uci.get()
    # itself errors internally - confirmed live against a bogus config name.
    # The old code went straight to sections.items() with no guard, crashing
    # with an uncaught AttributeError outside the try/except.
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: None)
    fake_nethsec.install(utils=utils)
    fake_euci(dl, uci_obj=MagicMock())

    assert dl.get_dhcp_pools() == []


def test_get_dhcp_pools_skips_ignored_and_disabled(fake_nethsec, fake_euci):
    sections = {
        "wan": {"interface": "wan", "start": "2", "limit": "100", "ignore": "1"},
        "guest": {"interface": "guest", "start": "2", "limit": "50", "dhcpv4": "disabled"},
        "lan": {"interface": "lan", "start": "100", "limit": "150"},
    }
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: sections)
    fake_nethsec.install(utils=utils)
    fake_euci(dl, uci_obj=MagicMock())

    pools = dl.get_dhcp_pools()

    assert [p["name"] for p in pools] == ["lan"]


def test_get_dhcp_pools_skips_zero_limit(fake_nethsec, fake_euci):
    sections = {"lan": {"interface": "lan", "start": "100", "limit": "0"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: sections)
    fake_nethsec.install(utils=utils)
    fake_euci(dl, uci_obj=MagicMock())

    assert dl.get_dhcp_pools() == []


def test_get_dhcp_pools_empty_without_library(monkeypatch):
    monkeypatch.setattr(dl, "EUCI_AVAILABLE", False)

    assert dl.get_dhcp_pools() == []


# --- count_active_leases() ---------------------------------------------------

def test_count_active_leases_counts_unexpired_and_never(monkeypatch):
    monkeypatch.setattr(dl.time, "time", lambda: 1000)
    leases = [
        {"expiry": "2000"},   # active - in the future
        {"expiry": "500"},    # expired - in the past
        {"expiry": "0"},      # active - permanent (0 == never expires)
        {"expiry": "never"},  # active - explicit non-numeric marker
    ]

    assert dl.count_active_leases(leases) == 3


# --- read_leases() ------------------------------------------------------------

def test_read_leases_parses_standard_dnsmasq_format(monkeypatch, tmp_path):
    lease_file = tmp_path / "dhcp.leases"
    lease_file.write_text("1234567890 aa:bb:cc:dd:ee:ff 192.168.1.50 myhost *\n")
    monkeypatch.setattr(dl, "resolve_lease_file", lambda: (lease_file, str(lease_file)))

    leases, src = dl.read_leases()

    assert leases == [{
        "expiry": "1234567890", "mac": "aa:bb:cc:dd:ee:ff", "ip": "192.168.1.50", "hostname": "myhost",
    }]


def test_read_leases_no_file_found(monkeypatch):
    monkeypatch.setattr(dl, "resolve_lease_file", lambda: (None, "no lease file found"))

    leases, src = dl.read_leases()

    assert leases == []
    assert src == "no lease file found"


# --- main(): perfdata regression + thresholds -------------------------------

def test_main_no_pools_found(monkeypatch, capsys):
    monkeypatch.setattr(dl, "get_dhcp_pools", lambda: [])

    rc = dl.main()

    assert rc == 0
    assert "No active DHCP pool found" in capsys.readouterr().out


def test_main_ok_reports_real_perfdata(monkeypatch, capsys):
    monkeypatch.setattr(dl, "EUCI_AVAILABLE", True)
    monkeypatch.setattr(dl, "get_dhcp_pools", lambda: [{"name": "lan", "interface": "lan", "start": 100, "limit": 150}])
    monkeypatch.setattr(dl, "read_leases", lambda: ([{"expiry": "0"}] * 10, "/tmp/dhcp.leases"))
    monkeypatch.setattr(dl, "count_active_leases", lambda leases: 10)

    dl.main()
    line = capsys.readouterr().out.strip()

    state, service, perf, text = split_check_result(line)
    assert state == "0"
    # Regression: perfdata was previously split across a space-separated
    # "active=..." token plus a trailing "| expired=... max=... percent=...
    # pools=..." block after the free text - only "active" was ever
    # actually graphed. "max" is intentionally dropped now (duplicated
    # active's own ;0;{capacity} boundary under a different name).
    assert graphed_metric_names(line) == {"active", "expired", "total", "percent", "pools"}
    values = dict(parse_perfdata(perf))
    assert values["active"] == 10.0
    assert values["total"] == 10.0
    assert values["expired"] == 0.0
    assert values["pools"] == 1.0


def test_main_warning_at_80_percent(monkeypatch, capsys):
    monkeypatch.setattr(dl, "EUCI_AVAILABLE", True)
    monkeypatch.setattr(dl, "get_dhcp_pools", lambda: [{"name": "lan", "interface": "lan", "start": 100, "limit": 100}])
    monkeypatch.setattr(dl, "read_leases", lambda: ([{"expiry": "0"}] * 85, "/tmp/dhcp.leases"))
    monkeypatch.setattr(dl, "count_active_leases", lambda leases: 85)

    dl.main()
    line = capsys.readouterr().out.strip()

    assert split_check_result(line)[0] == "1"


def test_main_critical_at_90_percent(monkeypatch, capsys):
    monkeypatch.setattr(dl, "EUCI_AVAILABLE", True)
    monkeypatch.setattr(dl, "get_dhcp_pools", lambda: [{"name": "lan", "interface": "lan", "start": 100, "limit": 100}])
    monkeypatch.setattr(dl, "read_leases", lambda: ([{"expiry": "0"}] * 95, "/tmp/dhcp.leases"))
    monkeypatch.setattr(dl, "count_active_leases", lambda leases: 95)

    dl.main()
    line = capsys.readouterr().out.strip()

    assert split_check_result(line)[0] == "2"
