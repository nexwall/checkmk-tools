#!/usr/bin/env pwsh
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#
# monitor_jobs.ps1 - Background jobs and daily baseline checks for monitoring servers
#
# Usage:
#   .\copilot\monitor_jobs.ps1 daily [sp|us|vps01|vps02|ubnt|all]
#   .\copilot\monitor_jobs.ps1 notify [sp|us|vps01|vps02|ubnt|all] [-Minutes 60] [-Interval 15]
#   .\copilot\monitor_jobs.ps1 status
#   .\copilot\monitor_jobs.ps1 stop

param(
    [Parameter(Position=0)][string]$Command = "help",
    [Parameter(Position=1)][string]$Target  = "all",
    [int]$Minutes  = 60,
    [int]$Interval = 15
)

$VERSION   = "1.8.3"
$WORKSPACE = Split-Path -Parent $PSScriptRoot
$LOG_FILE  = Join-Path $WORKSPACE "monitor-jobs.log"

$SSH_HOSTS = @{
    sp    = "srv-monitoring-sp"
    us    = "srv-monitoring-us"
    vps01 = "checkmk-vps-01-c"
    vps02 = "checkmk-vps-02-c"
    ubnt  = "ubntmarzio-root"
}

# --- Remote Python script for daily checks ---
$DAILY_PY = @'
import subprocess, datetime, urllib.request, socket, os, time

def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)

def sec(t):
    print(f"\n{'='*55}\n  {t}\n{'='*55}")

# SYSTEM
sec("SYSTEM")
_, out = run(["hostname", "-f"])
print(f"  Hostname: {out}")
_, out = run(["uptime", "-p"])
print(f"  Uptime:   {out}")

# CPU load
rc, out = run(["cat", "/proc/loadavg"])
if rc == 0:
    parts = out.split()
    load1, load5, load15 = parts[0], parts[1], parts[2]
    rc2, cpuout = run(["nproc"])
    ncpu = int(cpuout.strip()) if rc2 == 0 and cpuout.strip().isdigit() else 1
    warn = " !!!" if float(load1) > ncpu * 1.5 else ""
    print(f"  CPU load: {load1} / {load5} / {load15} (1m/5m/15m, {ncpu} cores){warn}")

# Active PIDs
rc, out = run(["bash", "-c", "ps aux --no-headers | wc -l"])
if rc == 0:
    print(f"  PIDs:     {out.strip()} active processes")

# Memory
rc, out = run(["free", "-m"])
rows = [r for r in out.split("\n") if r.strip()]
if len(rows) > 1:
    row = rows[1].split()
    if len(row) >= 7:
        total_mb, used_mb, free_mb, avail_mb = int(row[1]), int(row[2]), int(row[3]), int(row[6])
        pct = int(used_mb * 100 / total_mb) if total_mb > 0 else 0
        warn = " !!!" if pct > 85 else ""
        print(f"  Memory:   {used_mb}M used / {total_mb}M total ({pct}% used, {avail_mb}M avail){warn}")

# Disk all mountpoints
rc, out = run(["df", "-h", "--output=target,size,used,avail,pcent"])
if rc == 0:
    rows = [r for r in out.split("\n") if r.strip()]
    for row in rows[1:]:
        parts = row.split()
        if len(parts) >= 5:
            mnt, size, used, avail, pct_s = parts[0], parts[1], parts[2], parts[3], parts[4]
            if not any(x in mnt for x in ["/sys", "/proc", "/dev", "/run", "/snap"]):
                pct_n = int(pct_s.replace("%","")) if pct_s.replace("%","").isdigit() else 0
                warn = " !!!" if pct_n > 85 else ""
                print(f"  Disk {mnt}: {used}/{size} ({pct_s} used, {avail} free){warn}")

# OMD STATUS
sec("OMD STATUS")
rc, out = run(["omd", "status", "monitoring"])
for line in out.split("\n"):
    line = line.strip()
    if not line:
        continue
    prefix = "!!! " if "stopped" in line.lower() and "Overall" not in line else ""
    print(f"  {prefix}{line}")

