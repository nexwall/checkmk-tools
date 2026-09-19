"""Tests for checkmk-periodic-discovery-autoapply.py.

Covers only the pure logic (locating the rule line, reading/patching its
scalar fields, diffing against the target) using sample rules.mk lines
shaped like the real ones found on srv-monitoring-sp/us and checkmk-vps-01
(ids/descriptions genericized). The I/O half (su/backup/cmk -O) needs a
real OMD site and is intentionally not exercised here.
"""

import pytest

# Mirrors the pre-2026-08-03 state on srv-monitoring-sp / checkmk-vps-01:
# add/remove/interval already correct, activation still False (mode as int tuple).
NONCOMPLIANT_ACTIVATION_LINE = (
    "{'id': 'aaaaaaaa-0000-0000-0000-000000000001', 'value': {'check_interval': 120.0, "
    "'severity_unmonitored': 1, 'severity_vanished': 0, 'inventory_rediscovery': "
    "{'mode': (0, {'update_host_labels': False, 'add_new_services': True, "
    "'remove_vanished_services': True, 'update_changed_service_labels': False, "
    "'update_changed_service_parameters': False}), 'keep_clustered_vanished_services': True, "
    "'group_time': 900, 'excluded_time': [], 'activation': False}}, 'condition': {}, "
    "'options': {'disabled': False, 'description': 'Perform every two hours a service discovery'}},"
)

# Same rule after the activation fix - fully compliant.
COMPLIANT_LINE = NONCOMPLIANT_ACTIVATION_LINE.replace("'activation': False", "'activation': True")

# Mirrors srv-monitoring-us: mode as a 'custom' string tuple instead of an int,
# but already fully compliant on all four scalar fields.
CUSTOM_MODE_COMPLIANT_LINE = (
    "{'id': 'aaaaaaaa-0000-0000-0000-000000000002', 'value': {'check_interval': 120.0, "
    "'severity_unmonitored': 1, 'severity_vanished': 0, 'inventory_rediscovery': "
    "{'mode': ('custom', {'add_new_services': True, 'remove_vanished_services': True, "
    "'update_changed_service_labels': False, 'update_changed_service_parameters': False, "
    "'update_host_labels': True}), 'keep_clustered_vanished_services': True, 'group_time': 900, "
    "'excluded_time': [], 'activation': True}}, 'condition': {}, "
    "'options': {'disabled': False, 'description': 'Perform every two hours a service discovery'}},"
)

OTHER_RULESET_LINE = (
    "{'id': 'bbbbbbbb-0000-0000-0000-000000000000', 'value': 30, 'condition': {}, "
    "'options': {'disabled': False, 'description': 'Some unrelated ruleset'}},"
)

PROXMOX_SUBFOLDER_LINE = (
    "{'id': 'cccccccc-0000-0000-0000-000000000000', 'value': {'check_interval': 5.0, "
    "'inventory_rediscovery': {'mode': (0, {'add_new_services': True, "
    "'remove_vanished_services': True}), 'activation': False}}, "
    "'condition': {'host_folder': '/proxmox'}, 'options': {'disabled': False}},"
)


def _wrap(*rule_lines: str) -> str:
    return "periodic_discovery = [\n" + "\n".join(rule_lines) + "\n] + periodic_discovery\n"


# --- find_target_rule_line ---------------------------------------------------

def test_find_target_rule_line_locates_root_folder_rule(autoapply_module):
    content = _wrap(OTHER_RULESET_LINE, NONCOMPLIANT_ACTIVATION_LINE)
    idx, line = autoapply_module.find_target_rule_line(content)
    assert line == NONCOMPLIANT_ACTIVATION_LINE
    assert content.splitlines()[idx] == NONCOMPLIANT_ACTIVATION_LINE


