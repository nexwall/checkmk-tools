import socket, subprocess, time

s = socket.socket(socket.AF_UNIX)
s.connect('/omd/sites/monitoring/tmp/run/live')
s.send(b'GET services\nFilter: host_filename ~ /wato/clients/\nFilter: plugin_output ~ active check\nColumns: host_name\nOutputFormat: python3\n')
s.shutdown(socket.SHUT_WR)
data = eval(s.makefile().read())
hosts = sorted(set(row[0] for row in data))
print(f"Hosts to fix: {len(hosts)}")
for i, host in enumerate(hosts):
    try:
        subprocess.run(['cmk', '--check', host], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT (skipped): {host}")
    if i % 5 == 0:
        print(f"  {i+1}/{len(hosts)} - {host}")
    time.sleep(0.3)
print("Done")
