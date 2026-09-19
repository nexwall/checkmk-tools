#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""Tests for check_vpn_tunnels.py.

Covers: the OpenVPN p2p-vs-subnet type-mismatch regression (client/outbound
instances were always queried with type="subnet", permanently reporting 0
active clients for real, healthy p2p tunnels), the road-warrior-exclusion
fix, and the per-tunnel IPsec (strongSwan) check added alongside it - none
yet promoted to full/ (see check_vpn_tunnels_wip.py in this same directory;
this test file intentionally imports that staged copy instead of the
production script in full/, whose hash must stay unchanged until the fix is
promoted). WireGuard support has been removed entirely - out of scope for
what this check needs to monitor.
"""

import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

_WIP_PATH = Path(__file__).resolve().parent / "check_vpn_tunnels_wip.py"
_loader = importlib.machinery.SourceFileLoader("check_vpn_tunnels_wip", str(_WIP_PATH))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
vt = importlib.util.module_from_spec(_spec)
_loader.exec_module(vt)

from checkmk_format import split_check_result


# --- count_openvpn_tunnels() -------------------------------------------------

def test_openvpn_p2p_client_instance_queried_as_p2p_not_subnet(fake_nethsec, fake_euci):
    # Regression: an outbound/client instance was always queried with
    # type="subnet" regardless of role - live-verified that a healthy,
    # ping-verified p2p tunnel returns {} for type="subnet" (CLIENT_LIST
    # rows only exist for routed/subnet servers), permanently reporting 0
    # active clients (false CRITICAL) for a fully working tunnel.
    instances = {"site_b": {"enabled": "1", "client": "1"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)
    seen_types = []

    def fake_list_connected_clients(section, type):
        seen_types.append(type)
        return {"stats": {"bytes_received": 1000, "bytes_sent": 500}}

    ovpn = SimpleNamespace(list_connected_clients=fake_list_connected_clients)
    fake_nethsec.install(utils=utils, ovpn=ovpn)
    fake_euci(vt, uci_obj=MagicMock())

    total, active = vt.count_openvpn_tunnels()

    assert seen_types == ["p2p"]
    assert (total, active) == (1, 1)


def test_openvpn_p2p_requires_traffic_in_both_directions(fake_nethsec, fake_euci):
    instances = {"site_b": {"enabled": "1", "client": "1"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)
    # Only one direction has traffic - must NOT count as active.
    ovpn = SimpleNamespace(list_connected_clients=lambda section, type: {"stats": {"bytes_received": 1000, "bytes_sent": 0}})
    fake_nethsec.install(utils=utils, ovpn=ovpn)
    fake_euci(vt, uci_obj=MagicMock())

    total, active = vt.count_openvpn_tunnels()

    assert (total, active) == (1, 0)


def test_openvpn_road_warrior_excluded_from_tunnel_count(fake_nethsec, fake_euci):
    # Regression: road warrior (host-to-net) servers were counted here too,
    # same as genuine site-to-site tunnels. They're identified by
    # 'ns_auth_mode' - the same field /usr/libexec/rpcd/ns.ovpntunnel's own
    # list_tunnels() checks to skip them ("skip road warrior servers").
    # check_ovpn_host2net.py already covers them, and treats 0 connected
    # clients as normal - counting them here too made a road warrior with no
    # client currently connected drag this check down to CRITICAL "All VPN
    # down" even when every real tunnel was healthy.
    instances = {"ns_roadwarrior1": {"enabled": "1", "ns_auth_mode": "certificate"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)
    ovpn = SimpleNamespace(list_connected_clients=lambda section, type: {"peer1": {}, "peer2": {}})
    fake_nethsec.install(utils=utils, ovpn=ovpn)
    fake_euci(vt, uci_obj=MagicMock())

    total, active = vt.count_openvpn_tunnels()

    assert (total, active) == (0, 0)


def test_openvpn_net_to_net_subnet_server_queried_as_subnet(fake_nethsec, fake_euci):
    # A genuine site-to-site (net-to-net) server: no client/ns_client flag
    # and no ns_auth_mode - unlike a road warrior, this must be counted.
    instances = {"ns_site_b": {"enabled": "1"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)
    seen_types = []

    def fake_list_connected_clients(section, type):
        seen_types.append(type)
        return {"peer1": {}, "peer2": {}}

    ovpn = SimpleNamespace(list_connected_clients=fake_list_connected_clients)
    fake_nethsec.install(utils=utils, ovpn=ovpn)
    fake_euci(vt, uci_obj=MagicMock())

    total, active = vt.count_openvpn_tunnels()

    assert seen_types == ["subnet"]
    assert (total, active) == (1, 2)  # 1 instance, 2 connected clients


def test_openvpn_disabled_instances_not_counted(fake_nethsec, fake_euci):
    instances = {"old": {"enabled": "0"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)
    fake_nethsec.install(utils=utils, ovpn=SimpleNamespace(list_connected_clients=lambda *a, **k: {}))
    fake_euci(vt, uci_obj=MagicMock())

    assert vt.count_openvpn_tunnels() == (0, 0)


def test_openvpn_empty_without_library(monkeypatch):
    monkeypatch.setattr(vt, "EUCI_AVAILABLE", False)

    assert vt.count_openvpn_tunnels() == (0, 0)


# --- list_openvpn_tunnels() (per-tunnel identification) ---------------------

def test_list_tunnels_names_which_one_is_down_when_several_configured(fake_nethsec, fake_euci):
    # The whole point of this function: with 2+ net-to-net tunnels, the
    # aggregate count_openvpn_tunnels() can only say "1 of 2 down" - it
    # can't say which. list_openvpn_tunnels() must name it.
    instances = {
        "ns_site_a": {"enabled": "1"},   # connected
        "ns_site_b": {"enabled": "1"},   # not connected
    }
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)

    def fake_list_connected_clients(section, type):
        return {"peer1": {}} if section == "ns_site_a" else {}

    ovpn = SimpleNamespace(list_connected_clients=fake_list_connected_clients)
    fake_nethsec.install(utils=utils, ovpn=ovpn)
    fake_euci(vt, uci_obj=MagicMock())

    details = {d["name"]: d for d in vt.list_openvpn_tunnels()}

    assert details["ns_site_a"]["up"] is True
    assert details["ns_site_a"]["clients"] == 1
    assert details["ns_site_b"]["up"] is False
    assert details["ns_site_b"]["clients"] == 0


def test_list_tunnels_excludes_road_warrior(fake_nethsec, fake_euci):
    instances = {"ns_roadwarrior1": {"enabled": "1", "ns_auth_mode": "certificate"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)
    ovpn = SimpleNamespace(list_connected_clients=lambda section, type: {"peer1": {}})
    fake_nethsec.install(utils=utils, ovpn=ovpn)
    fake_euci(vt, uci_obj=MagicMock())

    assert vt.list_openvpn_tunnels() == []


def test_list_tunnels_p2p_client_up_requires_traffic_both_directions(fake_nethsec, fake_euci):
    instances = {"ns_client_a": {"enabled": "1", "client": "1"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)
    ovpn = SimpleNamespace(list_connected_clients=lambda section, type: {"stats": {"bytes_received": 10, "bytes_sent": 0}})
    fake_nethsec.install(utils=utils, ovpn=ovpn)
    fake_euci(vt, uci_obj=MagicMock())

    details = vt.list_openvpn_tunnels()

    assert details == [{"name": "ns_client_a", "up": False, "label": "ns_client_a", "clients": 0}]


def test_count_openvpn_tunnels_derived_from_list(fake_nethsec, fake_euci):
    # count_openvpn_tunnels() must agree with list_openvpn_tunnels() - it's
    # meant to be a pure aggregation of the same data, not a second query.
    instances = {
        "ns_site_a": {"enabled": "1"},
        "ns_site_b": {"enabled": "1"},
    }
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)

    def fake_list_connected_clients(section, type):
        return {"peer1": {}} if section == "ns_site_a" else {}

    ovpn = SimpleNamespace(list_connected_clients=fake_list_connected_clients)
    fake_nethsec.install(utils=utils, ovpn=ovpn)
    fake_euci(vt, uci_obj=MagicMock())

    total, active = vt.count_openvpn_tunnels()

    assert (total, active) == (2, 1)


# --- _parse_swanctl_sas() ----------------------------------------------------

# Captured verbatim from `swanctl --list-sas --pretty` on nsec8-test against
# an unreachable peer: IKE_SA still negotiating, no child SA yet.
_SWANCTL_CONNECTING = """list-sa event {
  ns_b4100974 {
    uniqueid = 1
    version = 2
    state = CONNECTING
    local-host = 192.168.10.180
    local-port = 500
    local-id = %any
    remote-host = 2.43.5.33
    remote-port = 500
    remote-id = %any
    initiator = yes
    initiator-spi = ef5dfa14fb0f771b
    responder-spi = 0000000000000000
    tasks-active = [
      IKE_VENDOR
      IKE_INIT
      IKE_NATD
      IKE_CERT_PRE
      IKE_AUTH
      IKE_CERT_POST
      IKE_CONFIG
      IKE_AUTH_LIFETIME
      IKE_MOBIKE
      IKE_ESTABLISH
      CHILD_CREATE
    ]
    child-sas {
    }
  }
}
list-sas reply {
}
"""

# Synthetic: IKE_SA established with one child SA (the data tunnel) installed.
_SWANCTL_ESTABLISHED = """list-sa event {
  ns_b4100974 {
    uniqueid = 1
    version = 2
    state = ESTABLISHED
    local-host = 192.168.10.180
    remote-host = 2.43.5.33
    child-sas {
      ns_b4100974_tunnel_1 {
        reqid = 1
        state = INSTALLED
        mode = TUNNEL
        protocol = ESP
      }
    }
  }
}
list-sas reply {
}
"""

# Synthetic: IKE_SA established but its child SA has not (yet) come up -
# must NOT count as up, unlike a naive "IKE state == ESTABLISHED" check.
_SWANCTL_ESTABLISHED_NO_CHILD = """list-sa event {
  ns_b4100974 {
    uniqueid = 1
    version = 2
    state = ESTABLISHED
    local-host = 192.168.10.180
    remote-host = 2.43.5.33
    child-sas {
    }
  }
}
list-sas reply {
}
"""


def test_parse_swanctl_connecting_has_no_installed_child():
    conns = vt._parse_swanctl_sas(_SWANCTL_CONNECTING)

    assert conns["ns_b4100974"]["state"] == "CONNECTING"
    assert conns["ns_b4100974"]["children"] == []


def test_parse_swanctl_established_with_installed_child():
    conns = vt._parse_swanctl_sas(_SWANCTL_ESTABLISHED)

    assert conns["ns_b4100974"]["state"] == "ESTABLISHED"
    assert conns["ns_b4100974"]["children"] == ["INSTALLED"]


def test_parse_swanctl_ignores_nested_child_state_for_ike_state():
    # Regression risk: a naive "last 'state = X' wins" parser would let the
    # child SA's INSTALLED state overwrite the IKE_SA's own ESTABLISHED.
    conns = vt._parse_swanctl_sas(_SWANCTL_ESTABLISHED)

    assert conns["ns_b4100974"]["state"] == "ESTABLISHED"


# --- list_ipsec_tunnels() -----------------------------------------------------

def _install_ipsec_remote(fake_nethsec, remotes):
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: remotes)
    fake_nethsec.install(utils=utils)


def test_ipsec_up_requires_established_and_installed_child(fake_nethsec, fake_euci, monkeypatch):
    _install_ipsec_remote(fake_nethsec, {
        "ns_b4100974": {"ns_name": "Checkmk", "enabled": "1"},
    })
    fake_euci(vt, uci_obj=MagicMock())
    monkeypatch.setattr(vt.shutil, "which", lambda name: "/usr/sbin/swanctl")
    monkeypatch.setattr(subprocess, "run",
                         lambda cmd, **kw: MagicMock(stdout=_SWANCTL_ESTABLISHED))

    tunnels = vt.list_ipsec_tunnels()

    assert tunnels == [{"name": "ns_b4100974", "label": "Checkmk", "up": True}]


def test_ipsec_established_without_installed_child_is_down(fake_nethsec, fake_euci, monkeypatch):
    _install_ipsec_remote(fake_nethsec, {
        "ns_b4100974": {"ns_name": "Checkmk", "enabled": "1"},
    })
    fake_euci(vt, uci_obj=MagicMock())
    monkeypatch.setattr(vt.shutil, "which", lambda name: "/usr/sbin/swanctl")
    monkeypatch.setattr(subprocess, "run",
                         lambda cmd, **kw: MagicMock(stdout=_SWANCTL_ESTABLISHED_NO_CHILD))

    tunnels = vt.list_ipsec_tunnels()

    assert tunnels[0]["up"] is False


def test_ipsec_connecting_is_down(fake_nethsec, fake_euci, monkeypatch):
    _install_ipsec_remote(fake_nethsec, {
        "ns_b4100974": {"ns_name": "Checkmk", "enabled": "1"},
    })
    fake_euci(vt, uci_obj=MagicMock())
    monkeypatch.setattr(vt.shutil, "which", lambda name: "/usr/sbin/swanctl")
    monkeypatch.setattr(subprocess, "run",
                         lambda cmd, **kw: MagicMock(stdout=_SWANCTL_CONNECTING))

    tunnels = vt.list_ipsec_tunnels()

    assert tunnels[0]["up"] is False


def test_ipsec_disabled_not_counted(fake_nethsec, fake_euci, monkeypatch):
    _install_ipsec_remote(fake_nethsec, {
        "ns_b4100974": {"ns_name": "Checkmk", "enabled": "0"},
    })
    fake_euci(vt, uci_obj=MagicMock())
    monkeypatch.setattr(vt.shutil, "which", lambda name: "/usr/sbin/swanctl")
    monkeypatch.setattr(subprocess, "run",
                         lambda cmd, **kw: MagicMock(stdout=_SWANCTL_ESTABLISHED))

    assert vt.list_ipsec_tunnels() == []


def test_ipsec_label_falls_back_to_section_name(fake_nethsec, fake_euci, monkeypatch):
    _install_ipsec_remote(fake_nethsec, {
        "ns_b4100974": {"enabled": "1"},  # no ns_name
    })
    fake_euci(vt, uci_obj=MagicMock())
    monkeypatch.setattr(vt.shutil, "which", lambda name: "/usr/sbin/swanctl")
    monkeypatch.setattr(subprocess, "run",
                         lambda cmd, **kw: MagicMock(stdout=_SWANCTL_ESTABLISHED))

    tunnels = vt.list_ipsec_tunnels()

    assert tunnels[0]["label"] == "ns_b4100974"


def test_ipsec_down_when_swanctl_binary_unavailable(fake_nethsec, fake_euci, monkeypatch):
    _install_ipsec_remote(fake_nethsec, {
        "ns_b4100974": {"ns_name": "Checkmk", "enabled": "1"},
    })
    fake_euci(vt, uci_obj=MagicMock())
    monkeypatch.setattr(vt.shutil, "which", lambda name: None)

    tunnels = vt.list_ipsec_tunnels()

    assert tunnels[0]["up"] is False


def test_ipsec_empty_without_library(monkeypatch):
    monkeypatch.setattr(vt, "EUCI_AVAILABLE", False)

    assert vt.list_ipsec_tunnels() == []


# --- main(): per-tunnel service lines ----------------------------------------

def test_main_prints_one_service_line_per_tunnel(monkeypatch, capsys):
    monkeypatch.setattr(vt, "list_openvpn_tunnels", lambda: [
        {"name": "ns_site_a", "up": True, "label": "ns_site_a", "clients": 1},
        {"name": "ns_site_b", "up": False, "label": "ns_site_b", "clients": 0},
    ])
    monkeypatch.setattr(vt, "list_ipsec_tunnels", lambda: [])

    vt.main()
    lines = capsys.readouterr().out.strip().splitlines()

    assert split_check_result(lines[0])[:2] == ("0", "VPN.Tunnel.OVPN.ns_site_a")
    assert split_check_result(lines[1])[:2] == ("2", "VPN.Tunnel.OVPN.ns_site_b")
    assert len(lines) == 2


def test_main_prints_one_service_line_per_ipsec_tunnel(monkeypatch, capsys):
    monkeypatch.setattr(vt, "list_openvpn_tunnels", lambda: [])
    monkeypatch.setattr(vt, "list_ipsec_tunnels", lambda: [
        {"name": "ns_b4100974", "label": "Checkmk", "up": False},
    ])

    vt.main()
    lines = capsys.readouterr().out.strip().splitlines()

    assert len(lines) == 1
    # Prefixed distinctly from OpenVPN's "VPN.Tunnel.OVPN.<label>" so the two
    # label namespaces (both operator-chosen ns_name values) can't collide.
    assert split_check_result(lines[0])[:2] == ("2", "VPN.Tunnel.IPsec.Checkmk")


def test_main_no_vpn_configured(monkeypatch, capsys):
    monkeypatch.setattr(vt, "list_openvpn_tunnels", lambda: [])
    monkeypatch.setattr(vt, "list_ipsec_tunnels", lambda: [])

    vt.main()
    out = capsys.readouterr().out.strip()

    # Nothing configured at all - no OpenVPN tunnels, no IPsec tunnels -
    # means no service lines at all, not a permanent uninformative OK.
    assert out == ""