def test_find_target_rule_line_ignores_subfolder_scoped_rule(autoapply_module):
    # PROXMOX_SUBFOLDER_LINE has inventory_rediscovery but condition is not {}
    content = _wrap(PROXMOX_SUBFOLDER_LINE, COMPLIANT_LINE)
    idx, line = autoapply_module.find_target_rule_line(content)
    assert line == COMPLIANT_LINE


def test_find_target_rule_line_raises_when_missing(autoapply_module):
    content = _wrap(OTHER_RULESET_LINE, PROXMOX_SUBFOLDER_LINE)
    with pytest.raises(autoapply_module.RuleNotFoundError):
        autoapply_module.find_target_rule_line(content)


def test_find_target_rule_line_raises_when_ambiguous(autoapply_module):
    content = _wrap(NONCOMPLIANT_ACTIVATION_LINE, COMPLIANT_LINE)
    with pytest.raises(autoapply_module.RuleNotFoundError):
        autoapply_module.find_target_rule_line(content)


# --- read_current_values ------------------------------------------------------

def test_read_current_values_noncompliant(autoapply_module):
    values = autoapply_module.read_current_values(NONCOMPLIANT_ACTIVATION_LINE)
    assert values == {
        "check_interval": "120.0",
        "add_new_services": "True",
        "remove_vanished_services": "True",
        "activation": "False",
    }


def test_read_current_values_custom_mode(autoapply_module):
    values = autoapply_module.read_current_values(CUSTOM_MODE_COMPLIANT_LINE)
    assert values["activation"] == "True"
    assert values["add_new_services"] == "True"


# --- compute_diff --------------------------------------------------------------

def test_compute_diff_empty_when_compliant(autoapply_module):
    current = autoapply_module.read_current_values(COMPLIANT_LINE)
    assert autoapply_module.compute_diff(current, autoapply_module.TARGET) == {}


def test_compute_diff_flags_activation_only(autoapply_module):
    current = autoapply_module.read_current_values(NONCOMPLIANT_ACTIVATION_LINE)
    diff = autoapply_module.compute_diff(current, autoapply_module.TARGET)
    assert diff == {"activation": ("False", "True")}


def test_compute_diff_custom_mode_is_compliant(autoapply_module):
    current = autoapply_module.read_current_values(CUSTOM_MODE_COMPLIANT_LINE)
    assert autoapply_module.compute_diff(current, autoapply_module.TARGET) == {}


# --- patch_field / apply_patches -----------------------------------------------

def test_patch_field_replaces_single_occurrence(autoapply_module):
    patched = autoapply_module.patch_field(NONCOMPLIANT_ACTIVATION_LINE, "activation", "True")
    assert "'activation': True" in patched
    assert "'activation': False" not in patched


def test_patch_field_leaves_other_fields_untouched(autoapply_module):
    patched = autoapply_module.patch_field(NONCOMPLIANT_ACTIVATION_LINE, "activation", "True")
    assert "'update_host_labels': False" in patched
    assert "'check_interval': 120.0" in patched


def test_patch_field_raises_when_key_absent(autoapply_module):
    with pytest.raises(autoapply_module.RuleNotFoundError):
        autoapply_module.patch_field(NONCOMPLIANT_ACTIVATION_LINE, "not_a_real_key", "True")


def test_apply_patches_produces_fully_compliant_line(autoapply_module):
    current = autoapply_module.read_current_values(NONCOMPLIANT_ACTIVATION_LINE)
    diff = autoapply_module.compute_diff(current, autoapply_module.TARGET)
    patched = autoapply_module.apply_patches(NONCOMPLIANT_ACTIVATION_LINE, diff)
    assert patched == COMPLIANT_LINE
    assert autoapply_module.compute_diff(
        autoapply_module.read_current_values(patched), autoapply_module.TARGET
    ) == {}


def test_apply_patches_is_noop_for_empty_diff(autoapply_module):
    patched = autoapply_module.apply_patches(COMPLIANT_LINE, {})
    assert patched == COMPLIANT_LINE
