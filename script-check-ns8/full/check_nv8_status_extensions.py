#!/usr/bin/env python3
"""check_nv8_status_extensions.py - CheckMK Local Check for NethVoice NS8 extension recording status

Monitor PJSIP registration of extensions (endpoints) on all NethVoice modules
installed on NethServer 8 (NS8).

Use runagent + podman exec to run `asterisk -rx "pjsip show endpoints"` in
FreePBX/Asterisk container of each NethVoice module found.

CheckMK Output:
  - One row per NOT registered extension (for granular drilldown in CheckMK)
  - An NV8.Status.Extensions summary line with total counts

PJSIP endpoint states:
  Not in use → registered, no active calls (OK)
  In use → registered, call in progress (OK)
  Ringing → recorded, ringing (OK)
  Busy → registered, busy (OK)
  On Hold → registered, waiting (OK)
  Unavailable → NOT registered (no contact) (WARN/CRIT)
  Invalid → configuration error (WARN)
  Unknown → unknown status (WARN)

Thresholds (configurable):
  WARN if >WARN_PCT% of extensions not registered (default: 10%)
  CRIT if >CRIT_PCT% of extensions not registered (default: 30%)

Deployment (NS8 hosts):
  cd /opt/checkmk-tools && git pull
  cp script-check-ns8/full/check_nv8_status_extensions.py /usr/lib/check_mk_agent/local/check_nv8_status_extensions
  chmod +x /usr/lib/check_mk_agent/local/check_nv8_status_extensions

Version: 1.0.0"""

import re
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

VERSION = "1.0.3"
SERVICE_SUMMARY  = "NV8.Status.Extensions"
SERVICE_EXT      = "NV8.Status.Extension"

SCRIPT_TIMEOUT = 25       # secondi totali budget
WARN_PCT       = 10       # % interni non registrati → WARNING
CRIT_PCT       = 30       # % interni non registrati → CRITICAL

_START = time.monotonic()

# Endpoint states indicating active registration
REGISTERED_STATES = {
    "not in use",
    "in use",
    "ringing",
    "ring",
    "busy",
    "on hold",
}

