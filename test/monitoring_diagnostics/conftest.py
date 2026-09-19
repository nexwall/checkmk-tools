"""Shared pytest setup for checkmk-periodic-discovery-autoapply.py tests.

The script lives in the repo itself (script-tools/full/monitoring_diagnostics),
not in /usr/local/bin, and has no third-party dependencies - so it's loaded
directly via importlib from its actual path, no stubbing needed.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "script-tools"
    / "full"
    / "monitoring_diagnostics"
    / "checkmk-periodic-discovery-autoapply.py"
)


@pytest.fixture()
def autoapply_module():
    spec = importlib.util.spec_from_file_location(
        "checkmk_periodic_discovery_autoapply", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