# KEY SERVICES
sec("KEY SERVICES")
for svc in ["cron", "systemd-resolved", "rsyslog", "fail2ban"]:
    rc, out = run(["systemctl", "is-active", svc])
    mark = "" if rc == 0 else "  !!!"
    print(f"  {svc}: {out.strip()}{mark}")

# STOPPED SERVICES (all failed/inactive)
sec("STOPPED SERVICES (systemctl --failed)")
rc, out = run(["systemctl", "--failed", "--no-legend", "--no-pager"])
lines = [l.strip() for l in out.split("\n") if l.strip() and "0 loaded" not in l]
if lines:
    for l in lines:
        print(f"  !!! {l}")
else:
    print("  none")

# CRONTAB root
sec("CRONTAB (root)")
rc, out = run(["crontab", "-l"])
lines = [l for l in out.split("\n") if l.strip() and not l.startswith("#")]
if lines:
    for l in lines:
        print(f"  {l}")
else:
    print("  (none)")

# CRONTAB monitoring user
sec("CRONTAB (monitoring user)")
rc, out = run(["su", "-", "monitoring", "-c", "crontab -l"])
lines = [l for l in out.split("\n") if l.strip() and not l.startswith("#")]
if lines:
    for l in lines:
        print(f"  {l}")
else:
    print("  (none)")

# REPO
sec("REPO /opt/checkmk-tools")
rc, out = run(["git", "-C", "/opt/checkmk-tools", "log", "--oneline", "-1"])
print(f"  Last commit:  {out if rc == 0 else 'NOT FOUND - repo missing?'}")
rc, out = run(["git", "-C", "/opt/checkmk-tools", "status", "--short"])
print(f"  Working tree: {'clean' if not out.strip() else out.strip()}")
rc, out = run(["git", "-C", "/opt/checkmk-tools", "remote", "get-url", "origin"])
print(f"  Remote:       {out if rc == 0 else '?'}")
rc, out = run(["stat", "-c", "%y", "/opt/checkmk-tools/.git/FETCH_HEAD"])
if rc == 0:
    print(f"  Last pull:    {out.split('.')[0]}")

# LOCAL CHECKS
sec("LOCAL CHECKS (/usr/lib/check_mk_agent/local)")
rc, out = run(["ls", "/usr/lib/check_mk_agent/local/"])
files = [f for f in out.split("\n") if f.strip() and f != "__pycache__"]
print(f"  Deployed: {len(files)} checks")
for f in sorted(files):
    print(f"    {f}")

# OWNERSHIP CHECK
sec("OWNERSHIP CHECK")
# Files in /omd/sites/monitoring NOT owned by monitoring
rc, out = run(["bash", "-c",
    "find /omd/sites/monitoring -maxdepth 6"
    " ! -user monitoring"
    " ! -path '*/__pycache__/*'"
    " ! -path '*/.git/*'"
    " ! -path '*/tmp/*'"
    " ! -path '/omd/sites/monitoring/.config'"
    " ! -path '/omd/sites/monitoring/.config/*'"
    " 2>/dev/null | head -30"])
bad_mon = [l.strip() for l in out.split("\n") if l.strip()]
if bad_mon:
    print(f"  !!! {len(bad_mon)} file/dir in /omd/sites NOT owned by monitoring:")
    for f in bad_mon[:10]:
        rc2, stat_out = run(["stat", "-c", "%U:%G  %n", f])
        print(f"    !!! {stat_out if rc2 == 0 else f}")
    if len(bad_mon) > 10:
        print(f"    ... ({len(bad_mon)-10} more, run find manually for full list)")
else:
    print("  /omd/sites/monitoring: all files monitoring:monitoring OK")
# Notification scripts: explicit check
rc, out = run(["bash", "-c",
    "stat -c '%U:%G  %n'"
    " /omd/sites/monitoring/local/share/check_mk/notifications/*"
    " 2>/dev/null | grep -v '^monitoring:monitoring'"])
bad_notif = [l.strip() for l in out.split("\n") if l.strip()]
if bad_notif:
    for l in bad_notif:
        print(f"  !!! notifications: {l}")
else:
    print("  notifications/: all monitoring:monitoring OK")
