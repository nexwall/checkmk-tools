#!/usr/bin/env python3
"""Test check_host_status on real production hosts."""
import subprocess, concurrent.futures, time

PLUGIN = "/omd/sites/monitoring/local/lib/nagios/plugins/check_host_status"

TESTS = [
    # (label,              ip,              type,     extra_args)
    # --- Servers with CMK agent ---
    ("server-01",          "192.0.2.1",     "server",  ""),
    ("server-02",          "192.0.2.2",     "server",  ""),
    ("server-03",          "192.0.2.3",     "server",  ""),
    ("server-04",          "192.0.2.4",     "server",  ""),
    # --- Switches ---
    ("switch-01",          "192.0.2.10",    "switch",  ""),
    ("switch-02",          "192.0.2.11",    "switch",  ""),
    # --- Access Points ---
    ("ap-01",              "192.0.2.20",    "switch",  ""),
    ("ap-02",              "192.0.2.21",    "switch",  ""),
    # --- Clients (no agent) ---
    ("client-01",          "192.0.2.30",    "client",  ""),
    ("client-02",          "192.0.2.31",    "client",  ""),
    # --- NAS / Storage ---
    ("nas-01",             "192.0.2.40",    "server",  ""),
    ("nas-02",             "192.0.2.41",    "server",  ""),
    # --- Printers ---
    ("printer-01",         "192.0.2.50",    "generic", ""),
    ("printer-02",         "192.0.2.51",    "generic", ""),
    # --- Negative test: unreachable IP ---
    ("UNREACHABLE",        "192.0.2.254",   "client",  "--timeout 1"),
]

def run_check(label, ip, htype, extra):
    cmd = f"{PLUGIN} -H {ip} --type {htype} {extra}".strip()
    t0 = time.time()
    r = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=30)
    elapsed = time.time() - t0
    out = (r.stdout or r.stderr or "").strip().split("|")[0].strip()
    return label, htype, r.returncode, out, elapsed

STATE = {0: "OK  ", 1: "WARN", 2: "CRIT", 3: "UNK "}

print(f"\n{'='*90}")
print(f"  TEST check_host_status v2.3.0 - {len(TESTS)} host")
print(f"{'='*90}")
print(f"{'Host':<25} {'Type':<8} {'St':<5} {'Tempo':>6}  Output")
print(f"{'-'*90}")

with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
    futures = {ex.submit(run_check, *t): t for t in TESTS}
    results = []
    for f in concurrent.futures.as_completed(futures):
        try:
            results.append(f.result())
        except Exception as e:
            t = futures[f]
            results.append((t[0], t[2], 3, str(e), 0))

results.sort(key=lambda x: TESTS.index(next(t for t in TESTS if t[0]==x[0])))

ok = warn = crit = unk = 0
for label, htype, rc, out, elapsed in results:
    s = STATE.get(rc, "UNK ")
    if rc == 0: ok += 1
    elif rc == 1: warn += 1
    elif rc == 2: crit += 1
    else: unk += 1
    # truncate output if too long
    out_short = out[:60] + "..." if len(out) > 63 else out
    print(f"{label:<25} {htype:<8} {s:<5} {elapsed:>5.1f}s  {out_short}")

print(f"{'-'*90}")
print(f"  OK={ok}  WARN={warn}  CRIT={crit}  UNK={unk}")
print(f"{'='*90}\n")
