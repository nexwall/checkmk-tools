#!/usr/bin/env python3
# run_agents.py — Multi-Agent Orchestrator: CheckMK/Linux Infrastructure Monitor
#
# Architecture:
#   Agent 1: agent_haiku_sysmon.py   — claude-haiku-4.5  — system metrics (CPU, RAM, disk)
#   Agent 2: agent_haiku_netcheck.py — claude-haiku-4.5  — network, services, security
#   Agent 3: Opus Analyst (inline)   — claude-opus-4.8 high — deep analysis + action plan
#
# The two Haiku agents run in PARALLEL, then Sonnet receives both reports for deep analysis.
# Sonnet has full operational context: SSH access, CheckMK rules, forbidden actions, emergency procedures.
#
# Usage:
#   python3 copilot/run_agents.py [host_alias] [options]
#   python3 copilot/run_agents.py ubntmarzio-root
#   python3 copilot/run_agents.py checkmk-vps-02-c --loop 5 --interval 300
#   python3 copilot/run_agents.py srv-monitoring-sp --save
#   python3 copilot/run_agents.py --hosts checkmk-vps-01,checkmk-vps-02-c,srv-monitoring-sp
#   python3 copilot/run_agents.py --all
#
# Options:
#   --hosts h1,h2,h3   Run on multiple hosts (comma-separated), sequential
#   --all              Run on ALL configured hosts (see ALL_HOSTS list below)
#   --loop N           Run N times per host (0 = infinite loop), default: 1
#   --interval S       Seconds between loops (default: 300 = 5 min)
#   --save             Save Sonnet report to /tmp/agent_report_<host>_<ts>.txt
#   --dry-run          Collect data only, skip AI analysis (for debugging)
#
# WSL execution (from PowerShell):
#   wsl -d kali-linux bash -c "python3 /mnt/c/Users/.../copilot/run_agents.py --all"

import subprocess
import sys
import os
import json
import datetime
import time
import re

VERSION = "1.1.0"
COPILOT_BIN = "/home/marzio/.npm-global/bin/copilot"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# All known hosts with SSH key access — used by --all flag.
# Each entry: (alias, description)
# Hosts requiring ControlMaster passphrase (vps-01, vps-02) need the socket active first.
ALL_HOSTS = [
    # VPS / public servers — autonomous SSH key (no passphrase)
    ("checkmk-vps-02-c",    "CheckMK Staging VPS (monitor01.nethlab.it) — no passphrase"),
    ("srv-monitoring-sp",   "CheckMK SP production (45.33.235.86 via sos ProxyJump)"),
    ("ubntmarzio-root",     "Ubuntu 22.04 lab host (10.155.100.108)"),
    # VPS with passphrase — require ControlMaster active
    ("checkmk-vps-01",      "CheckMK Production VPS (monitor.nethlab.it) — needs ControlMaster"),
    # LAN hosts
    ("nsec8-stable",        "NethSecurity 8 stable lab (10.155.100.100)"),
    ("nsec8-test",          "NethSecurity 8.8.0-dev lab (192.168.10.167)"),
    ("rl94ns8",             "NethServer 8 lab (10.155.100.40)"),
    ("rl94ns81",            "NethServer 8 lab webtop (10.155.100.41)"),
    ("checkmk-z1-00",       "CheckMK local (192.168.10.128)"),
    ("checkmk-z1-01",       "CheckMK local (192.168.10.126)"),
    ("redteam-shell",       "Redteam shell (redteam.security.nethesis.it) — via sos ProxyJump"),
]