# /opt/checkmk-tools must be root:root
rc, out = run(["stat", "-c", "%U:%G", "/opt/checkmk-tools"])
if rc == 0:
    owner = out.strip()
    mark = "OK" if owner == "root:root" else "!!! expected root:root"
    print(f"  /opt/checkmk-tools: {owner}  {mark}")
else:
    print("  /opt/checkmk-tools: NOT FOUND !!!")

# BACKUP CHECK - cloud (rclone DO bucket)
sec("BACKUP CHECK (cloud DO bucket)")
hostname = socket.gethostname()
try:
    # fast: list top-level dirs only
    r_lsd = subprocess.run(
        ["su", "-", "monitoring", "-c", "rclone lsd do:testmonbck/ 2>&1"],
        capture_output=True, text=True, timeout=15
    )
    lsd = (r_lsd.stdout + r_lsd.stderr).strip()
    dirs = [l.split()[-1] for l in lsd.split("\n") if l.strip() and not l.startswith("ERROR")]
    # find longest dir name that is a prefix of this hostname
    matches = [d for d in dirs if hostname.startswith(d)]
    best = max(matches, key=len) if matches else None
    if best:
        r_lsl = subprocess.run(
            ["bash", "-c",
             f"su - monitoring -c 'rclone lsl do:testmonbck/{best}/monitoring/ 2>&1 | grep mkbackup.info | sort | tail -5'"],
            capture_output=True, text=True, timeout=30
        )
        lsl = (r_lsl.stdout + r_lsl.stderr).strip()
        if lsl and "ERROR" not in lsl:
            print(f"  Latest in do:testmonbck/{best}/monitoring/:")
            for l in lsl.split("\n"):
                if l.strip():
                    parts = l.strip().split()
                    date_part = parts[1] if len(parts) >= 3 else ""
                    name = parts[-1].split("/")[0] if parts else ""
                    print(f"    {date_part}  {name[:80]}")
        else:
            print(f"  !!! rclone lsl failed: {lsl[:150]}")
    else:
        print(f"  !!! no DO folder matches hostname '{hostname}'")
        print(f"  Available: {dirs}")
except Exception as e:
    print(f"  !!! rclone error: {e}")

# TELEGRAM CONNECTIVITY
sec("TELEGRAM CONNECTIVITY")
try:
    r = urllib.request.urlopen("https://api.telegram.org", timeout=5)
    print(f"  api.telegram.org: OK (http {r.status})")
except Exception as e:
    print(f"  api.telegram.org: FAIL !!!  ({e})")

# FALLBACK DNS
rc2, dns_out = run(["resolvectl", "status"])
fallback = [l.strip() for l in dns_out.split("\n") if "Fallback" in l]
if fallback:
    print(f"  FallbackDNS: {fallback[0]}")
else:
    print("  FallbackDNS: !!! NOT CONFIGURED")

# NOTIFY LOG - ERRORS last 24h
sec("NOTIFY LOG - ERRORS (last 24h)")
log_path = "/omd/sites/monitoring/var/log/notify.log"
try:
    today     = datetime.date.today().strftime("%Y-%m-%d")
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    with open(log_path) as f:
        lines = f.readlines()
    errors = [
        l.strip() for l in lines
        if (today in l or yesterday in l)
        and any(k in l for k in ["ERROR", "Traceback", "Unauthorized", "FAIL", "failed"])
    ]
    print(f"  Error count (24h): {len(errors)}")
    for e in errors[-5:]:
        print(f"    {e[:120]}")
except Exception as e:
    print(f"  Cannot read log: {e}")

# CHECKMK STATUS (LiveStatus)
sec("CHECKMK STATUS (LiveStatus)")
def live(q):
    try:
        s = socket.socket(socket.AF_UNIX)
        s.connect("/omd/sites/monitoring/tmp/run/live")
        s.send((q + "\n").encode())
        s.shutdown(socket.SHUT_WR)
        return s.makefile().read().strip()
    except Exception as e:
        return f"ERROR: {e}"
