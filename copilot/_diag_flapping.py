#!/usr/bin/env python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#
# Diagnostic script: analyze host connectivity flapping on srv-monitoring-sp
# Run via: wsl -d kali-linux python3 /mnt/c/.../copilot/_diag_flapping.py

import subprocess
import os

PROMPT = """You are a CheckMK monitoring expert. Analyze srv-monitoring-sp to diagnose host connectivity flapping (hosts going DOWN then UP every few minutes). The host uses SSH alias srv-monitoring-sp with root access via ControlMaster.

Run each step and show the full output before proceeding.

STEP 1 - OMD status:
Run: ssh srv-monitoring-sp "omd status monitoring"

STEP 2 - System health:
Run: ssh srv-monitoring-sp "uptime; free -h; df -h /"

STEP 3 - Nagios host definition for a flapping host (e.g. 192.168.32.37):
Run: ssh srv-monitoring-sp "grep -A 20 '192.168.32.37' /omd/sites/monitoring/etc/nagios/conf.d/check_mk_objects.cfg | head -30"

STEP 4 - What check command is used for hosts (look for check_host_connectivity_nmap and its arguments):
Run: ssh srv-monitoring-sp "grep -B2 -A5 'check_command.*check_host' /omd/sites/monitoring/etc/nagios/conf.d/check_mk_objects.cfg | head -60"

STEP 5 - max_check_attempts values in nagios config:
Run: ssh srv-monitoring-sp "grep 'max_check_attempts' /omd/sites/monitoring/etc/nagios/conf.d/check_mk_objects.cfg | sort -u | head -20"

STEP 6 - Check the checkcommands definition for check_host_connectivity_nmap (see if --retries is passed):
Run: ssh srv-monitoring-sp "grep -A5 'check_host_connectivity_nmap' /omd/sites/monitoring/etc/nagios/conf.d/check_mk_objects.cfg | head -40"

STEP 7 - Recent flapping notifications:
Run: ssh srv-monitoring-sp "tail -50 /omd/sites/monitoring/var/log/notify.log"

STEP 8 - Nagios log for recent HOST DOWN and HOST RECOVERY events:
Run: ssh srv-monitoring-sp "grep -E 'HOST (ALERT|RECOVERY)' /omd/sites/monitoring/var/log/nagios.log | tail -40"

After all steps, provide a detailed root cause analysis:
1. Is OMD running and healthy?
2. What check command + arguments are passed to check_host_connectivity_nmap for host checks?
3. Is --retries 2 actually visible in the nagios check command definition?
4. Is max_check_attempts=3 (or higher) set for host checks in nagios config?
5. Why are hosts going HARD CRITICAL immediately instead of using soft states first?
6. Concrete recommended fix (exact change needed in CheckMK WATO or nagios config) to stop the flapping notifications.
"""

env = dict(os.environ)
env['TERM'] = 'dumb'

subprocess.run(
    ['/home/marzio/.npm-global/bin/copilot', '-p', PROMPT, '--allow-all'],
    env=env
)
