#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""Tests for check_wan_status.py.

Covers: library-first WAN discovery with /proc/net/route fallback, ubus-based
up/down + gateway detection with /sys+/proc fallback, per-device internet
reachability via `ping -I`, and the two-service-per-WAN output (each an
explicit regression test for bugs found live on the test device: the
duplicate-service-name bug, the compound-vs-single-purpose naming mixup, and
the perfdata-field-placement bug that silently zeroed out WAN.Metrics).
"""

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import check_wan_status
from checkmk_format import graphed_metric_names, split_check_result


# --- find_wan_interfaces() -------------------------------------------------

def test_find_wan_interfaces_uses_library_first(fake_nethsec, fake_euci):
    fake_euci(check_wan_status, uci_obj=MagicMock())
    networks = {
        "eth1": {"props": {"role": "red"}},
        "eth0": {"props": {"role": "green"}},
    }
    inventory = SimpleNamespace(get_networks=lambda u: networks)
    utils = SimpleNamespace(
        get_all_by_type=lambda u, config, kind: {"tim_fibra": {}},
        get_interface=None,
    )
    fake_nethsec.install(inventory=inventory, utils=utils)

    def fake_uci_get(config, section, option, default=None):
        if section == "tim_fibra" and option == "device":
            return "eth1"
        return default

    uci_obj = MagicMock()
    uci_obj.get.side_effect = fake_uci_get
    fake_euci(check_wan_status, uci_obj=uci_obj)

    wans = check_wan_status.find_wan_interfaces()

    assert wans == [{"label": "tim_fibra", "device": "eth1"}]
    # the green-role interface must never appear
    assert not any(w["device"] == "eth0" for w in wans)


def test_find_wan_interfaces_falls_back_to_proc_net_route(monkeypatch, tmp_path):
    monkeypatch.setattr(check_wan_status, "EUCI_AVAILABLE", False)
    route_file = tmp_path / "route"
    # header + one default-route (00000000) entry for eth1
    route_file.write_text(
        "Iface\tDestination\tGateway\tFlags\n"
        "eth1\t00000000\tFA0AA8C0\t0003\n"
    )
    monkeypatch.setattr(check_wan_status, "Path", lambda p: route_file if p == "/proc/net/route" else __import__("pathlib").Path(p))

    wans = check_wan_status.find_wan_interfaces()

    assert wans == [{"label": "eth1", "device": "eth1"}]


# --- check_wan_state() ------------------------------------------------------

def _mock_ubus_status(monkeypatch, payload):
    result = MagicMock(returncode=0, stdout=json.dumps(payload))
    monkeypatch.setattr(subprocess, "run", MagicMock(return_value=result))


def test_check_wan_state_reads_up_and_gateway_from_ubus(monkeypatch):
    _mock_ubus_status(monkeypatch, {
        "up": True,
        "l3_device": "eth1",
        "route": [{"target": "0.0.0.0", "nexthop": "192.168.10.250"}],
    })

    device, up, gateway = check_wan_status.check_wan_state("tim_fibra", "eth1")

    assert (device, up, gateway) == ("eth1", True, "192.168.10.250")


def test_check_wan_state_down_from_ubus(monkeypatch):
    _mock_ubus_status(monkeypatch, {"up": False, "l3_device": "eth1", "route": []})

    _, up, gateway = check_wan_status.check_wan_state("tim_fibra", "eth1")

    assert up is False
    assert gateway is None


def test_check_wan_state_falls_back_when_ubus_unavailable(monkeypatch):
    # ubus call itself fails (e.g. binary missing) -> _ubus_interface_status returns None
    monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=FileNotFoundError))
    # Real /proc/net/route has 11 whitespace-separated columns; get_gateway_fallback()
    # requires len(parts) >= 8, so the fake line must have that many fields too.
    route_line = "eth1\t00000000\tFA0AA8C0\t0003\t0\t0\t0\t00000000\t0\t0\t0"
    monkeypatch.setattr(
        check_wan_status, "Path",
        lambda p: SimpleNamespace(exists=lambda: True, read_text=lambda: "up\n") if "operstate" in str(p)
        else SimpleNamespace(read_text=lambda: f"Iface\tDestination\tGateway\n{route_line}\n"),
    )

    device, up, gateway = check_wan_status.check_wan_state("tim_fibra", "eth1")

    assert device == "eth1"
    assert up is True
    assert gateway == "192.168.10.250"


# --- has_internet() ---------------------------------------------------------

def test_has_internet_true_when_majority_of_hosts_respond(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        # first 2 hosts succeed -> majority (2 of 4) reached, should stop early
        idx = len(calls)
        return MagicMock(returncode=0 if idx <= 2 else 1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert check_wan_status.has_internet("eth1") is True
    # early-exit: must not have pinged all 4 configured hosts
    assert len(calls) == 2
    assert calls[0][calls[0].index("-I") + 1] == "eth1"


def test_has_internet_false_when_no_host_responds(monkeypatch):
    monkeypatch.setattr(subprocess, "run", MagicMock(return_value=MagicMock(returncode=1)))

    assert check_wan_status.has_internet("eth1") is False


def test_has_internet_tolerates_exceptions_per_host(monkeypatch):
    # one host raises (e.g. timeout), the rest still get tried
    responses = [subprocess.TimeoutExpired(cmd="ping", timeout=2), MagicMock(returncode=0), MagicMock(returncode=0)]

    def fake_run(cmd, **kwargs):
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert check_wan_status.has_internet("eth1") is True


# --- main(): the two-service-per-WAN output, per state ----------------------

def _patch_pipeline(monkeypatch, wans, states):
    """states: dict label -> (device, up, gateway, has_internet_result)"""
    monkeypatch.setattr(check_wan_status, "find_wan_interfaces", lambda: wans)

    def fake_check_wan_state(label, configured_device):
        device, up, gateway, _ = states[label]
        return device, up, gateway

    def fake_has_internet(device):
        for device_, up, gateway, internet in states.values():
            if device_ == device:
                return internet
        return False

    monkeypatch.setattr(check_wan_status, "check_wan_state", fake_check_wan_state)
    monkeypatch.setattr(check_wan_status, "has_internet", fake_has_internet)


def test_main_all_ok(monkeypatch, capsys):
    wans = [{"label": "tim_fibra", "device": "eth1"}]
    _patch_pipeline(monkeypatch, wans, {"tim_fibra": ("eth1", True, "192.168.10.250", True)})

    check_wan_status.main()
    lines = capsys.readouterr().out.strip().splitlines()

    # Regression: WAN.Interface is the single up/down fact, WAN.Status is the
    # compound verdict - they must be two DISTINCT service names per WAN
    # (an earlier draft printed both as literally "WAN.Status", which
    # CheckMK would treat as duplicate/colliding services).
    services = [split_check_result(line)[1] for line in lines]
    assert services == ["WAN.Interface.tim_fibra", "WAN.Status.tim_fibra", "WAN.Metrics"]

    iface_state = split_check_result(lines[0])[0]
    status_state = split_check_result(lines[1])[0]
    assert (iface_state, status_state) == ("0", "0")

    # Regression: WAN.Metrics perfdata must be real (was previously placed
    # after the free text - field3 was just "-", so nothing was graphed).
    assert graphed_metric_names(lines[2]) == {"total", "up", "down", "degraded"}


def test_main_degraded_interface_up_no_internet(monkeypatch, capsys):
    wans = [{"label": "tim_fibra", "device": "eth1"}]
    _patch_pipeline(monkeypatch, wans, {"tim_fibra": ("eth1", True, "192.168.10.250", False)})

    check_wan_status.main()
    lines = capsys.readouterr().out.strip().splitlines()

    iface_line, status_line, metrics_line = lines
    assert split_check_result(iface_line)[0] == "0"  # interface itself is fine
    state, service, _, text = split_check_result(status_line)
    assert state == "1"  # WARNING, not CRITICAL - the interface isn't the problem
    assert "no internet reachability" in text
    assert "upstream/ISP" in text
    assert "192.168.10.250" in text

    metrics_state, _, perf, _ = split_check_result(metrics_line)
    assert dict(__import__("checkmk_format").parse_perfdata(perf))["degraded"] == 1.0


def test_main_interface_down_skips_internet_probe(monkeypatch, capsys):
    wans = [{"label": "tim_fibra", "device": "eth1"}]
    monkeypatch.setattr(check_wan_status, "find_wan_interfaces", lambda: wans)
    monkeypatch.setattr(check_wan_status, "check_wan_state", lambda label, dev: ("eth1", False, None))
    has_internet_mock = MagicMock()
    monkeypatch.setattr(check_wan_status, "has_internet", has_internet_mock)

    check_wan_status.main()
    lines = capsys.readouterr().out.strip().splitlines()

    iface_line, status_line, _ = lines
    assert split_check_result(iface_line)[0] == "2"
    assert split_check_result(status_line)[0] == "2"
    assert "DOWN" in status_line
    # Testing internet reachability on a down interface is meaningless -
    # must not even attempt it.
    has_internet_mock.assert_not_called()


def test_main_no_wan_interfaces_found(monkeypatch, capsys):
    monkeypatch.setattr(check_wan_status, "find_wan_interfaces", lambda: [])

    rc = check_wan_status.main()

    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("0 WAN.Status -")


def test_main_metrics_up_plus_down_always_equals_total(monkeypatch, capsys):
    # Regression: the previous WAN.Metrics computed up/down only from
    # state==0/state==2, silently excluding degraded (state==1) WANs from
    # both buckets - up_count + down_count could be less than total.
    wans = [{"label": "a", "device": "eth1"}, {"label": "b", "device": "eth2"}]
    _patch_pipeline(monkeypatch, wans, {
        "a": ("eth1", True, "10.0.0.1", False),  # degraded
        "b": ("eth2", False, None, False),       # down
    })

    check_wan_status.main()
    lines = capsys.readouterr().out.strip().splitlines()
    metrics = dict(__import__("checkmk_format").parse_perfdata(split_check_result(lines[-1])[2]))

    assert metrics["total"] == metrics["up"] + metrics["down"]
    assert metrics["degraded"] == 1.0
