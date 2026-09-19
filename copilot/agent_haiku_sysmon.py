#!/usr/bin/env python3
# agent_haiku_sysmon.py — Sub-agent: System Metrics Collector + Fast Analyzer
# Model: claude-haiku-4.5 (fast, low-cost)
# Role: Collect raw system metrics from a host via SSH, then use Haiku for quick triage.
# Output: JSON block (delimited) + human summary for the orchestrator (run_agents.py).
#
# Usage (standalone):
#   python3 agent_haiku_sysmon.py ubntmarzio-root [--raw]
#   python3 agent_haiku_sysmon.py checkmk-vps-02 --raw
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
AGENT_NAME = "haiku_sysmon"

# Infrastructure context embedded in each prompt — keep in sync with run_agents.py
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

# SSH commands to collect system metrics
COLLECT_COMMANDS = [
    ("uptime", "uptime"),
    ("loadavg", "cat /proc/loadavg"),
    ("memory", "free -h"),
    ("disk", "df -h --output=target,size,used,avail,pcent 2>/dev/null | head -20"),
    ("swap", "swapon --show 2>/dev/null || echo 'no swap'"),
    ("cpu_count", "nproc"),
    ("failed_units", "systemctl list-units --failed --no-legend --no-pager 2>/dev/null | head -10 || echo 'systemctl N/A'"),
    ("system_state", "systemctl is-system-running 2>/dev/null || echo 'unknown'"),
    ("top_cpu", "ps aux --no-header --sort=-%cpu 2>/dev/null | head -5 | awk '{print $1,$2,$3,$4,$11}'"),
    ("top_mem", "ps aux --no-header --sort=-%mem 2>/dev/null | head -5 | awk '{print $1,$2,$3,$4,$11}'"),
    ("last_boots", "last reboot 2>/dev/null | head -3 || echo 'N/A'"),
    ("dmesg_errors", "dmesg -l err,crit --time-format reltime 2>/dev/null | tail -5 || echo 'no dmesg errors'"),
]


def collect_metrics(host_alias):
    """Collect all system metrics from the host via SSH."""
    results = {}
    errors = []

    for name, cmd in COLLECT_COMMANDS:
        ssh_cmd = f'ssh -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=no {host_alias} "{cmd}" 2>&1'
        try:
            r = subprocess.run(
                ["bash", "-c", ssh_cmd],
                capture_output=True, text=True, timeout=15,
            )
            results[name] = r.stdout.strip() if r.stdout.strip() else r.stderr.strip()
        except subprocess.TimeoutExpired:
            results[name] = "TIMEOUT"
            errors.append(f"{name}: SSH timeout")
        except Exception as e:
            results[name] = f"ERROR: {e}"
            errors.append(f"{name}: {e}")

    return results, errors


def build_raw_text(host_alias, metrics, errors, collected_at):
    """Build a readable text block of raw metrics."""
    lines = [f"=== SYSMON RAW DATA: {host_alias} at {collected_at} ==="]
    for name, val in metrics.items():
        lines.append(f"\n[{name.upper()}]")
        lines.append(val)
    if errors:
        lines.append("\n[COLLECTION ERRORS]")
        lines.extend(errors)
    return "\n".join(lines)


def build_haiku_prompt(host_alias, raw_text, collected_at):
    """Build the Haiku analysis prompt."""
    return f"""You are a fast Linux system health analyzer. Your role is ANALYSIS ONLY — you must NOT run any shell commands.

{INFRA_CONTEXT}

TARGET HOST: {host_alias}
COLLECTION TIME: {collected_at}

RAW SYSTEM METRICS:
---
{raw_text}
---

Analyze the data and output EXACTLY this format — first the JSON block (machine-readable), then a one-line summary:

===AGENT_JSON_START===
{{
  "agent": "haiku_sysmon",
  "host": "{host_alias}",
  "collected_at": "{collected_at}",
  "status": "OK|WARNING|CRITICAL",
  "metrics": {{
    "uptime_days": <number or null>,
    "load_1m": <float or null>,
    "load_5m": <float or null>,
    "load_15m": <float or null>,
    "cpu_count": <number or null>,
    "mem_total_gb": <float or null>,
    "mem_used_gb": <float or null>,
    "mem_used_pct": <float or null>,
    "swap_used_pct": <float or null>,
    "disk_root_used_pct": <float or null>,
    "failed_units_count": <number>,
    "system_state": "<string>"
  }},
  "alerts": [
    {{"severity": "WARNING|CRITICAL", "metric": "<name>", "value": "<val>", "reason": "<brief>"}}
  ],
  "top_cpu_process": "<name or null>",
  "top_mem_process": "<name or null>",
  "collection_errors": <number>
}}
===AGENT_JSON_END===

SUMMARY: <one line: overall status emoji + host + key finding>

Thresholds: load > cpu_count = WARNING, load > 2*cpu_count = CRITICAL; mem > 85% = WARNING, > 95% = CRITICAL; disk > 80% = WARNING, > 90% = CRITICAL; any failed unit = WARNING; swap > 50% = WARNING.
Output ONLY the JSON block and the SUMMARY line. No other text."""


def run_haiku_analysis(prompt):
    """Call Copilot CLI with Haiku model for fast analysis."""
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
    """Extract one-line summary from Copilot output."""
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

    print(f"[{AGENT_NAME}] Collecting system metrics from {host_alias}...", file=sys.stderr)
    metrics, errors = collect_metrics(host_alias)

    raw_text = build_raw_text(host_alias, metrics, errors, collected_at)

    if raw_mode:
        print(raw_text)
        return

    print(f"[{AGENT_NAME}] Sending to Haiku for triage...", file=sys.stderr)
    prompt = build_haiku_prompt(host_alias, raw_text, collected_at)
    output = run_haiku_analysis(prompt)

    report_json, err = extract_json(output)
    summary = extract_summary(output)

    if err:
        print(f"[{AGENT_NAME}] WARNING: {err}", file=sys.stderr)
        # Build minimal fallback JSON
        report_json = {
            "agent": AGENT_NAME,
            "host": host_alias,
            "collected_at": collected_at,
            "status": "UNKNOWN",
            "parse_error": err,
            "raw_output_excerpt": output[:500],
        }

    # Print JSON to stdout (for orchestrator to capture)
    print(json.dumps(report_json, indent=2))
    print(f"[{AGENT_NAME}] {summary}", file=sys.stderr)


main()