h_ok   = live("GET hosts\nFilter: state = 0\nStats: state = 0\n")
h_down = live("GET hosts\nFilter: state != 0\nStats: state >= 0\n")
s_ok   = live("GET services\nFilter: state = 0\nStats: state = 0\n")
s_warn = live("GET services\nFilter: state = 1\nStats: state >= 0\n")
s_crit = live("GET services\nFilter: state = 2\nStats: state >= 0\n")
s_unkn = live("GET services\nFilter: state = 3\nStats: state >= 0\n")
stale  = live("GET services\nFilter: staleness > 1.5\nStats: state >= 0\n")
h_down_n = int(h_down) if h_down.isdigit() else 0
s_crit_n = int(s_crit) if s_crit.isdigit() else 0
stale_n  = int(stale)  if stale.isdigit()  else 0
print(f"  Hosts:    OK={h_ok}  DOWN={h_down_n}{'  !!!' if h_down_n > 0 else ''}")
print(f"  Services: OK={s_ok}  WARN={s_warn}  CRIT={s_crit_n}{'  !!!' if s_crit_n > 0 else ''}  UNKN={s_unkn}")
print(f"  Stale >1.5: {stale_n}{'  !!!' if stale_n > 0 else '  OK'}")
# unacknowledged CRIT
unack = live("GET services\nFilter: state = 2\nFilter: acknowledged = 0\nFilter: host_acknowledged = 0\nStats: state >= 0\n")
unack_n = int(unack) if unack.isdigit() else 0
print(f"  Unacked CRIT: {unack_n}{'  !!!' if unack_n > 0 else '  OK'}")
# stalled services: not updated for >10 min
t10 = int(time.time()) - 600
stall_all = live(f"GET services\nFilter: last_check < {t10}\nStats: state >= 0\n")
stall_nok = live(f"GET services\nFilter: last_check < {t10}\nFilter: state != 0\nStats: state >= 0\n")
stall_n = int(stall_nok) if str(stall_nok).isdigit() else 0
stall_a = int(stall_all) if str(stall_all).isdigit() else 0
warn_s = "  !!!" if stall_n > 0 else "  OK"
print(f"  Stall >10min: {stall_a} total, {stall_n} non-OK{warn_s}")
if stall_n > 0:
    top = live(f"GET services\nColumns: host_name description state last_check\nFilter: last_check < {t10}\nFilter: state != 0\nOutputFormat: csv\n")
    for row in top.split("\n")[:5]:
        parts = row.split(";")
        if len(parts) == 4:
            h, svc, st, lc = parts
            age_min = int((time.time() - int(lc)) / 60) if lc.isdigit() else "?"
            state_str = {"0": "OK", "1": "WARN", "2": "CRIT", "3": "UNKN"}.get(st, st)
            print(f"    !!! {h} | {svc} | {state_str} | last check {age_min}min ago")

# LAST SUCCESSFUL NOTIFICATION
sec("LAST SUCCESSFUL NOTIFICATION")
log_path = "/omd/sites/monitoring/var/log/notify.log"
try:
    rc, out = run(["bash", "-c",
        f"grep 'Telegram OK' {log_path} 2>/dev/null | tail -1"])
    if out.strip():
        print(f"  Last OK: {out.strip()[:120]}")
    else:
        print("  !!! No successful Telegram notification found in log")
except Exception as e:
    print(f"  !!! error: {e}")

# NOTIFICATION BULK QUEUE
bulk_dir = "/omd/sites/monitoring/var/check_mk/notify/bulk"
try:
    files = [f for f in os.listdir(bulk_dir) if not f.startswith(".")]
    if files:
        print(f"  !!! Bulk queue: {len(files)} pending notifications")
        for f in files[:5]:
            print(f"    {f}")
    else:
        print("  Bulk queue: empty OK")
except Exception:
    print("  Bulk queue: dir not present (OK)")

# CHECKMK VERSION
sec("CHECKMK VERSION")
rc, out = run(["bash", "-c", "su - monitoring -c 'omd version' 2>&1"])
if rc == 0:
    print(f"  {out.strip()}")
else:
    print(f"  !!! {out.strip()[:100]}")
# auto-upgrade log (last 5 lines)
rc, out = run(["bash", "-c",
    "tail -5 /var/log/auto-upgrade-checkmk.log 2>/dev/null || echo 'NOT FOUND'"])
