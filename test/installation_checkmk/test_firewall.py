"""Tests for steps/firewall.py's ufw enable invocation.

Regression coverage for the 2026-08-03 change: "echo y | ufw enable" still
prints ufw's own confirmation prompt to stdout before consuming the piped
answer, making it look like the installer is asking a question it has
already silently decided - confusing during a live run. ufw --force enable
suppresses the prompt entirely instead of pre-answering it.
"""

import sys
from pathlib import Path

import pytest

PACKAGE_DIR = (
    Path(__file__).resolve().parents[2]
    / "script-tools"
    / "full"
    / "installation"
    / "checkmk"
)
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

import steps.firewall as firewall_module  # noqa: E402


@pytest.fixture()
def recorded_commands(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, check=True):
        calls.append(list(cmd))

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(firewall_module, "run_cmd", fake_run)
    return calls


def test_ufw_enable_uses_force_flag_not_piped_echo(recorded_commands, minimal_installer_config):
    cfg = minimal_installer_config()
    firewall_module.run_step(cfg)

    assert ["ufw", "--force", "enable"] in recorded_commands
    assert not any("echo y" in " ".join(c) for c in recorded_commands)
