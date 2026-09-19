#!/usr/bin/env python3
"""fix_stale_checkmk.py - Fixes Check_MK* stale services

MECHANISM:
  1. Enable passive_checks on the Check_MK* service (ENABLE_PASSIVE_SVC_CHECKS)
     → DO NOT touch active_checks_enabled (remains 0)
  2. Inject passive result OK via PROCESS_SERVICE_CHECK_RESULT
     → update last_check without activating automatic scheduling
  3. Run cmk --check <host> to update the sub-services (CPU, Disk, etc.)

USE:
  python3 fix_stale_checkmk.py # sample mode (3 hosts)
  python3 fix_stale_checkmk.py --all # all stale hosts
  python3 fix_stale_checkmk.py --host DC01 <hostname> ns8

Version: 1.4.0"""
import subprocess, json, time, sys, os

now = int(time.time())
SAMPLE_SIZE = 3
CMD_PIPE = "/omd/sites/monitoring/tmp/run/nagios.cmd"
CMK_BIN = "/omd/sites/monitoring/bin/cmk"

# Check_MK* services to be processed
CMK_SERVICES = ["Check_MK", "Check_MK Discovery", "Check_MK Agent", "Check_MK HW/SW Inventory"]


def lq(query):
    import socket as _socket
    if not query.endswith("\n"):
        query += "\n"
    if not query.endswith("\n\n"):
        query += "\n"
    s = _socket.socket(_socket.AF_UNIX)
    s.connect("/omd/sites/monitoring/tmp/run/live")
    s.send(query.encode())
    s.shutdown(_socket.SHUT_WR)
    raw = s.makefile().read().strip()
    return json.loads(raw) if raw else []


def send_pipe_cmds(commands):
    """Send commands to the Nagios pipe directly (per-command writing)."""
    ts = int(time.time())
    count = 0
    for cmd in commands:
        try:
            with open(CMD_PIPE, 'w') as f:
                f.write(f"[{ts}] {cmd}\n")
            count += 1
        except Exception as e:
            print(f"  ERRORE pipe cmd '{cmd[:60]}': {e}")
    print(f"  Inviati {count}/{len(commands)} comandi")
    return count == len(commands)


def cmk_check(host):
    """Run cmk --check <host> one-shot to update subservices."""
    if os.geteuid() == 0:
        # Root: deve girare come site user "monitoring"
        cmd = ['su', '-', 'monitoring', '-s', '/bin/bash', '-c', f'{CMK_BIN} --check {host}']
    else:
        cmd = [CMK_BIN, '--check', host]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


# --- Parse argomenti ---
mode = "sample"
explicit_hosts = []
if "--all" in sys.argv:
    mode = "all"
elif "--host" in sys.argv:
    mode = "explicit"
    idx = sys.argv.index("--host")
    explicit_hosts = sys.argv[idx + 1:]

print("=" * 62)
print("FIX STALE Check_MK*")
print("Metodo: ENABLE_PASSIVE + PROCESS_SERVICE_CHECK_RESULT + cmk --check")
print(f"Modalita: {mode.upper()} | active_checks_enabled NON modificato")
print("=" * 62)

# --- Find Check_MK* services stale ---
stale_svcs = lq(
    "GET services\n"
    f"Filter: last_check < {now - 60}\n"
    "Filter: description ~ Check_MK\n"
    "Columns: host_name description state last_check plugin_output\n"
    "OutputFormat: json\n"
)

stale_hosts = sorted(set(r[0] for r in stale_svcs if r[1] == "Check_MK"))
print(f"\nServizi Check_MK* stale (last_check < now-1min): {len(stale_svcs)}")
from collections import Counter
by_type = Counter(r[1] for r in stale_svcs)
for t, c in sorted(by_type.items()):
    print(f"  {c:3d}x  {t}")

# --- Select host to process ---
if mode == "explicit":
    hosts_to_check = explicit_hosts
elif mode == "all":
    hosts_to_check = stale_hosts
else:
    hosts_to_check = stale_hosts[:SAMPLE_SIZE]

print(f"\nHost da processare: {len(hosts_to_check)}")
for h in hosts_to_check:
    print(f"  - {h}")

if not hosts_to_check:
    print("Nessun host stale - sistema OK!")
    sys.exit(0)

if mode == "sample" and len(stale_hosts) > SAMPLE_SIZE:
    print(f"\n  (Usa --all per processare tutti i {len(stale_hosts)} host stale)")

# --- Step 1: enable passive checks + inject result OK ---
print(f"\n[Step 1] Abilita passive checks + inject risultato OK su Check_MK*")
cmds_step1 = []
for r in stale_svcs:
    host, svc, state, last_chk, output = r
    if host not in hosts_to_check:
        continue
    # Enable passive checks on this service (DO NOT touch active_checks_enabled)
    cmds_step1.append(f"ENABLE_PASSIVE_SVC_CHECKS;{host};{svc}")
    # Inject passive result with original state and original (or default) output
    out = output.replace(';', ',').replace('\n', ' ').strip() if output else "OK - stale reset"
    cmds_step1.append(f"PROCESS_SERVICE_CHECK_RESULT;{host};{svc};{state};{out}")

send_pipe_cmds(cmds_step1)

# --- Step 2: cmk --check to update sub-services ---
import time as tm
tm.sleep(2)
print(f"\n[Step 2] cmk --check per aggiornare sotto-servizi (CPU, Disk, Interface...)")
for host in hosts_to_check:
    print(f"  {host}...", end=" ", flush=True)
    try:
        rc, _, err = cmk_check(host)
        print("OK" if rc == 0 else f"RC={rc}")
        if rc != 0 and err:
            print(f"    stderr: {err[:80]}")
    except subprocess.TimeoutExpired:
        print("TIMEOUT")
    except Exception as e:
        print(f"ERRORE: {e}")

# --- Verify ---
tm.sleep(5)
print(f"\n[Verifica post-fix]")
now2 = int(tm.time())

host_filter = "|".join(hosts_to_check)
after = lq(
    "GET services\n"
    "Filter: description ~ Check_MK\n"
    f"Filter: host_name ~ {host_filter}\n"
    "Columns: host_name description state last_check active_checks_enabled\n"
    "OutputFormat: json\n"
)

ok_count = 0
still_stale = 0
for r in sorted(after, key=lambda x: (x[0], x[1])):
    host, svc, state, last_chk, active = r
    age = (now2 - last_chk) // 60
    state_str = {0:"OK",1:"WARN",2:"CRIT",3:"UNK"}.get(state,"?")
    if age < 5:
        status_str = " AGGIORNATO"
        ok_count += 1
    else:
        status_str = f"ancora stale ({age}min)"
        still_stale += 1
    print(f"  {host:30s} | {svc:25s} | {state_str:4s} | active={active} | {status_str}")

print(f"\nRisultato:")
print(f"  Aggiornati: {ok_count}")
print(f"  Ancora stale: {still_stale}")
print(f"  active_checks_enabled toccato: NO ")
print("\n" + "=" * 62)
