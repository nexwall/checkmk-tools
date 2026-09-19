#!/usr/bin/env python3
# agent_haiku_netcheck.py — Sub-agent: Network, Services & Security Analyzer
# Model: claude-haiku-4.5 (fast, low-cost)
# Role: Collect process/service/network/security data from host, fast triage with Haiku.
# Output: JSON block (delimited) + human summary for the orchestrator (run_agents.py).
#
# Usage (standalone):
#   python3 agent_haiku_netcheck.py ubntmarzio-root [--raw]
#   python3 agent_haiku_netcheck.py srv-monitoring-sp --raw
#
# Called by run_agents.py — do not run in production without the orchestrator.

import subprocess
import sys
import os
import json
import datetime
import re

VERSION = "1.0.0"
COPILOT_BIN = "/home/marzio/.npm-global/bin/copilot"
AGENT_NAME = "haiku_netcheck"

# Infrastructure context — keep in sync with run_agents.py and agent_haiku_sysmon.py
INFRA_CONTEXT = """
INFRASTRUCTURE CONTEXT (READ-ONLY REFERENCE):
- ubntmarzio-root: Ubuntu 22.04 test host, SSH alias, user root, key ~/.ssh/copilot_ubnt
- checkmk-vps-01: CheckMK Production (monitor.nethlab.it), SSH alias, key ~/.ssh/checkmk (passphrase)
- checkmk-vps-02: CheckMK Staging (monitor01.nethlab.it), SSH alias copilot-key (no passphrase)
- srv-monitoring-sp: Monitoring SP (45.33.235.86:2333), ProxyJump via sos, key ~/.ssh/copilot_srv_monitoring
- srv-monitoring-us: Monitoring US (195.223.159.26:2333), ProxyJump via checkmk-vps-01

CHECKMK OMD:
- Site name: monitoring — path: /omd/sites/monitoring/
- Notify log: /omd/sites/monitoring/var/log/notify.log
- Livestatus socket: /omd/sites/monitoring/tmp/run/live
- All files on monitoring servers MUST be owned monitoring:monitoring

CRITICAL FORBIDDEN ACTIONS — NEVER SUGGEST THESE:
1. ENABLE_SVC_CHECK or DISABLE_SVC_CHECK on any service without explicit user confirmation
2. SCHEDULE_FORCED_SVC_CHECK on any service (breaks passive CheckMK checks permanently)
3. Disabling Check_MK or Check_MK Discovery services (causes mass stale on all hosts)
4. Writing directly to Nagios cmd pipe for passive services
For stale fix: ONLY suggest 'su - monitoring -c "cmk --check <host>"'
"""

# SSH commands for network, process, security, service checks
COLLECT_COMMANDS = [
    ("listening_ports", "ss -tlnp 2>/dev/null | awk 'NR>1 {print $4, $6}'"),
    ("established_conn", "ss -tnp state established 2>/dev/null | wc -l"),
    ("ssh_sessions", "who 2>/dev/null | head -10 || echo 'N/A'"),
    ("last_logins", "last -n 10 2>/dev/null | head -10 || echo 'N/A'"),
    ("auth_failures", "grep -c 'Failed password\\|authentication failure' /var/log/auth.log 2>/dev/null || grep -c 'Failed\\|failure' /var/log/secure 2>/dev/null || echo 'N/A'"),
    ("journal_errors", "journalctl -p err..crit -n 15 --no-pager 2>/dev/null | tail -15 || echo 'no journalctl'"),
    ("cron_jobs", "crontab -l 2>/dev/null; ls /etc/cron.d/ 2>/dev/null | head -10"),
    ("active_services", "systemctl list-units --type=service --state=running --no-legend --no-pager 2>/dev/null | wc -l || echo 'N/A'"),
    ("critical_services", "for s in ssh sshd cron crond rsyslog systemd-journald; do systemctl is-active $s 2>/dev/null && echo \"$s: active\" || echo \"$s: FAILED/not found\"; done"),
    ("suspicious_proc", "ps aux --no-header 2>/dev/null | grep -E '/tmp/|/dev/shm|cryptominer|ncat |nmap |python.*-c' | grep -v grep | head -5 || echo 'none'"),
    ("open_files_count", "lsof 2>/dev/null | wc -l || echo 'N/A'"),
    ("package_updates", "apt list --upgradable 2>/dev/null | wc -l || yum check-update --quiet 2>/dev/null | wc -l || echo 'N/A'"),
]

# Additional commands for CheckMK hosts
CHECKMK_COMMANDS = [
    ("omd_status", "omd status 2>/dev/null || echo 'omd not found'"),
    ("notify_log_tail", "tail -20 /omd/sites/monitoring/var/log/notify.log 2>/dev/null || echo 'notify log N/A'"),
    ("cmk_version", "su - monitoring -c 'cmk --version 2>/dev/null' 2>/dev/null || echo 'cmk N/A'"),
    ("omd_site_disk", "du -sh /omd/sites/monitoring/ 2>/dev/null || echo 'N/A'"),
]

# Hosts that run CheckMK OMD
CHECKMK_HOSTS = {
    "checkmk-vps-01",
    "checkmk-vps-02",
    "checkmk-vps-02-c",
    "srv-monitoring-sp",
    "srv-monitoring-us",
    "checkmk-z1-00",
    "checkmk-z1-01",
}


