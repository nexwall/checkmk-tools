import socket, time

def live(q):
    s = socket.socket(socket.AF_UNIX)
    s.connect("/omd/sites/monitoring/tmp/run/live")
    s.send((q + "\n").encode())
    s.shutdown(socket.SHUT_WR)
    return s.makefile().read()

now = int(time.time())
th = now - 1800  # 30 min

# Stale count
r = live(f"GET services\nFilter: last_check < {th}\nFilter: scheduled_downtime_depth = 0\nStats: state >= 0\n").strip()
print(f"STALE >30min: {r}")

# Totali
r2 = live("GET services\nStats: state = 0\nStats: state = 1\nStats: state = 2\nStats: state = 3\n").strip()
v = r2.split(";")
print(f"TOTALE -> OK={v[0]} WARN={v[1]} CRIT={v[2]} UNK={v[3]}")

# Pending
r3 = live("GET services\nFilter: has_been_checked = 0\nStats: state >= 0\n").strip()
print(f"PENDING (mai controllati): {r3}")

# Check_MK* stale
r4 = live(f"GET services\nFilter: description ~ Check_MK\nFilter: last_check < {th}\nColumns: host_name description last_check active_checks_enabled\n").strip()
print("Check_MK* STALE:")
if r4:
    for line in r4.split("\n"):
        p = line.split(";")
        if len(p) >= 4:
            age = (now - int(p[2])) // 60 if p[2].isdigit() else "?"
            print(f"  {p[0]} | {p[1]} | {age}min | active={p[3]}")
else:
    print("  nessuno ")

# Top 10 stale
r5 = live(f"GET services\nFilter: last_check < {th}\nColumns: host_name description last_check\n").strip()
print(f"\nPRIMI 20 STALE:")
if r5:
    lines = r5.split("\n")
    print(f"  (totale righe: {len(lines)})")
    for l in lines[:20]:
        p = l.split(";")
        if len(p) >= 3:
            age = (now - int(p[2])) // 60 if p[2].isdigit() else "?"
            print(f"  {p[0]} | {p[1]} | {age}min")
else:
    print("  nessuno ")
