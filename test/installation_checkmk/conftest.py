"""Shared pytest setup for the checkmk Python installer package's tests.

The package (script-tools/full/installation/checkmk) uses plain relative
imports (from lib.common import ..., from steps import ...), so its own
directory is added to sys.path to let those imports resolve normally - no
stubbing needed, everything imported is pure stdlib.
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


@pytest.fixture()
def remove_all_module():
    import steps.remove_all as module

    return module


@pytest.fixture()
def installer_module():
    import installer as module

    return module


@pytest.fixture()
def minimal_installer_config():
    from lib.config import InstallerConfig

    def _make(**overrides):
        base = dict(
            timezone="Europe/Rome",
            ssh_port=22,
            permit_root_login="yes",
            client_alive_interval=600,
            client_alive_countmax=2,
            login_grace_time=30,
            root_password="",
            open_http_https=True,
            letsencrypt_email="",
            letsencrypt_domains="",
            webserver="apache",
            ntp_servers=["0.pool.ntp.org"],
            checkmk_admin_password="",
            checkmk_deb_url="",
            cmk_version="latest",
            site_name="monitoring",
            redirect_to_site=True,
            deploy_local_checks=True,
            enable_auto_git_sync=True,
            auto_git_sync_interval_sec=60,
            auto_git_sync_repo_url="https://github.com/nethesis/checkmk-tools.git",
            auto_git_sync_target_dir="/opt/checkmk-tools",
            smtp_relayhost="",
            smtp_relay_user="",
            smtp_relay_password="",
            smtp_from_address="",
            fail2ban_ignoreip="",
        )
        base.update(overrides)
        return InstallerConfig(**base)

    return _make
