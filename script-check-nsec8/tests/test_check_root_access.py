#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""Tests for check_root_access.py.

Covers: the 3 real root-login log formats (SSH/console/web UI - the exact
bug found live, where 2 of 3 were silently missed), the full-log-scan fix
(no more 500-line tail cap), /proc PPid-based main-daemon exclusion, and the
consolidated perfdata regression (was split across dead-text duplicate
metric names).
"""

import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import check_root_access as ra
from checkmk_format import graphed_metric_names, parse_perfdata, split_check_result


# --- parse_auth_log(): the 3 real login-event formats -----------------------

def _mock_logread(monkeypatch, lines):
    monkeypatch.setattr(
        subprocess, "run",
        MagicMock(return_value=MagicMock(returncode=0, stdout="\n".join(lines))),
    )


def test_parse_auth_log_detects_ssh_password_success(monkeypatch):
    _mock_logread(monkeypatch, [
        "Jul 17 17:07:51 dropbear[17561]: Password auth succeeded for 'root' from 192.168.10.189:53614",
    ])

    successful, failed, ips = ra.parse_auth_log()

    assert (successful, failed) == (1, 0)
    assert ips == ["192.168.10.189"]


def test_parse_auth_log_detects_console_login_success(monkeypatch):
    # Regression: this format (busybox `login`) was NOT matched by the
    # original SSH-only marker list at all.
    _mock_logread(monkeypatch, ["Jul 17 13:30:45 login[1478]: root login on 'ttyS0'"])

    successful, failed, _ = ra.parse_auth_log()

    assert successful == 1
    assert failed == 0


def test_parse_auth_log_detects_web_ui_success_and_failure(monkeypatch):
    # Regression: "authentication success/failed" (web UI login) was NOT
    # matched by the original marker list, and is a DIFFERENT string from
    # the much noisier "authorization success" (logged on every API call).
    _mock_logread(monkeypatch, [
        "nethsecurity-api[6528]: ... authentication success for user root from 192.168.10.184",
        "nethsecurity-api[6528]: ... authentication failed for user root from 10.0.0.5: bad password",
    ])

    successful, failed, ips = ra.parse_auth_log()

    assert (successful, failed) == (1, 1)
    assert ips == ["192.168.10.184"]


def test_parse_auth_log_ignores_noisy_authorization_lines(monkeypatch):
    # The repeated per-API-call "authorization success" heartbeat must NOT
    # be miscounted as a login event (it fires roughly every 60s regardless
    # of any actual login).
    _mock_logread(monkeypatch, [
        "nethsecurity-api[6528]: ... authorization success for user root. POST /api/ubus/call",
    ] * 50)

    successful, failed, _ = ra.parse_auth_log()

    assert (successful, failed) == (0, 0)


def test_parse_auth_log_ignores_non_root_logins(monkeypatch):
    _mock_logread(monkeypatch, ["dropbear: Password auth succeeded for 'admin' from 10.0.0.1"])

    successful, _, _ = ra.parse_auth_log()

    assert successful == 0


def test_parse_auth_log_scans_full_log_not_just_a_tail(monkeypatch):
    # Regression: a real login event was previously lost because it fell
    # outside a hardcoded lines[-500:] window once enough heartbeat noise
    # accumulated after it. Simulate >500 lines of noise BEFORE a real event.
    noise = ["nethsecurity-api: authorization success for user root. GET /x"] * 600
    real_login = ["dropbear: Password auth succeeded for 'root' from 192.168.10.189"]
    _mock_logread(monkeypatch, real_login + noise)

    successful, _, _ = ra.parse_auth_log()

    assert successful == 1


def test_parse_auth_log_falls_back_to_var_log_messages(monkeypatch):
    monkeypatch.setattr(subprocess, "run", MagicMock(return_value=MagicMock(returncode=1, stdout="")))
    monkeypatch.setattr(type(ra.LOG_FILE), "exists", lambda self: True)
    monkeypatch.setattr(
        type(ra.LOG_FILE), "read_text",
        lambda self, encoding=None, errors=None: "dropbear: Password auth succeeded for 'root' from 1.2.3.4\n",
    )

    successful, _, _ = ra.parse_auth_log()

    assert successful == 1


def test_parse_auth_log_returns_none_when_no_log_source_available(monkeypatch):
    monkeypatch.setattr(subprocess, "run", MagicMock(return_value=MagicMock(returncode=1, stdout="")))
    monkeypatch.setattr(type(ra.LOG_FILE), "exists", lambda self: False)

    successful, failed, ips = ra.parse_auth_log()

    assert (successful, failed, ips) == (None, None, [])


# --- get_active_root_sessions(): main-daemon exclusion via PPid -------------

def _fake_proc_dir(entries):
    """entries: list of (pid, cmdline_bytes, status_text)."""
    procs = []
    for pid, cmdline, status in entries:
        p = MagicMock()
        p.name = str(pid)
        p.__truediv__ = lambda self, part, _cmdline=cmdline, _status=status: (
            SimpleNamespace(read_bytes=lambda: _cmdline) if part == "cmdline"
            else SimpleNamespace(read_text=lambda: _status)
        )
        procs.append(p)
    return procs


def test_get_active_root_sessions_excludes_main_daemon_via_ppid(monkeypatch):
    # Regression: the original check compared "PPID:" (never matches real
    # /proc/<pid>/status, which uses "PPid:") so the main daemon was always
    # miscounted as a session. It also wrongly required PID 1's own cmdline
    # to mention dropbear/sshd, which is never true (PID 1 is always init).
    procs = _fake_proc_dir([
        (100, b"/usr/sbin/dropbear -F", "Name:\tdropbear\nPPid:\t1\n"),  # main daemon - PPid 1
        (101, b"/usr/sbin/dropbear -F", "Name:\tdropbear\nPPid:\t100\n"),  # real session child
    ])
    monkeypatch.setattr(ra.Path, "iterdir", lambda self: iter(procs))

    count, sessions = ra.get_active_root_sessions()

    assert count == 1
    assert sessions == {"proc:101"}


def test_get_active_root_sessions_ignores_non_ssh_processes(monkeypatch):
    procs = _fake_proc_dir([(200, b"/usr/sbin/crond", "Name:\tcrond\nPPid:\t1\n")])
    monkeypatch.setattr(ra.Path, "iterdir", lambda self: iter(procs))

    count, _ = ra.get_active_root_sessions()

    assert count == 0


# --- main(): login_state + threshold branches + perfdata --------------------

def test_main_ok_with_recent_successful_login(monkeypatch, capsys):
    monkeypatch.setattr(ra, "get_active_root_sessions", lambda: (1, {"proc:1"}))
    monkeypatch.setattr(ra, "parse_auth_log", lambda: (2, 0, ["1.2.3.4"]))

    ra.main()
    line = capsys.readouterr().out.strip()

    state, service, perf, text = split_check_result(line)
    assert state == "0"
    assert "login_state=passed" in text
    # Regression: perfdata was previously split across 3 space-separated
    # tokens plus a trailing "| ..." block (only "sessions" was ever
    # actually graphed); active_sessions/successful_logins/failed_logins
    # duplicated sessions/logins/failed under different, dead names.
    assert graphed_metric_names(line) == {"sessions", "logins", "failed", "unique_ips"}
    perf_values = dict(parse_perfdata(split_check_result(line)[2]))
    assert perf_values == {"sessions": 1.0, "logins": 2.0, "failed": 0.0, "unique_ips": 1.0}


def test_main_login_state_failed_takes_priority_over_passed(monkeypatch, capsys):
    monkeypatch.setattr(ra, "get_active_root_sessions", lambda: (0, set()))
    monkeypatch.setattr(ra, "parse_auth_log", lambda: (1, 1, ["9.9.9.9"]))

    ra.main()
    line = capsys.readouterr().out.strip()

    assert "login_state=failed" in line


def test_main_critical_on_too_many_failed_attempts(monkeypatch, capsys):
    monkeypatch.setattr(ra, "get_active_root_sessions", lambda: (0, set()))
    monkeypatch.setattr(ra, "parse_auth_log", lambda: (0, ra.FAILED_CRIT, []))

    ra.main()
    line = capsys.readouterr().out.strip()

    assert split_check_result(line)[0] == "2"


def test_main_auth_log_unavailable_does_not_invent_login_state(monkeypatch, capsys):
    monkeypatch.setattr(ra, "get_active_root_sessions", lambda: (1, {"proc:1"}))
    monkeypatch.setattr(ra, "parse_auth_log", lambda: (None, None, []))

    ra.main()
    line = capsys.readouterr().out.strip()

    assert "login_state=none" in line
    assert "(auth log unavailable)" in line
