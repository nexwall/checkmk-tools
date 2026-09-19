"""Tests for steps/checkmk.py's package-install command choice.

Regression coverage for the 2026-08-03 change: gdebi -n <path> was replaced
with apt-get install -y <path> for installing the CheckMK .deb (local or
downloaded), because gdebi has no progress feedback for a long unpack.
Dpkg::Progress-Fancy=1 is NOT added at this call site - it's injected
centrally by lib/common.py's run() for every apt-get/apt command (see
test_common_progress_fancy.py), so checkmk.py itself only needs to pass the
plain apt-get invocation. gdebi-core is no longer installed as a
prerequisite either, since nothing needs it anymore.
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

import steps.checkmk as checkmk_module  # noqa: E402


@pytest.fixture()
def recorded_commands(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, check=True):
        calls.append(list(cmd))

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(checkmk_module, "run_cmd", fake_run)
    monkeypatch.setattr(checkmk_module, "run_capture", lambda cmd, check=False: "monitoring")
    monkeypatch.setattr(checkmk_module, "run_stdin", lambda cmd, text, check=False: None)
    monkeypatch.setattr(checkmk_module, "command_exists", lambda name: True)
    return calls


def test_local_deb_install_uses_apt_get_not_gdebi(tmp_path, recorded_commands, minimal_installer_config):
    deb_file = tmp_path / "check-mk-community-2.5.0p10_0.jammy_amd64.deb"
    deb_file.write_bytes(b"fake deb content")

    cfg = minimal_installer_config(checkmk_deb_url=str(deb_file))
    checkmk_module.run_step(cfg)

    install_calls = [c for c in recorded_commands if str(deb_file) in c]
    assert len(install_calls) == 1
    assert install_calls[0] == ["apt-get", "install", "-y", str(deb_file)]
    assert not any("gdebi" in c for c in recorded_commands)


def test_gdebi_core_is_no_longer_installed(tmp_path, recorded_commands, minimal_installer_config):
    deb_file = tmp_path / "check-mk-community-2.5.0p10_0.jammy_amd64.deb"
    deb_file.write_bytes(b"fake deb content")

    cfg = minimal_installer_config(checkmk_deb_url=str(deb_file))
    checkmk_module.run_step(cfg)

    assert not any("gdebi-core" in c for c in recorded_commands)
