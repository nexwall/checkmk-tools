import socket, time

def live(q):
    s = socket.socket(socket.AF_UNIX)
    s.connect("/omd/sites/monitoring/tmp/run/live")
    s.send((q + "\n").encode())
    s.shutdown(socket.SHUT_WR)
    return s.makefile().read()

now = int(time.time())

print("=" * 70)
print("DIAGNOSTICA STALENESS (campo reale CheckMK)")
print("=" * 70)

# ===== STALE COUNT for threshold =====
for thr in [1.0, 1.5, 2.0, 5.0]:
    r = live(f"GET services\nFilter: staleness > {thr}\nStats: state >= 0\n").strip()
    print(f"  staleness > {thr}: {r} servizi")

# ===== ALL STALE (staleness > 1.5) =====
r = live("GET services\nFilter: staleness > 1.5\nColumns: host_name description staleness state last_check active_checks_enabled\n").strip()
print(f"\n[STALE reali staleness>1.5]")
if r:
    lines = r.split("\n")
    print(f"  Totale: {len(lines)}")

    # Group by host
    by_host = {}
    for line in lines:
        p = line.split(";")
        if len(p) >= 6:
            host = p[0]
            if host not in by_host:
                by_host[host] = []
            stale_val = float(p[2]) if p[2].replace('.','').isdigit() else 0
            age = (now - int(p[4])) // 60 if p[4].isdigit() else "?"
            state = {0:"OK",1:"WARN",2:"CRIT",3:"UNK"}.get(int(p[3]) if p[3].isdigit() else -1, "?")
            by_host[host].append((p[1], stale_val, age, state, p[5]))

    print(f"\n  HOST con servizi stale ({len(by_host)} host):")
    for host in sorted(by_host, key=lambda h: -len(by_host[h])):
        svcs = by_host[host]
        print(f"\n  [{host}] ({len(svcs)} servizi stale):")
        for svc, stale, age, state, active in sorted(svcs, key=lambda x: -x[1])[:10]:
            print(f"    [{state}] {svc} | staleness={stale:.1f} | last_check={age}min fa | active={active}")
        if len(svcs) > 10:
            print(f"    ... e altri {len(svcs)-10}")
else:
    print("  Nessuno stale! ")

# ===== CHECK_MK SERVICE FOR HOST — check active + staleness =====
r = live("GET services\nFilter: description ~ Check_MK\nColumns: host_name description staleness active_checks_enabled last_check\n").strip()
print(f"\n[Check_MK* services - stato attuale]")
if r:
    lines = r.split("\n")
    problems = []
    for line in lines:
        p = line.split(";")
        if len(p) >= 5:
            stale = float(p[2]) if p[2].replace('.','').isdigit() else 0
            age = (now - int(p[4])) // 60 if p[4].isdigit() else "?"
            if stale > 1.0 or str(p[3]) == "1":
                problems.append((p[0], p[1], stale, p[3], age))
    if problems:
        print(f"  PROBLEMI ({len(problems)}):")
        for host, svc, stale, active, age in problems:
            print(f"    {host} | {svc} | staleness={stale:.1f} | active={active} | {age}min fa")
    else:
        print(f"  Tutti OK (active=0, staleness OK) su {len(lines)} servizi ")

print("\n" + "=" * 70)
