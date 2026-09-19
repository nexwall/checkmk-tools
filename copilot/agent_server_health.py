#!/usr/bin/env python3
# agent_server_health.py
# Intelligent server health check using Copilot CLI
# Connects to a host via SSH, collects raw data, sends to Copilot CLI for AI analysis.
#
# Usage:
#   python3 agent_server_health.py [host_alias] [--save]
#   python3 agent_server_health.py ubntmarzio-root
#   python3 agent_server_health.py ubntmarzio-root --save
#
# WSL execution (from PowerShell):
#   wsl -d kali-linux bash -c "python3 /opt/checkmk-tools/copilot/agent_server_health.py ubntmarzio-root"
#
# Requirements:
#   - Copilot CLI installed: /home/marzio/.npm-global/bin/copilot
#   - SSH key configured for the target host alias in ~/.ssh/config
#   - gh auth (GitHub Copilot access)

import subprocess
import sys
import os
import json
import datetime

VERSION = "1.0.0"
COPILOT_BIN = "/home/marzio/.npm-global/bin/copilot"

# Host profiles: alias -> {description, ssh_user, collect_checkmk}
HOST_PROFILES = {
    "ubntmarzio-root": {
        "description": "Ubuntu 22.04 test host (ubntmarzio)",
        "collect_checkmk": False,
        "extra_checks": [
            "systemctl list-units --failed --no-legend 2>/dev/null | head -10",
            "journalctl -p err -n 10 --no-pager 2>/dev/null",
        ],
    },
    "checkmk-vps-01": {
        "description": "CheckMK VPS 01 - Production (monitor.nethlab.it)",
        "collect_checkmk": True,
        "extra_checks": [
            "omd status 2>/dev/null",
            "su - monitoring -c 'cmk --version 2>/dev/null'",
        ],
    },
    "checkmk-vps-02": {
        "description": "CheckMK VPS 02 - Staging (monitor01.nethlab.it)",
        "collect_checkmk": True,
        "extra_checks": [
            "omd status 2>/dev/null",
        ],
    },
    "srv-monitoring-sp": {
        "description": "Monitoring server SP (45.33.235.86:2333)",
        "collect_checkmk": True,
        "extra_checks": [
            "omd status 2>/dev/null",
            "tail -5 /omd/sites/monitoring/var/log/notify.log 2>/dev/null",
        ],
    },
}

# Base commands always collected from any host
BASE_COMMANDS = [
    "uptime",
    "free -h",
    "df -h / 2>/dev/null",
    "top -bn1 2>/dev/null | head -12",
    "ss -tlnp 2>/dev/null | head -20",
    "systemctl is-system-running 2>/dev/null || echo 'systemctl not available'",
]


def build_ssh_data_collector(host_alias, profile):
    """Build the shell command string that collects data from the remote host."""
    commands = list(BASE_COMMANDS)
    commands.extend(profile.get("extra_checks", []))

    parts = []
    for cmd in commands:
        # Wrap each command with a header separator and error silencing
        header = f"echo '=== {cmd.split()[0].upper()} ==='"
        parts.append(f"{header}; {cmd} 2>/dev/null; echo")

    full_cmd = " && ".join(parts)
    ssh_cmd = f'ssh -o ConnectTimeout=15 -o BatchMode=yes {host_alias} "{full_cmd}"'
    return ssh_cmd


def collect_raw_data(host_alias, profile):
    """Run SSH data collection directly (for embedding in prompt)."""
    ssh_cmd = build_ssh_data_collector(host_alias, profile)

    result = subprocess.run(
        ["bash", "-c", ssh_cmd],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0 and not result.stdout:
        return None, result.stderr.strip()
    return result.stdout.strip(), None


def build_copilot_prompt(host_alias, profile, raw_data):
    """Build the Copilot CLI prompt text for AI analysis."""
    desc = profile.get("description", host_alias)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    prompt = f"""You are a Linux/CheckMK server health analyst. Analyze the following raw system data collected from host "{host_alias}" ({desc}) at {now}.

RAW DATA COLLECTED VIA SSH:
---
{raw_data}
---

Provide a concise health report with this EXACT format:

HOST: {host_alias}
STATUS: OK | WARNING | CRITICAL
TIME: {now}

SUMMARY (1-2 sentences):
<brief overall status>

FINDINGS:
- <metric>: <value> - <status emoji 🟢/🟡/🔴> <brief note>
(list all key metrics: load, memory, disk, swap, failed services, listening ports)

ALERTS:
<list any WARNING or CRITICAL items, or "None" if all is OK>

RECOMMENDATIONS:
<1-3 specific actionable recommendations, or "None" if all is OK>

Keep the report short and machine-readable. Use 🟢 OK, 🟡 WARNING, 🔴 CRITICAL for status emojis.
Do NOT run any additional shell commands — analyze only the data provided above."""

    return prompt


def run_copilot_analysis(prompt, save_output=False, host_alias="host"):
    """Send the prompt to Copilot CLI for AI analysis."""
    env = os.environ.copy()
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/marzio/.npm-global/bin"
    env["TERM"] = "dumb"

    cmd = [
        COPILOT_BIN,
        "-p", prompt,
        "--allow-all",
        "--autopilot",
    ]

    output_file = None
    if save_output:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"/tmp/copilot_health_{host_alias}_{ts}.txt"

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )

    output = result.stdout
    if result.returncode != 0 and result.stderr:
        output += "\n[STDERR]: " + result.stderr

    if save_output and output_file:
        with open(output_file, "w") as f:
            f.write(output)
        print(f"[saved] Report saved to: {output_file}", file=sys.stderr)

    return output


def main():
    host_alias = "ubntmarzio-root"
    save = False

    args = sys.argv[1:]
    if args:
        host_alias = args[0]
    if "--save" in args:
        save = True

    profile = HOST_PROFILES.get(host_alias)
    if not profile:
        print(f"[agent] Unknown host alias: {host_alias}")
        print(f"[agent] Known hosts: {', '.join(HOST_PROFILES.keys())}")
        print(f"[agent] To add new hosts, edit HOST_PROFILES in this script.")
        sys.exit(1)

    print(f"[agent] Collecting data from: {host_alias} ({profile['description']})")

    raw_data, err = collect_raw_data(host_alias, profile)
    if err:
        print(f"[agent] SSH collection failed: {err}")
        sys.exit(2)

    print(f"[agent] Data collected ({len(raw_data)} chars). Sending to Copilot CLI...")

    prompt = build_copilot_prompt(host_alias, profile, raw_data)
    report = run_copilot_analysis(prompt, save_output=save, host_alias=host_alias)

    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)


main()