# Regex for Endpoint line in the output of `pjsip show endpoints`
# Formato: "  Endpoint:  <name/cid>  <state>  <N of M>"
# Example: "Endpoint: 100 Not in use 0 of inf"
#          "  Endpoint:  200/200              Unavailable   0 of inf"
ENDPOINT_RE = re.compile(
    r"^\s+Endpoint:\s+(\S+)\s+(.*?)\s+\d+\s+of\s+",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def elapsed() -> float:
    return time.monotonic() - _START


def run_command(cmd: List[str], timeout: int = 8) -> Tuple[int, str, str]:
    """Executes a command within the global time budget."""
    try:
        remaining = max(1, int(SCRIPT_TIMEOUT - elapsed()))
        effective = min(timeout, remaining)
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=effective,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "command not found"
    except Exception as exc:
        return 1, "", str(exc)


def sanitize_name(name: str) -> str:
    """Converts an extension name to CheckMK service name dot format."""
    # Rimuove suffisso /CID (es: "200/200" → "200")
    name = name.split("/")[0]
    name = re.sub(r"[^a-zA-Z0-9]", ".", name)
    name = re.sub(r"\.{2,}", ".", name)
    return name.strip(".") or "ext"


# ---------------------------------------------------------------------------
# Discovery moduli e container
# ---------------------------------------------------------------------------

def get_modules() -> List[str]:
    code, out, _ = run_command(["runagent", "-l"])
    if code != 0 or not out:
        return []
    return [
        line.strip()
        for line in out.splitlines()
        if line.strip() and line.strip() not in ("cluster", "node")
    ]


def get_containers(module: str) -> List[str]:
    """Returns the names of the containers running in the module."""
    code, out, _ = run_command(
        ["runagent", "-m", module, "podman", "ps", "--format", "{{.Names}}"]
    )
    if code != 0 or not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def find_nethvoice_containers() -> List[Tuple[str, str]]:
    """Find all FreePBX/Asterisk containers in NethVoice modules.
    Returns list of (module_name, container_name)."""
    results = []
    for module in get_modules():
        if elapsed() >= SCRIPT_TIMEOUT - 5:
            break
        if not any(kw in module.lower() for kw in ("nethvoice", "asterisk", "freepbx", "pbx")):
            continue
        for cname in get_containers(module):
            if "freepbx" in cname.lower() or "asterisk" in cname.lower():
                results.append((module, cname))
    return results


# ---------------------------------------------------------------------------
# Query Asterisk CLI
# ---------------------------------------------------------------------------

def run_asterisk_cmd(module: str, container: str, asterisk_cmd: str) -> Optional[str]:
    """Executes an Asterisk CLI command. Return stdout or None on serious error."""
    code, out, _ = run_command(
        ["runagent", "-m", module, "podman", "exec",
         container, "asterisk", "-rx", asterisk_cmd],
        timeout=10,
    )
    if code in (124, 127):
        return None
    return out


# ---------------------------------------------------------------------------
# Parsing `pjsip show endpoints`
# ---------------------------------------------------------------------------

def parse_endpoints(output: str) -> List[Dict[str, str]]:
    """Parse the output of `pjsip show endpoints`.
    Returns list of dicts with:
      name - endpoint name (without CID)
      state - raw state (lowercase)
      registered - True if registered with active contact"""
    endpoints = []
    for line in output.splitlines():
        m = ENDPOINT_RE.match(line)
        if not m:
            continue

        raw_name  = m.group(1).strip()
        raw_state = m.group(2).strip()
        state_lc  = raw_state.lower()

        # Skip endpoints that appear to be trunk or system endpoints
        base_name = raw_name.split("/")[0]
        if any(kw in base_name.lower() for kw in ("trunk", "reg-", "reg_", "sip:", "anonymous")):
            continue

        # Skip non-endpoint entries (headers, separators, counts)
        if not re.match(r"^[a-zA-Z0-9]", base_name):
            continue

        registered = state_lc in REGISTERED_STATES

        endpoints.append({
            "name":       base_name,
            "raw_name":   raw_name,
            "state":      raw_state,
            "registered": registered,
        })

    return endpoints


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    # Prerequisiti
    rc, _, _ = run_command(["which", "runagent"])
    if rc != 0:
        print(f"3 {SERVICE_SUMMARY} - UNKNOWN: runagent not found, this script requires NS8")
        return 0

    containers = find_nethvoice_containers()
    if not containers:
        print(f"2 {SERVICE_SUMMARY} - CRITICAL: no NethVoice module found on this NS8 host")
        return 0

    all_endpoints: List[Dict[str, str]] = []
    modules_checked: List[str] = []

    for module, container in containers:
        if elapsed() >= SCRIPT_TIMEOUT - 3:
            break

        output = run_asterisk_cmd(module, container, "pjsip show endpoints")
        if not output or not output.strip():
            continue

        eps = parse_endpoints(output)
        for ep in eps:
            ep["module"] = module
        all_endpoints.extend(eps)
        modules_checked.append(module)

    if not all_endpoints:
        print(
            f"1 {SERVICE_SUMMARY} - WARNING: no PJSIP extension found "
            f"| modules={','.join(modules_checked) or 'none'}"
        )
        return 0

    total       = len(all_endpoints)
    registered  = [e for e in all_endpoints if e["registered"]]
    unreg       = [e for e in all_endpoints if not e["registered"]]
    reg_count   = len(registered)
    unreg_count = len(unreg)
    unreg_pct   = (unreg_count / total * 100) if total > 0 else 0.0

    # One CRIT line for each unregistered extension → separate service → individual notification
    for ep in unreg:
        svc = f"{SERVICE_EXT}.{sanitize_name(ep['name'])}"
        print(f"2 {svc} - Unregistered | name={ep['name']} state={ep['state']} module={ep['module']}")

    # Concise summary (counts only)
    if unreg_count == 0:
        overall = 0
        msg = f"OK: all {total} extensions registered"
    elif unreg_pct >= CRIT_PCT:
        overall = 2
        msg = f"CRITICAL: {reg_count}/{total} registered, {unreg_count} unregistered ({unreg_pct:.0f}%)"
    elif unreg_pct >= WARN_PCT:
        overall = 1
        msg = f"WARNING: {reg_count}/{total} registered, {unreg_count} unregistered ({unreg_pct:.0f}%)"
    else:
        overall = 0
        msg = f"OK: {reg_count}/{total} registered, {unreg_count} unregistered ({unreg_pct:.0f}%)"

    perf = f"registered={reg_count};;;0;{total} unregistered={unreg_count};;;0;{total} total={total}"
    modules_str = ",".join(modules_checked)
    print(f"{overall} {SERVICE_SUMMARY} - {msg} | {perf} modules={modules_str}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
