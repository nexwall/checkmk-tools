#!/usr/bin/python3
import socket, sys, subprocess, os, re
from collections import Counter

LIVE      = "/omd/sites/monitoring/tmp/run/live"
SITE      = "/omd/sites/monitoring"
NOTIFY_LOG = f"{SITE}/var/log/notify.log"
SPOOL_DIR  = f"{SITE}/var/check_mk/notify/spool"
PLUGINS_DIR = f"{SITE}/local/share/check_mk/notifications"

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.stdout.strip(), r.stderr.strip()

def live(query):
    s = socket.socket(socket.AF_UNIX)
    s.connect(LIVE)
    s.send((query + "\n").encode())
    s.shutdown(socket.SHUT_WR)
    data = s.makefile().read().strip()
    return [line.split(";") for line in data.splitlines() if line]

MODE = os.environ.get("CMK_MODE", "analysis")

if MODE == "notify":
    print()
    print("=" * 68)
    print("  CHECKMK NOTIFICATION SYSTEM CHECK  --  monitor.nethlab.it")
    print("=" * 68)

    # 1. mknotifyd status
    print("\n[ 1/5 ] mknotifyd process:")
    out, _ = run("pgrep -a mknotifyd")
    if out:
        print(f"  RUNNING: {out[:80]}")
    else:
        print("  !! mknotifyd NOT RUNNING")

    # 2. spool directory
    print("\n[ 2/5 ] Spool dir:")
    files, _ = run(f"ls -la {SPOOL_DIR} 2>/dev/null")
    lines = [l for l in files.splitlines() if not l.startswith("total") and l.strip()]
    stuck = [l for l in lines if not l.startswith("d") and ".txt" in l]
    if stuck:
        print(f"  !! {len(stuck)} notification(s) stuck in spool:")
        for l in stuck[:10]:
            print(f"     {l}")
    else:
        print("  OK - spool empty")

    # 3. notify.log — last 100 lines, extract errors/warnings
    print("\n[ 3/5 ] notify.log — last errors:")
    log_tail, _ = run(f"tail -200 {NOTIFY_LOG} 2>/dev/null")
    errors = []
    warns  = []
    for line in log_tail.splitlines():
        ll = line.lower()
        if "error" in ll or "exception" in ll or "traceback" in ll or "failed" in ll or "errno" in ll:
            errors.append(line)
        elif "warning" in ll or "warn" in ll:
            warns.append(line)
    if errors:
        print(f"  !! {len(errors)} error line(s) found:")
        for l in errors[-15:]:
            print(f"     {l[:110]}")
    else:
        print("  OK - no errors in last 200 lines")
    if warns:
        print(f"  {len(warns)} warning line(s):")
        for l in warns[-5:]:
            print(f"     {l[:110]}")

    # 4. notify.log — last 10 notification events
    print("\n[ 4/5 ] notify.log — ultimi 10 eventi:")
    events = [l for l in log_tail.splitlines() if "Starting notification" in l or "Sending notification" in l or "Plugin" in l or "Finished" in l or "Got notification" in l]
    for l in events[-10:]:
        print(f"  {l[:110]}")
    if not events:
        print("  (nessun evento recente trovato)")

    # 5. plugin installati
    print("\n[ 5/5 ] Notification plugins:")
    plugins, _ = run(f"ls -la {PLUGINS_DIR} 2>/dev/null")
    for l in plugins.splitlines():
        if not l.startswith("total") and not l.startswith("d"):
            print(f"  {l}")

    print("\n" + "=" * 68)
    sys.exit(0)

# default: infrastructure analysis

def live(query):
    s = socket.socket(socket.AF_UNIX)
    s.connect(LIVE)
    s.send((query + "\n").encode())
    s.shutdown(socket.SHUT_WR)
    data = s.makefile().read().strip()
    return [line.split(";") for line in data.splitlines() if line]

hosts = live("GET hosts\nColumns: name state plugin_output address\n")
svcs  = live("GET services\nColumns: host_name description state plugin_output\n")

STATE_HOST = {0: "UP", 1: "DOWN", 2: "UNREACHABLE", 3: "UNKNOWN"}
STATE_SVC  = {0: "OK", 1: "WARNING", 2: "CRITICAL", 3: "UNKNOWN"}

# parse hosts
h_up, h_down, h_unrch = [], [], []
for row in hosts:
    if len(row) < 4:
        continue
    name, state, out, addr = row[0], int(row[1]), row[2], row[3]
    if state == 0:
        h_up.append((name, addr, out))
    elif state == 1:
        h_down.append((name, addr, out))
    elif state == 2:
        h_unrch.append((name, addr, out))

# parse services
s_ok, s_warn, s_crit, s_unk = [], [], [], []
for row in svcs:
    if len(row) < 4:
        continue
    host, desc, state, out = row[0], row[1], int(row[2]), row[3]
    if state == 0:
        s_ok.append((host, desc, out))
    elif state == 1:
        s_warn.append((host, desc, out))
    elif state == 2:
        s_crit.append((host, desc, out))
    else:
        s_unk.append((host, desc, out))

print()
print("=" * 68)
print("  CHECKMK INFRASTRUCTURE ANALYSIS  --  monitor.nethlab.it")
print("=" * 68)

print(f"\n[ HOSTS: {len(hosts)} totali ]")
print(f"  UP          : {len(h_up)}")
print(f"  DOWN        : {len(h_down)}")
print(f"  UNREACHABLE : {len(h_unrch)}")

if h_down:
    print("\n  >> HOST DOWN:")
    for name, addr, out in h_down:
        print(f"     {name:<28} {addr:<16}  {out[:60]}")
if h_unrch:
    print("\n  >> HOST UNREACHABLE:")
    for name, addr, out in h_unrch:
        print(f"     {name:<28} {addr:<16}  {out[:60]}")

print(f"\n[ SERVICES: {len(svcs)} totali ]")
print(f"  OK       : {len(s_ok)}")
print(f"  WARNING  : {len(s_warn)}")
print(f"  CRITICAL : {len(s_crit)}")
print(f"  UNKNOWN  : {len(s_unk)}")

if s_crit:
    print("\n  >> CRITICAL:")
    for host, desc, out in s_crit:
        print(f"     [{host:<24}]  {desc:<28}  {out.replace(chr(10),' ')[:65]}")

if s_warn:
    print("\n  >> WARNING:")
    for host, desc, out in s_warn:
        print(f"     [{host:<24}]  {desc:<28}  {out.replace(chr(10),' ')[:65]}")

if s_unk:
    print("\n  >> UNKNOWN:")
    for host, desc, out in s_unk:
        print(f"     [{host:<24}]  {desc:<28}  {out.replace(chr(10),' ')[:65]}")

prob_hosts = Counter()
for host, desc, out in s_crit + s_warn:
    prob_hosts[host] += 1
if prob_hosts:
    print("\n  >> TOP HOST CON PROBLEMI:")
    for h, c in prob_hosts.most_common(8):
        print(f"     {h:<30}  {c:>2} problema/i  {'!' * c}")

print("\n" + "=" * 68)
