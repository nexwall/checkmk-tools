"""Tests for lib/common.py's _with_progress_fancy helper.

Added 2026-08-03: rather than adding -o Dpkg::Progress-Fancy=1 at every
individual apt-get/apt call site across the installer's steps (11+ places),
run() injects it centrally for any apt-get/apt command, so every step gets
a real percentage progress bar for free without repeating the flag.
"""

import sys
from pathlib import Path

PACKAGE_DIR = (
    Path(__file__).resolve().parents[2]
    / "script-tools"
    / "full"
    / "installation"
    / "checkmk"
)
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

import lib.common as common  # noqa: E402


def test_injects_flag_for_apt_get():
    result = common._with_progress_fancy(["apt-get", "install", "-y", "chrony"])
    assert result == ["apt-get", "-o", "Dpkg::Progress-Fancy=1", "install", "-y", "chrony"]


def test_injects_flag_for_apt():
    result = common._with_progress_fancy(["apt", "install", "-y", "chrony"])
    assert result == ["apt", "-o", "Dpkg::Progress-Fancy=1", "install", "-y", "chrony"]


def test_applies_to_non_install_apt_subcommands_too():
    result = common._with_progress_fancy(["apt-get", "purge", "-y", "postfix"])
    assert result == ["apt-get", "-o", "Dpkg::Progress-Fancy=1", "purge", "-y", "postfix"]


def test_leaves_unrelated_commands_untouched():
    result = common._with_progress_fancy(["systemctl", "restart", "apache2"])
    assert result == ["systemctl", "restart", "apache2"]


def test_does_not_duplicate_flag_if_already_present():
    cmd = ["apt-get", "-o", "Dpkg::Progress-Fancy=1", "install", "-y", "chrony"]
    result = common._with_progress_fancy(cmd)
    assert result == cmd
    assert result.count("Dpkg::Progress-Fancy=1") == 1


def test_empty_command_list_is_a_noop():
    assert common._with_progress_fancy([]) == []
