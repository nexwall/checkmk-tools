#!/usr/bin/python3
# test_telegram_channels.py - Test all Telegram notification channels on all monitoring servers
# Runs via WSL SSH on each server, reads env file, tests all channels, reports results

import subprocess
import sys
import base64
import json
import re

VERSION = "1.2.0"

# Servers to test: name, SSH host alias (from ~/.ssh/config in WSL), env file path
# Add "skip": True for password-only hosts (will print manual instructions instead)
SERVERS = [
    {
        "name": "srv-monitoring-sp",
        "host": "srv-monitoring-sp",
        "env": "/omd/sites/monitoring/etc/environment",
    },
    {
        "name": "checkmk-vps-01",
        "host": "checkmk-vps-01",
        "env": "/omd/sites/monitoring/etc/environment",
    },
    {
        "name": "checkmk-vps-02",
        "host": "checkmk-vps-02",
        "env": "/omd/sites/monitoring/etc/environment",
    },
    {
        "name": "srv-monitoring-us",
        "host": "root@195.223.159.26",
        "ssh_opts": "-J checkmk-vps-01 -p 2333 -i ~/.ssh/copilot_monitoring_us_root",
        "env": "/omd/sites/monitoring/etc/environment",
    },
]

# Remote Python script (runs on each server via base64)
REMOTE_SCRIPT = r"""
import re, urllib.request, urllib.parse, json, sys

env_file = sys.argv[1] if len(sys.argv) > 1 else "/omd/sites/monitoring/etc/environment"

try:
    with open(env_file) as f:
        content = f.read()
except Exception as e:
    print(json.dumps({"error": str(e)}))
    sys.exit(0)

def get_var(name):
    m = re.search(name + r'="?([^"\n\r]+)"?', content)
    if not m:
        return None
    return m.group(1).strip().strip('"')

token = get_var("TELEGRAM_TOKEN")
results = {
    "token_prefix": (token[:15] + "...") if token else None,
    "channels": {}
}

if not token:
    results["error"] = "TELEGRAM_TOKEN not found in " + env_file
    print(json.dumps(results))
    sys.exit(0)

# Collect all chat_id variables
chats = {}
for m in re.finditer(r'(TELEGRAM_\w*CHAT_ID)="?(-?\d+)"?', content):
    chats[m.group(1)] = m.group(2)

if not chats:
    results["error"] = "No TELEGRAM_*CHAT_ID found in " + env_file
    print(json.dumps(results))
    sys.exit(0)

for var, chat_id in sorted(chats.items()):
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": "[TEST] " + var + " OK - automated test"
    }).encode()
    try:
        r = urllib.request.urlopen(
            "https://api.telegram.org/bot" + token + "/sendMessage",
            data,
            timeout=10
        )
        results["channels"][var] = {"chat_id": chat_id, "status": "OK", "code": r.status}
    except urllib.error.HTTPError as e:
        results["channels"][var] = {"chat_id": chat_id, "status": "FAIL", "code": e.code, "reason": str(e.reason)}
    except Exception as e:
        results["channels"][var] = {"chat_id": chat_id, "status": "ERROR", "reason": str(e)}

print(json.dumps(results))
"""


## Utils

def ssh_run_script(host, script, env_file, timeout=30, ssh_opts=""):
    b64 = base64.b64encode(script.encode()).decode()
    opts = f"{ssh_opts} " if ssh_opts else ""
    ssh_cmd = f"ssh -o ConnectTimeout=10 -o BatchMode=yes {opts}{host} 'echo {b64} | base64 -d | python3 - {env_file}'"
    cmd = ["wsl", "-d", "kali-linux", "bash", "-c", ssh_cmd]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

def extract_json(text):
    # Try each line from the end looking for a valid JSON object
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                return json.loads(line)
            except Exception:
                pass
    # Fallback: try whole output
    try:
        return json.loads(text.strip())
    except Exception:
        return None

def print_server_result(server_name, rc, stdout, stderr):
    print()
    print(f"  {'='*54}")
    print(f"  Server: {server_name}")
    print(f"  {'='*54}")

    if rc != 0 or (not stdout and not stderr):
        print(f"  [SSH ERROR] rc={rc}")
        if stderr:
            print(f"  {stderr[:300]}")
        return

    data = extract_json(stdout)
    if data is None:
        print(f"  [PARSE ERROR] Output: {stdout[:200]}")
        return

    if "error" in data:
        print(f"  [ERROR] {data['error']}")
        return

    print(f"  Token:  {data.get('token_prefix', 'N/A')}")

    channels = data.get("channels", {})
    if not channels:
        print("  No channels found")
        return

    for var, info in sorted(channels.items()):
        status = info.get("status", "?")
        chat = info.get("chat_id", "?")
        if status == "OK":
            icon = "OK  "
            detail = ""
        else:
            icon = "FAIL"
            detail = f" ({info.get('code', '')} {info.get('reason', '')})"
        print(f"  [{icon}] {var:<35} chat={chat}{detail}")


## Main

def main():
    print(f"Telegram Channel Test v{VERSION}")
    print(f"Testing {len(SERVERS)} server configurations...")

    summary_ok = 0
    summary_fail = 0

    for srv in SERVERS:
        try:
            rc, stdout, stderr = ssh_run_script(
                srv["host"], REMOTE_SCRIPT, srv["env"],
                ssh_opts=srv.get("ssh_opts", "")
            )
            print_server_result(srv["name"], rc, stdout, stderr)

            # Count for summary
            data = extract_json(stdout) if stdout else None
            if data and "channels" in data:
                for info in data["channels"].values():
                    if info.get("status") == "OK":
                        summary_ok += 1
                    else:
                        summary_fail += 1

        except subprocess.TimeoutExpired:
            print()
            print(f"  [TIMEOUT] {srv['name']}")
            summary_fail += 1
        except Exception as e:
            print()
            print(f"  [EXCEPTION] {srv['name']}: {e}")
            summary_fail += 1

    print()
    print(f"  {'='*54}")
    print(f"  SUMMARY: {summary_ok} OK  |  {summary_fail} FAIL")
    print(f"  {'='*54}")
    print()


main()