for l in out.strip().split("\n"):
    if l.strip():
        print(f"  upgrade-log: {l.strip()[:100]}")
# auto-update (OS packages) last run
rc, out = run(["bash", "-c",
    "grep -E 'Starting auto-update|Completed' /var/log/auto-updates.log 2>/dev/null | tail -2 || echo 'NOT FOUND'"])
for l in out.strip().split("\n"):
    if l.strip():
        print(f"  auto-update: {l.strip()[:100]}")

# SSL CERTIFICATE
sec("SSL CERTIFICATE")
try:
    r = subprocess.run(
        ["bash", "-c",
         "echo | openssl s_client -connect localhost:443 -servername localhost 2>/dev/null"
         " | openssl x509 -noout -enddate 2>/dev/null"],
        capture_output=True, text=True, timeout=10
    )
    out = (r.stdout + r.stderr).strip()
    if "notAfter" in out:
        date_str = out.split("=", 1)[1].strip()
        from datetime import datetime as dt
        exp = dt.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
        now_utc = dt.now(datetime.timezone.utc).replace(tzinfo=None)
        days_left = (exp - now_utc).days
        warn = "  !!!" if days_left < 30 else ""
        print(f"  HTTPS cert expires: {date_str} ({days_left} days left){warn}")
    else:
        print(f"  !!! Could not read cert: {out[:100]}")
except Exception as e:
    print(f"  !!! SSL check error: {e}")

# SECURITY - SSH failed logins (24h)
sec("SECURITY")
rc, out = run(["bash", "-c",
    "journalctl -u ssh -u sshd --since '24 hours ago' 2>/dev/null"
    " | grep -c 'Failed password' || echo 0"])
failed_n = int(out.strip()) if out.strip().isdigit() else 0
warn = "  !!!" if failed_n > 50 else ""
print(f"  SSH failed logins (24h): {failed_n}{warn}")
# listening ports
rc, out = run(["bash", "-c",
    "ss -tlnp 2>/dev/null | grep -E ':80|:443|:8080|:5000' | awk '{print $4}'"])
ports = [p.strip() for p in out.split("\n") if p.strip()]
print(f"  Listening: {', '.join(ports) if ports else '!!! none of 80/443/8080/5000 open'}")

# RRD STORAGE
sec("RRD STORAGE")
for rrd_dir in ["/omd/sites/monitoring/var/check_mk/rrd",
                "/omd/sites/monitoring/var/pnp4nagios"]:
    rc, out = run(["du", "-sh", rrd_dir])
    if rc == 0:
        size = out.split()[0]
        print(f"  {rrd_dir}: {size}")
        break
else:
    print("  !!! RRD directory not found")

# CORE RESTARTS (last 7d)
rc, out = run(["bash", "-c",
    "journalctl -u nagios -u naemon -u cmc --since '7 days ago' 2>/dev/null"
    " | grep -cE 'Started|started|restarted|restart' || echo 0"])
restarts = out.strip().split()[0] if out.strip() else "0"
print(f"  Core restarts (7d): {restarts}")

# YDEA CACHE FRESHNESS
sec("YDEA CACHE FRESHNESS")
for cf in ["ydea_checkmk_tickets.json", "ydea_checkmk_flapping.json"]:
    path = f"/opt/ydea-toolkit/cache/{cf}"
    try:
        mtime = os.path.getmtime(path)
        age_min = int((time.time() - mtime) / 60)
        size = os.path.getsize(path)
        # tickets: if {} (empty) → no open tickets, age irrelevant
        if cf == "ydea_checkmk_tickets.json":
            if size <= 2:
                print(f"  {cf}: 0 tickets (OK, no open tickets)")
            else:
                warn = "  !!!" if age_min > 120 else ""
                print(f"  {cf}: {size}B, updated {age_min}min ago{warn}")
        else:
            # flapping: updated only on real events, flag only if >24h
            warn = "  !!!" if age_min > 1440 else ""
            print(f"  {cf}: {size}B, updated {age_min}min ago{warn}")
    except Exception:
        print(f"  !!! NOT FOUND: {path}")
