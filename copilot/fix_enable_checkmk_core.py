#!/usr/bin/env python3
"""fix_enable_checkmk_core.py - Reenable the "Check_MK" service (Check_MK ONLY,
not Check_MK Agent/Discovery) on all hosts where it has been disabled.

The "Check_MK" service is the CheckMK DATA COLLECTOR: schedule cmk --check <host>
and feed the passive results to all other services. MUST be active=1.
Without it the whole system goes permanently offline.

Version: 1.0.0"""
import socket
import select
import subprocess
import time

LIVE_SOCKET = "/omd/sites/monitoring/tmp/run/live"
NAGIOS_CMD  = "/omd/sites/monitoring/tmp/run/nagios.cmd"


def ls(q):
    s = socket.socket(socket.AF_UNIX)
    s.connect(LIVE_SOCKET)
    s.sendall(q.encode())
    d = b""
    while True:
        r, _, __ = select.select([s], [], [], 3)
        if not r:
            break
        c = s.recv(65536)
        if not c:
            break
        d += c
    s.close()
    return [l for l in d.decode().split("\n") if l.strip()]


def send_cmd(command):
    ts = int(time.time())
    line = f"[{ts}] {command}\n"
    with open(NAGIOS_CMD, "a") as f:
        f.write(line)


def get_staleness(host, svc):
    rows = ls(
        f"GET services\n"
        f"Filter: host_name = {host}\n"
        f"Filter: description = {svc}\n"
        f"Columns: staleness active_checks_enabled\n\n"
    )
    for r in rows:
        p = r.split(";")
        if len(p) >= 2:
            return float(p[0]) if p[0].replace('.','').isdigit() else 99, p[1]
    return 99, "?"


print("=" * 65)
print("FIX: Riabilita Check_MK core service (data collector)")
print("=" * 65)

# Find all hosts where the "Check_MK" service (exactly) is active=0
rows = ls(
    "GET services\n"
    "Filter: description = Check_MK\n"
    "Filter: active_checks_enabled = 0\n"
    "Columns: host_name description active_checks_enabled staleness\n\n"
)

if not rows:
    print("\nNessun host con Check_MK disabilitato. Sistema OK!")
else:
    hosts = []
    print(f"\nTrovati {len(rows)} host con Check_MK disabilitato (staleness attuale):")
    for r in rows:
        p = r.split(";")
        if len(p) >= 4:
            host = p[0]
            stale = float(p[3]) if p[3].replace('.','').isdigit() else 0
            print(f"  {host} | active={p[2]} | staleness={stale:.1f}")
            hosts.append(host)

    print(f"\n[STEP 1] Invio ENABLE_SVC_CHECK per {len(hosts)} host...")
    for host in hosts:
        send_cmd(f"ENABLE_SVC_CHECK;{host};Check_MK")
        print(f"   ENABLE_SVC_CHECK: {host}")
    time.sleep(1)

    print(f"\n[STEP 2] Eseguo cmk --check su tutti gli host...")
    ok_count = 0
    err_count = 0
    for host in hosts:
        result = subprocess.run(
            ["su", "-", "monitoring", "-c", f"cmk --check '{host}'"],
            capture_output=True, text=True, timeout=30
        )
        rc = result.returncode
        if rc == 0:
            print(f"   cmk --check {host} → OK")
            ok_count += 1
        else:
            print(f"   cmk --check {host} → RC={rc} (potrebbe essere host irraggiungibile)")
            err_count += 1

    print(f"\n[STEP 3] Attendo 15 secondi e verifico staleness...")
    time.sleep(15)

    resolved = 0
    still_stale = 0
    print("\nVerifica finale:")
    for host in hosts:
        stale, active = get_staleness(host, "Check_MK")
        if stale < 2.0:
            print(f"   {host} | staleness={stale:.2f} | active={active} → OK")
            resolved += 1
        else:
            print(f"   {host} | staleness={stale:.2f} | active={active} → ANCORA STALE")
            still_stale += 1

    print(f"\n{'='*65}")
    print(f"RISULTATO: {resolved}/{len(hosts)} risolti, {still_stale} ancora stale")

    # Conta stale totali
    rows_tot = ls("GET services\nFilter: staleness > 1.5\nStats: state >= 0\n")
    total_stale = rows_tot[0].strip() if rows_tot else "?"
    print(f"Stale totali nel sistema: {total_stale}")
    print("=" * 65)
