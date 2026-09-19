#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""Tests for check_firewall_rules.py.

Covers: nft-JSON structured counting (vs the old fragile text-heuristic
that undercounted "ct ..." dispatch rules present in nearly every real
ruleset), the UCI fallback via nethsec.utils.get_all_by_type, and the
perfdata-placement regression on both branches.
"""

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import check_firewall_rules as fr
from checkmk_format import graphed_metric_names, parse_perfdata, split_check_result

NFT_JSON = json.dumps({
    "nftables": [
        {"metainfo": {"version": "1.0.9"}},
        {"table": {"family": "inet", "name": "fw4"}},
        {"chain": {"family": "inet", "table": "fw4", "name": "input"}},
        {"chain": {"family": "inet", "table": "fw4", "name": "forward"}},
        {"rule": {"family": "inet", "table": "fw4", "chain": "input", "expr": [
            {"match": {"op": "in", "left": {"ct": {"key": "state"}}, "right": ["established", "related"]}},
        ]}},
        {"rule": {"family": "inet", "table": "fw4", "chain": "forward", "expr": []}},
    ]
})


# --- count_nft_rulesets() ----------------------------------------------------

def test_count_nft_rulesets_counts_ct_dispatch_rules(monkeypatch):
    # Regression: the previous text-based heuristic never counted rules
    # whose statement starts with "ct " (e.g. "ct state established,related
    # accept"), which fw4 puts in nearly every real chain - JSON counting by
    # key presence doesn't have that blind spot.
    monkeypatch.setattr(
        subprocess, "run",
        MagicMock(return_value=MagicMock(returncode=0, stdout=NFT_JSON)),
    )

    result, err = fr.count_nft_rulesets("/usr/sbin/nft")

    assert err is None
    assert result == {"tables": 1, "chains": 2, "rules": 2}


def test_count_nft_rulesets_reports_error_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        MagicMock(return_value=MagicMock(returncode=1, stderr="Operation not permitted")),
    )

    result, err = fr.count_nft_rulesets("/usr/sbin/nft")

    assert result is None
    assert "Operation not permitted" in err


def test_count_nft_rulesets_handles_timeout(monkeypatch):
    monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=subprocess.TimeoutExpired(cmd="nft", timeout=15)))

    result, err = fr.count_nft_rulesets("/usr/sbin/nft")

    assert result is None
    assert "timed out" in err


def test_count_nft_rulesets_handles_invalid_json(monkeypatch):
    monkeypatch.setattr(subprocess, "run", MagicMock(return_value=MagicMock(returncode=0, stdout="not json")))

    result, err = fr.count_nft_rulesets("/usr/sbin/nft")

    assert result is None
    assert "JSON parse error" in err


# --- count_uci_firewall() ----------------------------------------------------

def test_count_uci_firewall_uses_library(fake_euci_module):
    uci_obj = MagicMock()
    fake_euci_module(uci_obj)
    counts = {"zone": [1, 2], "forwarding": [1], "rule": [1, 2, 3, 4], "redirect": []}
    fake_utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: counts[kind])
    import sys
    import types
    pkg = types.ModuleType("nethsec")
    pkg.utils = fake_utils
    sys.modules["nethsec"] = pkg
    sys.modules["nethsec.utils"] = fake_utils

    result, err = fr.count_uci_firewall()

    assert err is None
    assert result == {"zones": 2, "forwardings": 1, "rules": 4, "redirects": 0}


def test_count_uci_firewall_unavailable_without_library(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in ("euci", "nethsec.utils"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    result, err = fr.count_uci_firewall()

    assert result is None
    assert "not available" in err


# --- main(): nft-first, UCI fallback, perfdata ------------------------------

def test_main_uses_nft_when_available(monkeypatch, capsys):
    monkeypatch.setattr(fr, "find_nft", lambda: "/usr/sbin/nft")
    monkeypatch.setattr(fr, "count_nft_rulesets", lambda nft_bin: ({"tables": 3, "chains": 40, "rules": 87}, None))

    fr.main()
    line = capsys.readouterr().out.strip()

    state, service, perf, text = split_check_result(line)
    assert state == "0"
    # Regression: perfdata was previously placed after "OK - ...", so field3
    # was just "-" and nothing was graphed.
    assert graphed_metric_names(line) == {"tables", "chains", "rules"}
    assert dict(parse_perfdata(perf)) == {"tables": 3.0, "chains": 40.0, "rules": 87.0}
    assert "(nft)" in text


def test_main_falls_back_to_uci_when_nft_unavailable(monkeypatch, capsys):
    monkeypatch.setattr(fr, "find_nft", lambda: None)
    monkeypatch.setattr(fr, "count_uci_firewall", lambda: ({"zones": 2, "forwardings": 1, "rules": 4, "redirects": 0}, None))

    fr.main()
    line = capsys.readouterr().out.strip()

    assert graphed_metric_names(line) == {"zones", "forwardings", "rules"}
    assert "(UCI)" in line


def test_main_unknown_when_both_sources_fail(monkeypatch, capsys):
    monkeypatch.setattr(fr, "find_nft", lambda: "/usr/sbin/nft")
    monkeypatch.setattr(fr, "count_nft_rulesets", lambda nft_bin: (None, "nft error: boom"))
    monkeypatch.setattr(fr, "count_uci_firewall", lambda: (None, "UCI error: boom"))

    fr.main()
    line = capsys.readouterr().out.strip()

    state, _, _, text = split_check_result(line)
    assert state == "3"
    assert "nft error: boom" in text
    assert "UCI error: boom" in text
