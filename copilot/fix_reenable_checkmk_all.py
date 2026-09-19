#!/usr/bin/env python3
"""fix_reenable_checkmk_all.py - Reenable Check_MK (data collector) on all stale hosts.
Use correct LiveStatus query (send + SHUT_WR) and send ENABLE_SVC_CHECK directly.
Version: 1.0.0"""
import socket
import time
import subprocess

LIVE_SOCKET = "/omd/sites/monitoring/tmp/run/live"
NAGIOS_CMD  = "/omd/sites/monitoring/tmp/run/nagios.cmd"


def live(q):
    """LiveStatus Query - fixed method with SHUT_WR"""
    s = socket.socket(socket.AF_UNIX)
    s.connect(LIVE_SOCKET)
    s.send((q + "\n").encode())
    s.shutdown(socket.SHUT_WR)
    data = s.makefile().read()
    s.close()
    return [l for l in data.split("\n") if l.strip()]


def send_cmd(command):
    ts = int(time.time())
    with open(NAGIOS_CMD, "a") as f:
        f.write(f"[{ts}] {command}\n")


print("=" * 65)
print("FIX DEFINITIVO: ENABLE Check_MK data collector su tutti gli host")
print("=" * 65)

# Get ALL monitored hosts (not the ones with problems, just ALL)
hosts_rows = live(
    "GET hosts\n"
    "Columns: name\n"
)
all_hosts = [r.strip() for r in hosts_rows if r.strip()]
print(f"\nHost totali nel sistema: {len(all_hosts)}")

# Only take hosts that have Check_MK service with high staleness
stale_rows = live(
    "GET services\n"
    "Filter: description = Check_MK\n"
    "Columns: host_name active_checks_enabled staleness\n"
)

print(f"Servizi Check_MK trovati: {len(stale_rows)}")
print("\nStato attuale Check_MK per host:")

hosts_to_fix = []
for row in stale_rows:
    parts = row.split(";")
    if len(parts) >= 3:
        host = parts[0].strip()
        active = parts[1].strip()
        staleness = parts[2].strip()
        stale_val = float(staleness) if staleness.replace('.','').isdigit() else 0
        marker = " ← DA FIXARE" if stale_val > 1.5 or active == "0" else ""
        print(f"  {host} | active={active} | staleness={stale_val:.1f}{marker}")
        if stale_val > 1.5 or active == "0":
            hosts_to_fix.append(host)

print(f"\nHost da fixare: {len(hosts_to_fix)}")

if not hosts_to_fix:
    print("\nNessun host stale. Provo comunque enable su tutti (force mode)...")
    # Read all hosts with Check_MK service
    hosts_to_fix = [r.split(";")[0].strip() for r in stale_rows if r.strip()]
    print(f"Force mode: {len(hosts_to_fix)} host")

if not hosts_to_fix:
    print("Zero host trovati - problema con LiveStatus query. Esco.")
    exit(1)

print(f"\n[STEP 1] Invio ENABLE_SVC_CHECK per {len(hosts_to_fix)} host...")
for host in hosts_to_fix:
    send_cmd(f"ENABLE_SVC_CHECK;{host};Check_MK")
    print(f"  ENABLE_SVC_CHECK: {host}")

# Wait for Nagios to process the commands
time.sleep(3)

print(f"\n[STEP 2] Eseguo cmk --check su tutti gli host...")
ok = 0
err = 0
for host in hosts_to_fix:
    try:
        result = subprocess.run(
            ["su", "-", "monitoring", "-c", f"cmk --check '{host}'"],
            capture_output=True, text=True, timeout=60
        )
        rc = result.returncode
        if rc == 0:
            print(f"   {host} OK")
            ok += 1
        else:
            out = (result.stdout + result.stderr).strip()[:100]
            print(f"   {host} RC={rc}: {out}")
            err += 1
    except subprocess.TimeoutExpired:
        print(f"   {host} TIMEOUT")
        err += 1

print(f"\n  cmk --check: {ok} OK, {err} errori/timeout")

# Please wait and check
print(f"\n[STEP 3] Attendo 10s e verifico staleness...")
time.sleep(10)

print("\nVerifica finale:")
check_rows = live(
    "GET services\n"
    "Filter: description = Check_MK\n"
    "Columns: host_name active_checks_enabled staleness last_check\n"
)

now = int(time.time())
resolved = still_stale = 0
for row in check_rows:
    parts = row.split(";")
    if len(parts) >= 4:
        host = parts[0]
        active = parts[1]
        stale = float(parts[2]) if parts[2].replace('.','').isdigit() else 99
        age = (now - int(parts[3])) // 60 if parts[3].isdigit() else "?"
        if stale < 2.0:
            print(f"   {host} | active={active} | staleness={stale:.2f} | {age}min")
            resolved += 1
        else:
            print(f"   {host} | active={active} | staleness={stale:.2f} | {age}min ← ANCORA STALE")
            still_stale += 1

# Conta stale totali
tot_rows = live("GET services\nFilter: staleness > 1.5\nStats: state >= 0\n")
tot = tot_rows[0].strip() if tot_rows else "?"

print(f"\n{'='*65}")
print(f"RISULTATO: {resolved} OK, {still_stale} ancora stale")
print(f"Stale totali nel sistema: {tot}")
print("=" * 65)
