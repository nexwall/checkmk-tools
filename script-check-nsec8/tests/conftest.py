#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""Shared pytest setup: make full/*.py importable as plain modules."""

import sys
import types
from pathlib import Path

import pytest

FULL_DIR = Path(__file__).resolve().parent.parent / "full"
if str(FULL_DIR) not in sys.path:
    sys.path.insert(0, str(FULL_DIR))


@pytest.fixture
def fake_nethsec(monkeypatch):
    """Install fake nethsec.<submodule> modules into sys.modules.

    The scripts under test do `from nethsec.inventory import get_networks`
    etc. *inside* function bodies (not at module top level), specifically so
    they can be tried first and fall back to manual parsing if unavailable -
    the real python3-nethsec package isn't installed in this dev/test
    environment, so this fixture stands in for it.

    Usage: fake_nethsec.install(inventory=SimpleNamespace(get_networks=...))
    """

    class _Installer:
        def install(self, **submodules):
            pkg = types.ModuleType("nethsec")
            monkeypatch.setitem(sys.modules, "nethsec", pkg)
            for name, mod in submodules.items():
                full_name = f"nethsec.{name}"
                monkeypatch.setitem(sys.modules, full_name, mod)
                setattr(pkg, name, mod)
            return pkg

    return _Installer()


@pytest.fixture
def fake_euci(monkeypatch):
    """Patch a script module's EUCI_AVAILABLE/EUci to a fake context manager,
    without needing the real `euci` package installed.

    Usage: fake_euci(check_wan_status, uci_obj)  # uci_obj: whatever `u` should be
    """

    def _patch(module, uci_obj):
        monkeypatch.setattr(module, "EUCI_AVAILABLE", True, raising=False)

        class _FakeEUci:
            def __enter__(self):
                return uci_obj

            def __exit__(self, *exc_info):
                return False

        monkeypatch.setattr(module, "EUci", _FakeEUci, raising=False)

    return _patch


@pytest.fixture
def fake_euci_module(monkeypatch):
    """Install a fake `euci` package into sys.modules for scripts that do a
    fresh `from euci import EUci` inside a function body (rather than
    checking a module-level EUCI_AVAILABLE flag) - e.g. check_firewall_rules.py.

    Usage: fake_euci_module(uci_obj)
    """

    def _install(uci_obj):
        class _FakeEUci:
            def __enter__(self):
                return uci_obj

            def __exit__(self, *exc_info):
                return False

        euci_pkg = types.ModuleType("euci")
        euci_pkg.EUci = _FakeEUci
        monkeypatch.setitem(sys.modules, "euci", euci_pkg)

    return _install