# Full operational context for Sonnet High (complete, authoritative)
SONNET_FULL_CONTEXT = """
=== INFRASTRUCTURE CONTEXT ===

HOSTS — SSH ACCESS:
  ubntmarzio-root:
    - Role: Ubuntu 22.04 test/lab host
    - SSH: alias configured in ~/.ssh/config, key ~/.ssh/copilot_ubnt (ed25519, no passphrase)
    - IP: 10.155.100.108:22, user root
    - System: Ubuntu 22.04 LTS, x86_64

  checkmk-vps-01:
    - Role: CheckMK PRODUCTION (monitor.nethlab.it)
    - SSH: alias checkmk-vps-01, key ~/.ssh/checkmk (ed25519, PASSPHRASE required)
    - ControlMaster active 30min after first connection
    - OMD site: monitoring at /omd/sites/monitoring/

  checkmk-vps-02 / checkmk-vps-02-c:
    - Role: CheckMK STAGING/TEST (monitor01.nethlab.it)
    - SSH: alias checkmk-vps-02-c, key ~/.ssh/copilot_checkmk_vps02 (NO passphrase) — autonomous
    - OMD site: monitoring at /omd/sites/monitoring/
    - Use for all test operations before touching vps-01

  srv-monitoring-sp:
    - Role: Primary monitoring server for SP infrastructure
    - SSH: alias srv-monitoring-sp, key ~/.ssh/copilot_srv_monitoring (NO passphrase)
    - MANDATORY: ProxyJump via 'sos' (configured in WSL ~/.ssh/config)
    - OMD site: monitoring at /omd/sites/monitoring/
    - Notify log: /omd/sites/monitoring/var/log/notify.log
    - Livestatus socket: /omd/sites/monitoring/tmp/run/live
    - CRITICAL: ALL files must be owned monitoring:monitoring (including backups)
    - Repo: /opt/checkmk-tools/ (manual git pull, no auto-sync)

  srv-monitoring-us:
    - Role: Monitoring server for US infrastructure
    - SSH: 'ssh -J checkmk-vps-01 -p 2333 -i ~/.ssh/copilot_monitoring_us_root root@195.223.159.26'
    - Key: ~/.ssh/copilot_monitoring_us_root (ed25519, NO passphrase) — autonomous
    - OMD site: monitoring at /omd/sites/monitoring/

=== CHECKMK OMD OPERATIONAL RULES ===

SITE MANAGEMENT:
  - Site name: monitoring
  - Start/stop: 'omd start|stop|restart monitoring'
  - Status: 'omd status monitoring'
  - Commands always as monitoring user: 'su - monitoring -c "command"'
  - Do NOT use sudo on srv-monitoring-sp (already root)

DIAGNOSTICS (SAFE — always allowed):
  - omd status monitoring
  - su - monitoring -c "cmk --version"
  - tail -50 /omd/sites/monitoring/var/log/notify.log
  - journalctl -p err -n 20 --no-pager
  - systemctl list-units --failed --no-legend
  - ss -tlnp (listening ports check)
  - free -h && df -h (resources)

RECOVERY COMMANDS (SAFE — use for stale/stuck checks):
  - su - monitoring -c "cmk --check <hostname>"         # force single host check
  - su - monitoring -c "cmk -O"                         # reload core config
  - su - monitoring -c "cmk -R"                         # full config reload

EMERGENCY SCRIPTS (in /opt/checkmk-tools/copilot/ or run via base64):
  - fix_reenable_checkmk_all.py  → Re-enable Check_MK on all hosts + force cmk --check (post mass-stale)
  - fix_enable_checkmk_core.py   → Enable Check_MK check on all hosts (fix stale)
  - _diag_now.py                 → Quick snapshot: stale/pending/CRIT counts
  - _diag_full.py                → Full service + Check_MK state diagnosis
  - _diag_staleness.py           → Staleness analysis with configurable thresholds

=== ABSOLUTE FORBIDDEN ACTIONS — NEVER SUGGEST OR EXECUTE ===

1. ENABLE_SVC_CHECK / DISABLE_SVC_CHECK on ANY service
   → Reason: requires explicit user confirmation every time
   → Exception: ONLY if user explicitly says "enable/disable <service> check on <host>"

2. SCHEDULE_FORCED_SVC_CHECK on ANY service
   → Reason: causes "ERROR - active check on passive service" on all SNMP/local checks
   → This breaks check state for interfaces, CPU switch, all NethSecurity local checks
   → The script force-reschedule-checks.py --all is FORBIDDEN for this reason

3. Disable Check_MK or Check_MK Discovery services
   → Reason: causes MASS STALE on all dependent services (400+ services go grey)
   → These two services are the heartbeat of the entire monitoring system

4. Write directly to Nagios cmd pipe for passive services
   → Reason: bypasses CheckMK state machine, causes inconsistencies

5. Hardcode IPs, passwords, tokens, credentials in any file

=== CONTEXT: KNOWN INCIDENTS (for pattern recognition) ===

INCIDENT 2026-03-20 — Mass Stale (Check_MK disabled on all hosts):
  - Cause: disable_active_checks.py accidentally disabled Check_MK service on all hosts
  - Symptom: all services stale > 1.5, 400+ grey rombi, cmk --check works but not scheduled
  - Fix: fix_reenable_checkmk_all.py → ENABLE_SVC_CHECK on Check_MK only + cmk --check per host
  - Key lesson: NEVER disable Check_MK or Check_MK Discovery

INCIDENT 2026-03-23 — Active check on passive services:
  - Cause: ENABLE_SVC_CHECK sent to all services (including SNMP interfaces, NethSecurity checks)
  - Symptom: hundreds of "ERROR - you did an active check on this service"
  - Fix: full site restore from backup
  - Key lesson: SCHEDULE_FORCED_SVC_CHECK is FORBIDDEN on passive services

=== SAFE LIVESTATUS QUERY PATTERN ===

For querying CheckMK via Livestatus (only on srv-monitoring-sp):
```python
import socket
def livestatus(query):
    s = socket.socket(socket.AF_UNIX)
    s.connect('/omd/sites/monitoring/tmp/run/live')
    s.send((query + '\\n').encode())
    s.shutdown(socket.SHUT_WR)   # MANDATORY: without this, returns empty
    return s.makefile().read().strip()
```
Always use send() + shutdown(SHUT_WR) — never sendall() without shutdown.
Run this script as monitoring user: su - monitoring -c "python3 /tmp/script.py"
"""

