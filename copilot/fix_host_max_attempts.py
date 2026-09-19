#!/usr/bin/env python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#
# Fix: add max_check_attempts=5 for all host checks on srv-monitoring-sp
# This prevents transient nmap misses from immediately triggering HARD DOWN notifications.
#
# Run on srv-monitoring-sp: python3 /tmp/fix_host_attempts.py; rm -f /tmp/fix_host_attempts.py

import re

RULES_MK = "/omd/sites/monitoring/etc/check_mk/conf.d/wato/rules.mk"

NEW_RULE = """
extra_host_conf.setdefault('max_check_attempts', [])

extra_host_conf['max_check_attempts'] = [
{'id': 'f1a2b3c4-d5e6-7890-abc1-d2e3f4a5b6c7', 'value': 5, 'condition': {}, 'options': {'disabled': False, 'description': 'All hosts: 5 attempts before HARD DOWN - prevents transient nmap miss flapping'}},
] + extra_host_conf['max_check_attempts']

"""

with open(RULES_MK, "r") as f:
    content = f.read()

# Check if already patched
if "f1a2b3c4-d5e6-7890-abc1-d2e3f4a5b6c7" in content:
    print("Already patched, nothing to do.")
    raise SystemExit(0)

# Insert after the extra_host_conf['notification_options'] block
anchor = "] + extra_host_conf['notification_options']"
if anchor not in content:
    print(f"ERROR: anchor not found: {anchor}")
    raise SystemExit(1)

content = content.replace(anchor, anchor + NEW_RULE, 1)

with open(RULES_MK, "w") as f:
    f.write(content)

print("OK: extra_host_conf['max_check_attempts'] = 5 added to rules.mk")