def collect_data(host_alias):
    """Collect network/service/security data from host via SSH."""
    results = {}
    errors = []

    commands = list(COLLECT_COMMANDS)
    if host_alias in CHECKMK_HOSTS:
        commands.extend(CHECKMK_COMMANDS)

    for name, cmd in commands:
        ssh_cmd = f'ssh -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=no {host_alias} "{cmd}" 2>&1'
        try:
            r = subprocess.run(
                ["bash", "-c", ssh_cmd],
                capture_output=True, text=True, timeout=20,
            )
            results[name] = r.stdout.strip() if r.stdout.strip() else "(empty)"
        except subprocess.TimeoutExpired:
            results[name] = "TIMEOUT"
            errors.append(f"{name}: SSH timeout")
        except Exception as e:
            results[name] = f"ERROR: {e}"
            errors.append(f"{name}: {e}")

    return results, errors


def build_raw_text(host_alias, data, errors, collected_at):
    """Build readable text block of raw data."""
    lines = [f"=== NETCHECK RAW DATA: {host_alias} at {collected_at} ==="]
    for name, val in data.items():
        lines.append(f"\n[{name.upper()}]")
        lines.append(val)
    if errors:
        lines.append("\n[COLLECTION ERRORS]")
        lines.extend(errors)
    return "\n".join(lines)


def build_haiku_prompt(host_alias, raw_text, collected_at, is_checkmk_host):
    """Build the Haiku analysis prompt."""
    checkmk_note = ""
    if is_checkmk_host:
        checkmk_note = """
CheckMK-specific checks (analyze omd_status, notify_log_tail, cmk_version):
- omd_status should show all services running
- notify_log_tail: look for ERROR, CRITICAL, repeated failures
- Report any OMD service not in 'running' state as CRITICAL"""

    return f"""You are a fast Linux network/services/security analyst. Your role is ANALYSIS ONLY — do NOT run any shell commands.

{INFRA_CONTEXT}

TARGET HOST: {host_alias}
COLLECTION TIME: {collected_at}
IS CHECKMK HOST: {is_checkmk_host}

RAW COLLECTED DATA:
---
{raw_text}
---

{checkmk_note}

Analyze the data and output EXACTLY this format — JSON block first, then summary:

===AGENT_JSON_START===
{{
  "agent": "haiku_netcheck",
  "host": "{host_alias}",
  "collected_at": "{collected_at}",
  "status": "OK|WARNING|CRITICAL",
  "network": {{
    "listening_ports_count": <number>,
    "established_connections": <number or null>,
    "critical_ports_open": ["<port:service>"],
    "suspicious_ports": ["<port:service if unexpected>"]
  }},
  "services": {{
    "active_count": <number or null>,
    "failed_critical": ["<service_name>"],
    "ssh_active": true|false,
    "omd_healthy": true|false|null
  }},
  "security": {{
    "active_ssh_sessions": <number>,
    "auth_failures_24h": <number or null>,
    "suspicious_processes": ["<process_description>"],
    "recent_logins": ["<user@ip if notable>"]
  }},
  "checkmk": {{
    "omd_status": "OK|DEGRADED|DOWN|N/A",
    "notify_errors": <number>,
    "notify_error_samples": ["<brief error excerpt>"]
  }},
  "alerts": [
    {{"severity": "WARNING|CRITICAL", "category": "network|services|security|checkmk", "finding": "<brief>"}}
  ],
  "updates_available": <number or null>,
  "collection_errors": <number>
}}
===AGENT_JSON_END===

SUMMARY: <one line: status emoji + host + key finding>

Output ONLY the JSON block and SUMMARY line. No other text."""


def run_haiku_analysis(prompt):
    """Call Copilot CLI with Haiku model."""
    env = os.environ.copy()
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/marzio/.npm-global/bin"
    env["TERM"] = "dumb"

    r = subprocess.run(
        [COPILOT_BIN, "-p", prompt, "--model", "claude-haiku-4.5",
         "--allow-all", "--autopilot"],
        capture_output=True, text=True, timeout=90, env=env,
    )
    return r.stdout + r.stderr


def extract_json(output):
    """Extract JSON block from Copilot CLI output."""
    m = re.search(r"===AGENT_JSON_START===(.*?)===AGENT_JSON_END===", output, re.DOTALL)
    if not m:
        return None, "JSON delimiters not found in output"
    try:
        data = json.loads(m.group(1).strip())
        return data, None
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"


def extract_summary(output):
    """Extract one-line summary from output."""
    m = re.search(r"SUMMARY:\s*(.+)", output)
    if m:
        return m.group(1).strip()
    return "(no summary)"


def main():
    host_alias = "ubntmarzio-root"
    raw_mode = False

    args = sys.argv[1:]
    if args:
        host_alias = args[0]
    if "--raw" in args:
        raw_mode = True

    collected_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_checkmk_host = host_alias in CHECKMK_HOSTS

    print(f"[{AGENT_NAME}] Collecting network/service data from {host_alias}...", file=sys.stderr)
    data, errors = collect_data(host_alias)

    raw_text = build_raw_text(host_alias, data, errors, collected_at)

    if raw_mode:
        print(raw_text)
        return

    print(f"[{AGENT_NAME}] Sending to Haiku for triage...", file=sys.stderr)
    prompt = build_haiku_prompt(host_alias, raw_text, collected_at, is_checkmk_host)
    output = run_haiku_analysis(prompt)

    report_json, err = extract_json(output)
    summary = extract_summary(output)

    if err:
        print(f"[{AGENT_NAME}] WARNING: {err}", file=sys.stderr)
        report_json = {
            "agent": AGENT_NAME,
            "host": host_alias,
            "collected_at": collected_at,
            "status": "UNKNOWN",
            "parse_error": err,
            "raw_output_excerpt": output[:500],
        }

    print(json.dumps(report_json, indent=2))
    print(f"[{AGENT_NAME}] {summary}", file=sys.stderr)


main()