# Expected JSON output structure for Sonnet's final report
SONNET_OUTPUT_FORMAT = """
===SONNET_REPORT_START===
OVERALL_STATUS: OK|WARNING|CRITICAL|UNKNOWN
SEVERITY_SCORE: 0-10 (0=perfect, 10=complete outage)
HOST: <host_alias>
TIMESTAMP: <ISO timestamp>

EXECUTIVE_SUMMARY:
<2-3 sentences describing the overall health and the most important finding>

CORRELATED_FINDINGS:
- [SYSMON + NETCHECK] <finding that appears in both reports, if any>
- [SYSMON only] <system-level finding>
- [NETCHECK only] <network/service/security finding>
<add as many as needed, mark with appropriate agent tag>

ROOT_CAUSE_ANALYSIS:
<If status is WARNING or CRITICAL: detailed root cause. If OK: "No issues detected.">

RECOMMENDED_ACTIONS:
- [RISK: LOW] <action description>
  Safe to execute: `<exact command>`
- [RISK: MEDIUM] <action description>
  Requires confirmation before executing: `<exact command>`
- [RISK: HIGH] <action requiring explicit user approval>
  DO NOT execute without user confirmation: `<reason>`
<If no actions needed: "No actions required — system is healthy.">

MONITORING_NOTES:
<Patterns to watch, metrics approaching thresholds, suggestions for monitoring improvements>

CHECKMK_SPECIFIC: <Only if host is a CheckMK server — OMD health, notify issues, stale counts>
===SONNET_REPORT_END===
"""


def run_copilot_env():
    """Return clean environment for Copilot CLI execution."""
    env = os.environ.copy()
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/marzio/.npm-global/bin"
    env["TERM"] = "dumb"
    return env


def run_haiku_agent(script_name, host_alias):
    """
    Run a Haiku sub-agent script and return its parsed JSON output.
    Returns (json_data, stderr_log) tuple.
    """
    script_path = os.path.join(SCRIPT_DIR, script_name)
    try:
        r = subprocess.run(
            ["python3", script_path, host_alias],
            capture_output=True, text=True, timeout=120,
            env=run_copilot_env(),
        )
        stderr_log = r.stderr.strip()
        stdout = r.stdout.strip()

        # Try to parse JSON from stdout
        try:
            data = json.loads(stdout)
            return data, stderr_log
        except json.JSONDecodeError:
            # Fallback: try to extract JSON if mixed with other output
            try:
                # Find first { to last }
                start = stdout.index("{")
                end = stdout.rindex("}") + 1
                data = json.loads(stdout[start:end])
                return data, stderr_log
            except (ValueError, json.JSONDecodeError):
                return {"agent": script_name, "status": "PARSE_ERROR", "raw": stdout[:300]}, stderr_log

    except subprocess.TimeoutExpired:
        return {"agent": script_name, "status": "TIMEOUT"}, f"{script_name}: timed out after 120s"
    except Exception as e:
        return {"agent": script_name, "status": "ERROR", "error": str(e)}, str(e)


