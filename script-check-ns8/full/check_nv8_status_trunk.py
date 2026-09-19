#!/usr/bin/env python3
"""check_nv8_status_trunk.py - CheckMK Local Check for NethVoice NS8 trunk status

Monitor PJSIP trunk logging on NethVoice NS8.
Use runagent + podman exec to run `asterisk -rx "pjsip show registrations"`
inside the Asterisk container of the NethVoice module.

CheckMK Output:
  - One line per trunk (dedicated service for granularity in case of problems)
  - One overall summary line (NethVoice_Trunks)

Recognized PJSIP states:
  Registered → OK (0)
  Not Registered → WARNING (1) e.g. non-registering IP-based trunks
  Trying → WARNING (1) recording in progress
  No Auth → CRITICAL (2) authentication error
  Rejected → CRITICAL (2) rejected by the provider
  Failed → CRITICAL (2) generic failure
  Stopped → CRITICAL (2) recording stopped
  Unregistered → CRITICAL (2) deregistered

Deployment:
  cp check_nethvoice_trunks.py /usr/lib/check_mk_agent/local/
  chmod +x /usr/lib/check_mk_agent/local/check_nethvoice_trunks.py

Version: 1.0.0"""

import subprocess
import sys
import re
import time
from typing import Dict, List, Optional, Tuple

VERSION = "1.5.0"
SERVICE_PREFIX = "NV8.Status.Trunk"
SERVICE_SUMMARY = "NV8.Status.Trunks"

SCRIPT_TIMEOUT = 20  # secondi totali a disposizione dello script
_START = time.monotonic()

# PJSIP registration states → CheckMK state (0=OK, 1=WARN, 2=CRIT, 3=UNKNOWN)
STATE_MAP: Dict[str, int] = {
    "Registered":     0,  # registrato correttamente
    "Not Registered": 1,  # non registrato (potrebbe essere intenzionale per trunk IP-based)
    "Trying":         1,  # tentativo di registrazione in corso
    "No Auth":        2,  # credenziali errate
    "Rejected":       2,  # rifiutato dal provider SIP
    "Failed":         2,  # errore generico
    "Stopped":        2,  # registrazione fermata
    "Unregistered":   2,  # deregistrato manualmente
}

