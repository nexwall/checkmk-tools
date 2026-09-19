#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""Tests for check_firewall_connections.py.

Covers: the unguarded-crash regression (unreadable/malformed sysctl files
raised a raw traceback instead of UNKNOWN), thresholds, and the
perfdata regression (only "connections" was ever real; "percent" was
previously dead text after a "|" in the free-text field).
"""

from unittest.mock import MagicMock

import check_firewall_connections as fc
from checkmk_format import graphed_metric_names, parse_perfdata, split_check_result


def _mock_sysctl(monkeypatch, count, maxval, exists=True):
    def fake_path(p):
        m = MagicMock()
        m.exists.return_value = exists
        if "count" in p:
            m.read_text.return_value = str(count)
        else:
            m.read_text.return_value = str(maxval)
        return m

    monkeypatch.setattr(fc, "Path", fake_path)


def test_conntrack_unavailable_when_sysctl_missing(monkeypatch):
    _mock_sysctl(monkeypatch, 0, 0, exists=False)

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fc.main()
    line = buf.getvalue().strip()

    assert split_check_result(line)[0] == "1"
    assert "not available" in line


def test_malformed_sysctl_value_returns_unknown_not_traceback(monkeypatch):
    # Regression: an unreadable/malformed sysctl file previously crashed
    # with a raw Python traceback, violating the project's own
    # "no Python traceback" rule.
    def fake_path(p):
        m = MagicMock()
        m.exists.return_value = True
        m.read_text.return_value = "not-a-number"
        return m

    monkeypatch.setattr(fc, "Path", fake_path)

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fc.main()
    line = buf.getvalue().strip()

    assert rc == 0
    assert split_check_result(line)[0] == "3"
    assert "UNKNOWN" in line


def test_main_ok_below_80_percent(monkeypatch, capsys):
    _mock_sysctl(monkeypatch, 100, 10000)  # 1%

    fc.main()
    line = capsys.readouterr().out.strip()

    state, service, perf, text = split_check_result(line)
    assert state == "0"
    # Regression: "percent" was previously appended after a "|" inside the
    # free-text field (field 4+), so only "connections" was ever real.
    assert graphed_metric_names(line) == {"connections", "percent"}
    values = dict(parse_perfdata(perf))
    assert values == {"connections": 100.0, "percent": 1.0}


def test_main_warning_at_80_percent(monkeypatch, capsys):
    _mock_sysctl(monkeypatch, 8000, 10000)  # 80%

    fc.main()
    line = capsys.readouterr().out.strip()

    assert split_check_result(line)[0] == "1"


def test_main_critical_at_90_percent(monkeypatch, capsys):
    _mock_sysctl(monkeypatch, 9000, 10000)  # 90%

    fc.main()
    line = capsys.readouterr().out.strip()

    assert split_check_result(line)[0] == "2"