def build_sonnet_prompt(host_alias, sysmon_data, netcheck_data, collected_at):
    """Build the full prompt for the Sonnet High analyst."""
    sysmon_json = json.dumps(sysmon_data, indent=2)
    netcheck_json = json.dumps(netcheck_data, indent=2)

    return f"""You are a senior infrastructure analyst specializing in Linux systems and CheckMK monitoring.
You have full operational authority to diagnose issues and propose remediation.
You must follow ALL rules in the context below — especially the FORBIDDEN ACTIONS section.

{SONNET_FULL_CONTEXT}

=== ANALYSIS REQUEST ===

TARGET HOST: {host_alias}
ANALYSIS TIME: {collected_at}

You received these two concurrent reports from the Haiku monitoring sub-agents:

--- HAIKU SYSMON AGENT REPORT ---
{sysmon_json}

--- HAIKU NETCHECK AGENT REPORT ---
{netcheck_json}

=== YOUR TASK ===

1. Correlate findings from both agents — look for patterns that appear in multiple reports
2. Perform deep root cause analysis for any WARNING or CRITICAL findings
3. Rate overall severity on 0-10 scale
4. Propose specific actions with exact commands where appropriate
5. Flag any patterns that match known incidents (listed in context above)
6. For CheckMK hosts: specifically evaluate monitoring health

IMPORTANT RULES FOR YOUR RESPONSE:
- Do NOT suggest forbidden actions (ENABLE_SVC_CHECK, SCHEDULE_FORCED_SVC_CHECK, disabling Check_MK)
- Mark any action with risk level: LOW (safe to run immediately), MEDIUM (confirm first), HIGH (user must explicitly approve)
- If you see stale services: suggest only 'cmk --check <host>' and the emergency scripts listed above
- If auth_failures > 100: flag as security concern (but do NOT suggest blocking IPs autonomously)

{SONNET_OUTPUT_FORMAT}

Fill out the report format above. Be specific, actionable, and concise. No padding."""


def run_sonnet_analyst(prompt, host_alias, save_output):
    """Call Copilot CLI with Sonnet High for deep analysis."""
    env = run_copilot_env()

    r = subprocess.run(
        [COPILOT_BIN, "-p", prompt,
         "--model", "claude-opus-4.8",
         "--reasoning-effort", "high",
         "--allow-all", "--autopilot"],
        capture_output=True, text=True, timeout=180, env=env,
    )
    output = r.stdout + r.stderr

    if save_output:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = f"/tmp/agent_report_{host_alias}_{ts}.txt"
        with open(path, "w") as f:
            f.write(output)
        print(f"[orchestrator] Report saved to: {path}", file=sys.stderr)

    return output