# Regex to detect PJSIP status in the line (not necessarily at the end of the line)
# ex: "trunk/sip:host:5060 auth Rejected (exp. 28s)"
STATUS_RE = re.compile(
    r"\b(Not\s+Registered|No\s+Auth|Registered|Trying|Rejected|Failed|Stopped|Unregistered)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def elapsed() -> float:
    """Seconds elapsed since the script was started."""
    return time.monotonic() - _START


def run_command(cmd: List[str], timeout: int = 8) -> Tuple[int, str, str]:
    """Executes a command and returns (exit_code, stdout, stderr).
    Respect the SCRIPT_TIMEOUT global time budget."""
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
    """Converts a trunk name into a valid service name for CheckMK.
    - Remove prefix reg- / reg_
    - Replaces non-alphanumeric characters (including _ and -) with dots"""
    name = re.sub(r"^reg[-_]", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^a-zA-Z0-9]", ".", name)
    name = re.sub(r"\.{2,}", ".", name)  # collassa punti multipli
    return name.strip(".") or "trunk"


# ---------------------------------------------------------------------------
# Discovery of the Asterisk container
# ---------------------------------------------------------------------------

def get_modules() -> List[str]:
    """Returns the list of all NS8 modules (output of runagent -l)."""
    code, out, _ = run_command(["runagent", "-l"])
    if code != 0 or not out:
        return []
    return [
        line.strip()
        for line in out.splitlines()
        if line.strip() and line.strip() not in ("cluster", "node")
    ]


def get_containers(module: str) -> List[Tuple[str, str]]:
    """Returns the module containers as a list of (name, status).
    Use `podman ps` (running containers only) to exclude stopped containers."""
    code, out, _ = run_command(
        ["runagent", "-m", module, "podman", "ps",
         "--format", "{{.Names}}|{{.Status}}"]
    )
    if code != 0 or not out:
        return []
    result = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        cname, cstatus = line.split("|", 1)
        result.append((cname.strip(), cstatus.strip()))
    return result


def find_nethvoice_containers() -> List[Tuple[str, str]]:
    """Find ALL FreePBX/Asterisk containers in all nethvoice modules.
    Returns list of (module_name, container_name)."""
    results = []
    for module in get_modules():
        if elapsed() >= SCRIPT_TIMEOUT:
            break
        # Optimization: Skip modules that are not nethvoice/asterisk/pbx
        if not any(kw in module.lower() for kw in ("nethvoice", "asterisk", "freepbx", "pbx")):
            continue
        for cname, _ in get_containers(module):
            if "freepbx" in cname.lower() or "asterisk" in cname.lower():
                results.append((module, cname))
    return results


# ---------------------------------------------------------------------------
# Query Asterisk
# ---------------------------------------------------------------------------

def run_asterisk_cmd(module: str, container: str, asterisk_cmd: str) -> Optional[str]:
    """Run an Asterisk command via runagent + podman exec.

    Returns:
        Raw output (stdout) or None in case of serious error."""
    code, out, err = run_command(
        ["runagent", "-m", module, "podman", "exec",
         container, "asterisk", "-rx", asterisk_cmd],
        timeout=10,
    )
    # Asterisk CLI can exit with code != 0 even with valid output;
    # we consider only timeout error (124) or command not found (127)
    if code in (124, 127):
        return None
    # "No objects found." is valid output (no trunk configured)
    return out


# ---------------------------------------------------------------------------
# Parsing `pjsip show registrations`
# ---------------------------------------------------------------------------

def parse_pjsip_registrations(output: str) -> List[Dict[str, str]]:
    """Parse the output of `asterisk -rx "pjsip show registrations"`.

    Typical format:
        <Registration/ServerURI......> <Auth.......> <Status>
        ========================================================================
        reg-trunk1/sip:user@host auth-t1 Registered
        reg-trunk2/sip:user@host2 auth-t2 Rejected
        2 registrations.

    Returns:
        List of dicts with keys: name, server, status"""
    trunks: List[Dict[str, str]] = []

    for line in output.splitlines():
        stripped = line.strip()

        # Salta righe vuote, separatori (===), header (<...>)
        if not stripped:
            continue
        if stripped.startswith("=") or stripped.startswith("<"):
            continue
        # Salta riga sommario "N registrations."
        if re.match(r"^\d+\s+registration", stripped, re.IGNORECASE):
            continue
        # Salta "No registrations currently exist."
        if "no registrations" in stripped.lower():
            continue

        # Look for PJSIP status at the bottom of the line
        m = STATUS_RE.search(stripped)
        if not m:
            continue

        status = re.sub(r"\s+", " ", m.group(1)).strip()

        # Column 1: the first part (separated by 2+ spaces)
        parts = re.split(r"\s{2,}", stripped)
        if not parts:
            continue

        reg_uri = parts[0].strip()
        reg_name = reg_uri.split("/")[0] if "/" in reg_uri else reg_uri
        server_uri = reg_uri.split("/", 1)[1] if "/" in reg_uri else ""

        trunks.append({
            "name": reg_name,
            "server": server_uri,
            "status": status,
        })

    return trunks


# ---------------------------------------------------------------------------
# CheckMK state helpers
# ---------------------------------------------------------------------------

def get_state(status: str) -> int:
    """Returns CheckMK status for a PJSIP status (default: 1 WARN for unknown)."""
    return STATE_MAP.get(status, 1)


STATE_LABEL = {0: "OK", 1: "WARNING", 2: "CRITICAL", 3: "UNKNOWN"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    # --- 1. Check runagent available (NS8) ---
    if run_command(["which", "runagent"])[0] != 0:
        print(f"3 {SERVICE_SUMMARY} - UNKNOWN: runagent not found, this script requires NS8")
        return 0

    # --- 2. Search ALL FreePBX/Asterisk containers ---
    containers = find_nethvoice_containers()
    if not containers:
        print(
            f"2 {SERVICE_SUMMARY} - CRITICAL: Asterisk/FreePBX container not found "
            f"(NethVoice installed? container running?)"
        )
        return 0

    # --- 3. Collect recordings from ALL nethvoice modules ---
    all_trunks: List[Dict[str, str]] = []
    modules_checked: List[str] = []

    for module, container in containers:
        raw = run_asterisk_cmd(module, container, "pjsip show registrations outbound")
        if raw is None:
            continue
        trunks = parse_pjsip_registrations(raw)
        for t in trunks:
            t["module"] = module  # add module info for debug
        all_trunks.extend(trunks)
        modules_checked.append(module)

    modules_str = ",".join(modules_checked) if modules_checked else "none"

    # --- 4. No trunks found ---
    if not all_trunks:
        print(
            f"1 {SERVICE_SUMMARY} - WARNING: no PJSIP outbound trunk configured "
            f"| modules={modules_str}"
        )
        return 0

    # --- 5. Output one line per trunk ---
    overall_state = 0
    registered_count = 0

    for trunk in all_trunks:
        state = get_state(trunk["status"])
        overall_state = max(overall_state, state)

        if state == 0:
            registered_count += 1

        svc_name = f"{SERVICE_PREFIX}.{sanitize_name(trunk['name'])}"

        # Shortened server URI: domain[:port] without sip:/sips:
        server = trunk["server"]
        server_clean = re.sub(r"^sips?:", "", server)          # remove schema
        server_clean = server_clean.split("@")[-1]              # host only (without user)
        server_clean = server_clean.split(";")[0].strip()       # remove SIP parameters

        mod = trunk.get("module", "")
        # Perfdata must be the single whitespace-free 3rd field (CheckMK's
        # local check parser never re-scans the free-text field for a later
        # "|") - previously there was no perfdata at all, so no graph icon
        # ever appeared for these services. "registered" is a 0/1 gauge so
        # the CheckMK graph renders as a step function showing exactly when
        # the trunk went down/up.
        perfdata = f"registered={1 if state == 0 else 0};;;0;1"
        print(f"{state} {svc_name} {perfdata} - {trunk['status']} | server={server_clean} module={mod}")

    # --- 6. Summary line ---
    total = len(all_trunks)
    not_ok = total - registered_count

    if overall_state == 0:
        summary_msg = f"OK: all trunks registered ({registered_count}/{total})"
    elif overall_state == 1:
        summary_msg = f"WARNING: {registered_count}/{total} registered, {not_ok} with issues"
    else:
        summary_msg = f"CRITICAL: {registered_count}/{total} registered, {not_ok} with issues"

    summary_perfdata = f"registered_trunks={registered_count};;;0;{total}|total_trunks={total}"
    print(
        f"{overall_state} {SERVICE_SUMMARY} {summary_perfdata} - {summary_msg} "
        f"| modules={modules_str}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