# ydea health log last entry
rc, out = run(["bash", "-c",
    "tail -3 /var/log/ydea_health.log 2>/dev/null || echo 'NOT FOUND'"])
for l in out.strip().split("\n"):
    if l.strip():
        print(f"  health.log: {l.strip()[:100]}")

# BACKUP AGE
sec("BACKUP AGE")
rc, tgt_out = run(["su", "-", "monitoring", "-c", "mkbackup targets 2>&1"])
target_ids = []
if rc == 0:
    for l in tgt_out.strip().split("\n")[2:]:
        if l.strip():
            target_ids.append(l.split()[0])
if target_ids:
    for tid in target_ids[:3]:
        rc2, lst = run(["su", "-", "monitoring", "-c", f"mkbackup list {tid} 2>&1"])
        if rc2 == 0 and lst.strip():
            # parse most recent Finished timestamp
            import re
            finished = re.findall(r'Finished:\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', lst)
            sizes    = re.findall(r'Size:\s+([\d.]+ \w+)', lst)
            if finished:
                last_fin = finished[0]
                last_size = sizes[0] if sizes else "?"
                from datetime import datetime as dt2
                fin_dt = dt2.strptime(last_fin, "%Y-%m-%d %H:%M:%S")
                now_utc2 = dt2.now(datetime.timezone.utc).replace(tzinfo=None)
                age_h = round((now_utc2 - fin_dt).total_seconds() / 3600, 1)
                warn = "  !!!" if age_h > 26 else ""
                print(f"  [{tid}] last backup: {last_fin}  size: {last_size}  age: {age_h}h{warn}")
                if len(finished) > 1:
                    prev_size = sizes[1] if len(sizes) > 1 else "?"
                    print(f"  [{tid}] prev backup: {finished[1]}  size: {prev_size}")
            else:
                print(f"  [{tid}] !!! cannot parse backup timestamp")
        else:
            print(f"  [{tid}] !!! {lst[:100]}")
else:
    print("  !!! mkbackup targets unavailable")

print(f"\n{'='*55}\n  CHECK COMPLETE\n{'='*55}\n")
'@

# --- Helper functions ---

function Get-Hosts {
    if ($Target -eq "all") { return $SSH_HOSTS.Keys | Sort-Object }
    if ($SSH_HOSTS.ContainsKey($Target)) { return @($Target) }
    Write-Host "Unknown target '$Target'. Use: sp, us, vps01, vps02, ubnt, all" -ForegroundColor Red
    exit 1
}

function Invoke-Daily {
    $b64      = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($DAILY_PY))
    $hostKeys = @(Get-Hosts)
    $sshHosts = $SSH_HOSTS

    # launch all hosts in parallel
    $jobs = @{}
    foreach ($key in $hostKeys) {
        $alias = $sshHosts[$key]
        $jobs[$key] = Start-Job -ScriptBlock {
            param($alias, $b64)
            wsl -d kali-linux bash -c "ssh $alias 'echo $b64 | base64 -d | python3 2>&1'" 2>&1
        } -ArgumentList $alias, $b64
    }

    Write-Host "Running checks in parallel on: $($hostKeys -join ', ')..." -ForegroundColor Yellow

    # collect results in original order
    foreach ($key in $hostKeys) {
        $alias = $sshHosts[$key]
        $out   = Receive-Job -Job $jobs[$key] -Wait -AutoRemoveJob
        Write-Host "`n$('#'*60)" -ForegroundColor Cyan
        Write-Host "  DAILY CHECK: $($key.ToUpper()) - $alias" -ForegroundColor Cyan
        Write-Host "$('#'*60)" -ForegroundColor Cyan
        Write-Host ($out -join "`n")
    }
}

