#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""Tests for check_dns_resolution.py.

Covers: raw DNS query construction/parsing (txid match, rcode check),
timeout/exception handling, and the two-tier WARNING/CRITICAL threshold
logic - plus the perfdata-placement regression (successful/failed/total
were previously dead text after the free-text field, only "response_time"
was ever actually graphed).
"""

import socket
import struct
from unittest.mock import MagicMock

import check_dns_resolution as dns
from checkmk_format import graphed_metric_names, parse_perfdata, split_check_result


def _dns_response(txid, rcode=0, extra_len=8):
    """Build a minimal valid DNS response header matching the given txid/rcode."""
    flags = 0x8000 | (rcode & 0x000F)
    return struct.pack(">HH", txid, flags) + b"\x00" * extra_len


class _FakeSocket:
    def __init__(self, response, raise_on_recv=None):
        self._response = response
        self._raise_on_recv = raise_on_recv
        self.sent = None

    def settimeout(self, t):
        pass

    def sendto(self, data, addr):
        self.sent = (data, addr)

    def recvfrom(self, bufsize):
        if self._raise_on_recv:
            raise self._raise_on_recv
        return self._response, ("127.0.0.1", 53)

    def close(self):
        pass


# --- _build_query() -----------------------------------------------------------

def test_build_query_encodes_domain_labels_correctly():
    query = dns._build_query("a.bc", txid=0x1234)

    header = query[:12]
    assert struct.unpack(">H", header[:2])[0] == 0x1234
    # qname: length-prefixed labels "a" (1) then "bc" (2), terminated by 0x00
    qname = query[12:]
    assert qname[0] == 1 and qname[1:2] == b"a"
    assert qname[2] == 2 and qname[3:5] == b"bc"
    assert qname[5] == 0  # root terminator


# --- resolve() ------------------------------------------------------------------

def test_resolve_ok_when_txid_and_rcode_match(monkeypatch):
    captured_txid = {}

    def fake_socket_ctor(*a, **k):
        return _FakeSocket(response=b"")  # placeholder, patched below

    # We need the txid resolve() picks (time-based) to build a matching response.
    monkeypatch.setattr(dns.time, "time", lambda: 1234.0)
    expected_txid = int(1234.0 * 1000) & 0xFFFF

    def fake_socket_ctor2(family, type_):
        return _FakeSocket(response=_dns_response(expected_txid, rcode=0))

    monkeypatch.setattr(socket, "socket", fake_socket_ctor2)

    ok, ms = dns.resolve("google.com")

    assert ok is True
    assert ms >= 0


def test_resolve_fails_on_txid_mismatch(monkeypatch):
    monkeypatch.setattr(dns.time, "time", lambda: 1234.0)

    def fake_socket_ctor(family, type_):
        return _FakeSocket(response=_dns_response(txid=0x9999, rcode=0))  # wrong txid

    monkeypatch.setattr(socket, "socket", fake_socket_ctor)

    ok, _ = dns.resolve("google.com")

    assert ok is False


def test_resolve_fails_on_nxdomain_rcode(monkeypatch):
    monkeypatch.setattr(dns.time, "time", lambda: 1234.0)
    expected_txid = int(1234.0 * 1000) & 0xFFFF

    def fake_socket_ctor(family, type_):
        return _FakeSocket(response=_dns_response(expected_txid, rcode=3))  # NXDOMAIN

    monkeypatch.setattr(socket, "socket", fake_socket_ctor)

    ok, _ = dns.resolve("nonexistent.invalid")

    assert ok is False


def test_resolve_fails_on_timeout(monkeypatch):
    def fake_socket_ctor(family, type_):
        return _FakeSocket(response=b"", raise_on_recv=socket.timeout("timed out"))

    monkeypatch.setattr(socket, "socket", fake_socket_ctor)

    ok, ms = dns.resolve("google.com", timeout_sec=1)

    assert ok is False
    assert ms >= 0


def test_resolve_fails_on_truncated_response(monkeypatch):
    def fake_socket_ctor(family, type_):
        return _FakeSocket(response=b"\x00\x01")  # too short to be a valid header

    monkeypatch.setattr(socket, "socket", fake_socket_ctor)

    ok, _ = dns.resolve("google.com")

    assert ok is False


# --- main(): thresholds + perfdata regression -------------------------------

def test_main_ok_all_succeed_fast(monkeypatch, capsys):
    monkeypatch.setattr(dns, "resolve", lambda domain, **k: (True, 10))

    dns.main()
    line = capsys.readouterr().out.strip()

    state, service, perf, text = split_check_result(line)
    assert state == "0"
    # Regression: successful/failed/total were previously placed after the
    # free text, so only "response_time" was ever actually graphed.
    assert graphed_metric_names(line) == {"response_time", "successful", "failed", "total"}
    values = dict(parse_perfdata(perf))
    assert values == {"response_time": 10.0, "successful": 3.0, "failed": 0.0, "total": 3.0}


def test_main_warning_between_500_and_1000ms(monkeypatch, capsys):
    monkeypatch.setattr(dns, "resolve", lambda domain, **k: (True, 700))

    dns.main()
    line = capsys.readouterr().out.strip()

    assert split_check_result(line)[0] == "1"


def test_main_critical_above_1000ms(monkeypatch, capsys):
    monkeypatch.setattr(dns, "resolve", lambda domain, **k: (True, 1500))

    dns.main()
    line = capsys.readouterr().out.strip()

    assert split_check_result(line)[0] == "2"


def test_main_warning_on_partial_failure(monkeypatch, capsys):
    results = iter([(True, 10), (False, 0), (True, 10)])
    monkeypatch.setattr(dns, "resolve", lambda domain, **k: next(results))

    dns.main()
    line = capsys.readouterr().out.strip()

    state, _, perf, _ = split_check_result(line)
    assert state == "1"
    assert dict(parse_perfdata(perf))["failed"] == 1.0


def test_main_critical_when_all_domains_fail(monkeypatch, capsys):
    monkeypatch.setattr(dns, "resolve", lambda domain, **k: (False, 0))

    dns.main()
    line = capsys.readouterr().out.strip()

    state, _, _, text = split_check_result(line)
    assert state == "2"
    assert "not responding" in text