def extract_sonnet_report(output):
    """Extract the formatted report from Sonnet output."""
    m = re.search(r"===SONNET_REPORT_START===(.*?)===SONNET_REPORT_END===", output, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Fallback: return the whole output minus usage stats
    clean = re.sub(r"Total usage est:.*", "", output, flags=re.DOTALL)
    return clean.strip()


def print_header(host_alias, iteration, total):
    """Print a clear section header."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    loop_info = f" (run {iteration}/{total if total else 'inf'})" if total != 1 else ""
    print(f"\n{'='*70}")
    print(f"  CHECKMK AGENT MONITOR — {host_alias}{loop_info}")
    print(f"  {ts}")
    print(f"{'='*70}")


def run_once(host_alias, save_output, dry_run):
    """Execute one full monitoring cycle."""
    collected_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n[orchestrator] Starting parallel Haiku agents for: {host_alias}")

    # Start both Haiku agents IN PARALLEL using Popen
    env = run_copilot_env()
    sysmon_path = os.path.join(SCRIPT_DIR, "agent_haiku_sysmon.py")
    netcheck_path = os.path.join(SCRIPT_DIR, "agent_haiku_netcheck.py")

    # In dry-run mode: skip Haiku AI — collect raw SSH data only
    haiku_args = [host_alias, "--raw"] if dry_run else [host_alias]

    print(f"[orchestrator] → Haiku-1 (sysmon) starting...", file=sys.stderr)
    proc_sysmon = subprocess.Popen(
        ["python3", sysmon_path] + haiku_args,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )

    print(f"[orchestrator] → Haiku-2 (netcheck) starting...", file=sys.stderr)
    proc_netcheck = subprocess.Popen(
        ["python3", netcheck_path] + haiku_args,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )

    # Wait for both to complete (max 120s each)
    try:
        sysmon_out, sysmon_err = proc_sysmon.communicate(timeout=120)
        print(f"[haiku_sysmon] {sysmon_err.strip().splitlines()[-1] if sysmon_err.strip() else 'done'}", file=sys.stderr)
    except subprocess.TimeoutExpired:
        proc_sysmon.kill()
        sysmon_out, sysmon_err = "", "TIMEOUT"

    try:
        netcheck_out, netcheck_err = proc_netcheck.communicate(timeout=120)
        print(f"[haiku_netcheck] {netcheck_err.strip().splitlines()[-1] if netcheck_err.strip() else 'done'}", file=sys.stderr)
    except subprocess.TimeoutExpired:
        proc_netcheck.kill()
        netcheck_out, netcheck_err = "", "TIMEOUT"

    # Parse Haiku outputs
    def parse_agent_json(raw, agent_name):
        try:
            return json.loads(raw.strip())
        except json.JSONDecodeError:
            try:
                start = raw.index("{")
                end = raw.rindex("}") + 1
                return json.loads(raw[start:end])
            except (ValueError, json.JSONDecodeError):
                return {"agent": agent_name, "status": "PARSE_ERROR", "raw": raw[:200]}

    sysmon_data = parse_agent_json(sysmon_out, "haiku_sysmon")
    netcheck_data = parse_agent_json(netcheck_out, "haiku_netcheck")

    # Show quick Haiku status
    s1 = sysmon_data.get("status", "?")
    s2 = netcheck_data.get("status", "?")
    print(f"\n[orchestrator] Haiku-1 sysmon:   [{s1}]")
    print(f"[orchestrator] Haiku-2 netcheck: [{s2}]")

    if dry_run:
        print("\n[orchestrator] --dry-run: showing raw SSH data only (no AI analysis)")
        print("\n=== SYSMON RAW DATA ===")
        print(sysmon_out if sysmon_out.strip() else "(empty)")
        print("\n=== NETCHECK RAW DATA ===")
        print(netcheck_out if netcheck_out.strip() else "(empty)")
        return

    # Determine if Sonnet is needed based on Haiku findings
    any_warning = s1 in ("WARNING", "CRITICAL", "UNKNOWN", "PARSE_ERROR") or \
                  s2 in ("WARNING", "CRITICAL", "UNKNOWN", "PARSE_ERROR")
    all_ok = s1 == "OK" and s2 == "OK"

    if all_ok:
        print(f"\n[orchestrator] Both Haiku agents report OK — running Opus for brief confirmation...")
    else:
        print(f"\n[orchestrator] Issues detected — invoking Opus High for deep analysis...")

    prompt = build_sonnet_prompt(host_alias, sysmon_data, netcheck_data, collected_at)
    sonnet_output = run_sonnet_analyst(prompt, host_alias, save_output)
    report = extract_sonnet_report(sonnet_output)

    print(f"\n{'─'*70}")
    print(report)
    print(f"{'─'*70}\n")


def main():
    host_alias = None
    host_list = []
    loop_count = 1
    interval = 300
    save_output = False
    dry_run = False

    args = sys.argv[1:]

    # First positional arg (not starting with --) = single host
    if args and not args[0].startswith("--"):
        host_alias = args[0]
        args = args[1:]

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--loop" and i + 1 < len(args):
            loop_count = int(args[i + 1])
            i += 2
        elif a == "--interval" and i + 1 < len(args):
            interval = int(args[i + 1])
            i += 2
        elif a == "--save":
            save_output = True
            i += 1
        elif a == "--dry-run":
            dry_run = True
            i += 1
        elif a == "--all":
            host_list = [h for h, _ in ALL_HOSTS]
            i += 1
        elif a == "--hosts" and i + 1 < len(args):
            host_list = [h.strip() for h in args[i + 1].split(",") if h.strip()]
            i += 2
        else:
            i += 1

    # Resolve final host list
    if host_list:
        targets = host_list
    elif host_alias:
        targets = [host_alias]
    else:
        targets = ["ubntmarzio-root"]

    # Resolve loop count: 0 = infinite
    max_iterations = loop_count if loop_count > 0 else None

    # Print known hosts table if --all or --hosts
    if len(targets) > 1:
        print(f"\n[orchestrator] v{VERSION} — multi-host mode ({len(targets)} hosts)")
        for t in targets:
            desc = next((d for h, d in ALL_HOSTS if h == t), "")
            print(f"  • {t:<30} {desc}")
        print()
    else:
        print(f"[orchestrator] v{VERSION} — target: {targets[0]}")

    print(f"[orchestrator] agents: Haiku-sysmon + Haiku-netcheck + Opus-high")
    print(f"[orchestrator] loop: {loop_count} ({'infinite' if loop_count == 0 else loop_count}x)"
          f" | interval: {interval}s | save: {save_output} | dry-run: {dry_run}")

    iteration = 1
    while True:
        for target in targets:
            print_header(target, iteration, max_iterations)
            run_once(target, save_output, dry_run)

        if max_iterations and iteration >= max_iterations:
            break

        iteration += 1
        print(f"\n[orchestrator] Next run in {interval}s... (Ctrl+C to stop)")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[orchestrator] Stopped by user.")
            break


main()