function Invoke-NotifyMonitor {
    $hosts    = @(Get-Hosts)
    $sshHosts = $SSH_HOSTS
    $logFile  = $LOG_FILE
    $mins     = $Minutes
    $ivl      = $Interval
    $jobName  = "NotifyMonitor_$(Get-Date -Format 'HHmm')"

    $null = Start-Job -Name $jobName -ScriptBlock {
        param($hosts, $sshHosts, $mins, $ivl, $logFile)
        $total = [math]::Ceiling($mins / $ivl)
        $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Add-Content $logFile ""
        Add-Content $logFile "[$ts] === MONITOR STARTED - hosts: $($hosts -join ',') - ${mins}min every ${ivl}min ==="
        for ($i = 0; $i -le $total; $i++) {
            $ts = Get-Date -Format "HH:mm:ss"
            Add-Content $logFile "[$ts] --- check $($i+1)/$($total+1) ---"
            foreach ($key in $hosts) {
                $alias = $sshHosts[$key]
                $out = wsl -d kali-linux bash -c "ssh $alias 'tail -30 /omd/sites/monitoring/var/log/notify.log 2>/dev/null | grep -E ""ERROR|Traceback|Unauthorized|Telegram OK|failed"" | tail -5'" 2>&1
                $line = if ($out) { ($out -join " ").Trim() } else { "OK - no errors" }
                Add-Content $logFile "  [$($key.ToUpper())] $line"
            }
            Add-Content $logFile ""
            if ($i -lt $total) { Start-Sleep -Seconds ($ivl * 60) }
        }
        Add-Content $logFile "[$( Get-Date -Format 'HH:mm:ss')] === MONITOR COMPLETED ==="
    } -ArgumentList $hosts, $sshHosts, $mins, $ivl, $logFile

    Write-Host "Monitor job started: $jobName" -ForegroundColor Green
    Write-Host "  Servers:   $($hosts -join ', ')"
    Write-Host "  Duration:  $Minutes min, check every $Interval min"
    Write-Host "  Total:     $([math]::Ceiling($Minutes / $Interval) + 1) checks"
    Write-Host "  Log:       $LOG_FILE"
    Write-Host "`nRun '.\copilot\monitor_jobs.ps1 status' to follow progress"
}

function Show-Status {
    Write-Host "`n=== RUNNING JOBS ===" -ForegroundColor Cyan
    $jobs = Get-Job | Where-Object { $_.Name -like "NotifyMonitor*" }
    if ($jobs) {
        $jobs | Format-Table Id, Name, State, HasMoreData -AutoSize
    } else {
        Write-Host "  No monitor jobs running"
    }
    Write-Host "`n=== RECENT LOG (last 40 lines) ===" -ForegroundColor Cyan
    if (Test-Path $LOG_FILE) {
        Get-Content $LOG_FILE -Tail 40
    } else {
        Write-Host "  No log file yet ($LOG_FILE)"
    }
}

function Stop-AllJobs {
    $jobs = Get-Job | Where-Object { $_.Name -like "NotifyMonitor*" }
    if ($jobs) {
        $jobs | Stop-Job
        $jobs | Remove-Job
        Write-Host "Stopped $($jobs.Count) job(s)" -ForegroundColor Yellow
    } else {
        Write-Host "No monitor jobs running"
    }
}

# --- Main ---
switch ($Command.ToLower()) {
    "daily"  { Invoke-Daily }
    "notify" { Invoke-NotifyMonitor }
    "status" { Show-Status }
    "stop"   { Stop-AllJobs }
    default  {
        Write-Host "monitor_jobs.ps1 v$VERSION"
        Write-Host ""
        Write-Host "Usage:"
        Write-Host "  .\copilot\monitor_jobs.ps1 daily  [sp|us|vps01|vps02|all]"
        Write-Host "  .\copilot\monitor_jobs.ps1 notify [sp|us|vps01|vps02|all] [-Minutes 60] [-Interval 15]"
        Write-Host "  .\copilot\monitor_jobs.ps1 status"
        Write-Host "  .\copilot\monitor_jobs.ps1 stop"
        Write-Host ""
        Write-Host "Daily checks include:"
        Write-Host "  system (uptime, disk, memory)"
        Write-Host "  OMD status (all components)"
        Write-Host "  key services + stopped services"
        Write-Host "  crontab (root + monitoring user)"
        Write-Host "  repo /opt/checkmk-tools (commit, status, last pull)"
        Write-Host "  ownership check (omd site files + notifications must be monitoring:monitoring)"
        Write-Host "  deployed local checks"
        Write-Host "  Telegram connectivity + FallbackDNS"
        Write-Host "  notify log errors (last 24h)"
    }
}
