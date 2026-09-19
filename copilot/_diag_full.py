import socket, time

def live(q):
    s = socket.socket(socket.AF_UNIX)
    s.connect("/omd/sites/monitoring/tmp/run/live")
    s.send((q + "\n").encode())
    s.shutdown(socket.SHUT_WR)
    return s.makefile().read()

now = int(time.time())
th30 = now - 1800   # 30 min
th60 = now - 3600   # 60 min

print("=" * 70)
print("DIAGNOSTICA COMPLETA CheckMK")
print("=" * 70)

# ===== TOTALI =====
r = live("GET services\nStats: state = 0\nStats: state = 1\nStats: state = 2\nStats: state = 3\n").strip()
v = r.split(";")
print(f"\n[TOTALI SERVIZI]  OK={v[0]}  WARN={v[1]}  CRIT={v[2]}  UNK={v[3]}")

# ===== HOST DOWN =====
r = live("GET hosts\nFilter: state != 0\nColumns: name state last_check\n").strip()
print(f"\n[HOST NON-UP]")
if r:
    for line in r.split("\n"):
        p = line.split(";")
        if len(p) >= 3:
            age = (now - int(p[2])) // 60 if p[2].isdigit() else "?"
            state = {0:"UP",1:"DOWN",2:"UNREACHABLE"}.get(int(p[1]) if p[1].isdigit() else -1, p[1])
            print(f"  {p[0]} | {state} | last={age}min fa")
else:
    print("  tutti UP ")

# ===== STALE >30min =====
r = live(f"GET services\nFilter: last_check < {th30}\nColumns: host_name description last_check state active_checks_enabled passive_checks_enabled\n").strip()
print(f"\n[STALE >30min]")
if r:
    lines = r.split("\n")
    print(f"  Totale: {len(lines)}")
    for line in sorted(lines, key=lambda x: int(x.split(';')[2]) if x.split(';')[2].isdigit() else 0):
        p = line.split(";")
        if len(p) >= 6:
            age = (now - int(p[2])) // 60 if p[2].isdigit() else 999999
            state = {0:"OK",1:"WARN",2:"CRIT",3:"UNK"}.get(int(p[3]) if p[3].isdigit() else -1, p[3])
            print(f"  [{state}] {p[0]} | {p[1]} | {age}min | active={p[4]} passive={p[5]}")
else:
    print("  nessuno ")

# ===== PENDING (never checked) =====
r = live("GET services\nFilter: has_been_checked = 0\nColumns: host_name description active_checks_enabled passive_checks_enabled\n").strip()
print(f"\n[PENDING - mai controllati]")
if r:
    lines = r.split("\n")
    print(f"  Totale: {len(lines)}")
    for line in lines:
        p = line.split(";")
        if len(p) >= 4:
            print(f"  {p[0]} | {p[1]} | active={p[2]} passive={p[3]}")
else:
    print("  nessuno ")

# ===== CRIT BREAKDOWN =====
r = live("GET services\nFilter: state = 2\nColumns: host_name description last_check active_checks_enabled\n").strip()
print(f"\n[CRIT - tutti]")
if r:
    lines = r.split("\n")
    print(f"  Totale: {len(lines)}")
    # Group by host
    by_host = {}
    for line in lines:
        p = line.split(";")
        if len(p) >= 4:
            host = p[0]
            if host not in by_host:
                by_host[host] = []
            age = (now - int(p[2])) // 60 if p[2].isdigit() else "?"
            by_host[host].append(f"{p[1]} (age={age}min)")
    for host in sorted(by_host):
        print(f"  {host} ({len(by_host[host])}):")
        for svc in by_host[host]:
            print(f"    - {svc}")
else:
    print("  nessuno")

# ===== WARN BREAKDOWN =====
r = live("GET services\nFilter: state = 1\nColumns: host_name description last_check\n").strip()
print(f"\n[WARN - tutti]")
if r:
    lines = r.split("\n")
    print(f"  Totale: {len(lines)}")
    for line in lines:
        p = line.split(";")
        if len(p) >= 3:
            age = (now - int(p[2])) // 60 if p[2].isdigit() else "?"
            print(f"  {p[0]} | {p[1]} | age={age}min")
else:
    print("  nessuno")

print("\n" + "=" * 70)
