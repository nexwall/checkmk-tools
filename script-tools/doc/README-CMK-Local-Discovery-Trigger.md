# CMK Local Discovery Trigger Installation Guide

## Objective

This guide installs and configures the trigger that:

- read local checks from `cmk -d <host>`
- detect differences (`new` / `vanished` / hash)
- runs discovery only when needed
- writes unified log to `/var/log/checkmk_server_autoheal.log`

Supports full server-side installation and host-side prerequisites.

## Prerequisites

- CheckMK server with repository present in `/opt/checkmk-tools`
- Python 3 available on the server
- Root or sudo access
- Monitored hosts already configured in CheckMK

## Server-side installation

### Quick mode (recommended)

```bash
# Zero arguments: auto-detect site/user/group + production preset (5 min timer)
python3 /opt/checkmk-tools/script-tools/full/sync_update/install-cmk-local-discovery-trigger.py

# Quick preset explicit variant
python3 /opt/checkmk-tools/script-tools/full/sync_update/install-cmk-local-discovery-trigger.py --quick
```

### 1) Update repository

```bash
cd /opt/checkmk-tools
git pull
```

### 2) Install/update service and timer

```bash
python3 /opt/checkmk-tools/script-tools/full/sync_update/install-cmk-local-discovery-trigger.py \
  --site monitoring \
  --run-as-user monitoring \
  --run-as-group monitoring \
  --interval-min 5 \
  --agent-timeout 90 \
  --log-file /var/log/checkmk_server_autoheal.log

# Optional: include git installation + auto sync git setup
python3 /opt/checkmk-tools/script-tools/full/sync_update/install-cmk-local-discovery-trigger.py \
  --site monitoring \
  --run-as-user monitoring \
  --run-as-group monitoring \
  --interval-min 5 \
  --agent-timeout 90 \
  --log-file /var/log/checkmk_server_autoheal.log \
  --setup-auto-sync-git \
  --auto-sync-interval-sec 60 \
  --repo-dir /opt/checkmk-tools \
  --auto-sync-log-file /var/log/auto-git-sync.log
```

### 3) Restart timer and start a run

```bash
systemctl restart checkmk-local-discovery-trigger.timer
systemctl start --no-block checkmk-local-discovery-trigger.service
```

### 4) Check status

```bash
systemctl status checkmk-local-discovery-trigger.timer --no-pager -l
systemctl status checkmk-local-discovery-trigger.service --no-pager -l
```

### 5) Check log

```bash
tail -n 100 -f /var/log/checkmk_server_autoheal.log
```

## Host side configuration

Server-side triggering only works if hosts display valid local checks.

### Host-side installation (recommended)

On each monitored host it is best to keep `/opt/checkmk-tools` updated with auto sync git.

```bash
cd /opt/checkmk-tools
git pull

# Dedicated installer host for auto sync git repository
python3 /opt/checkmk-tools/script-tools/full/installation/install-auto-git-sync.py

# Check auto sync service on host
systemctl status auto-git-sync.service --no-pager -l
tail -n 100 /var/log/auto-git-sync.log
```

If you use Python local checks from the repository on your host, you can also install sync checks:

```bash
# Zero arguments: automatic installation with default safe
python3 /opt/checkmk-tools/script-tools/full/sync_update/install-python-full-sync.py

# Explicit fast mode variant
python3 /opt/checkmk-tools/script-tools/full/sync_update/install-python-full-sync.py --quick

systemctl status checkmk-python-full-sync.timer --no-pager -l
```

If the host does not use systemd, the host installer automatically sets up cron fallbacks every 5 minutes.

### Host requirements

- Agent CheckMK reachable from the server
- Script local checks present in the correct host folder
- Executable scripts
- Output local check in standard CheckMK format

Expected format for each local check line:

```text
<STATE> <SERVICE_NAME> - <message>
```

### Typical path local checks on Linux hosts

```text
/usr/lib/check_mk_agent/local/
```

### Quick host test from CheckMK server

```bash
cmk -d <HOSTNAME>
cmk -D <HOSTNAME>
```

If `cmk -d` contains no `<<<local>>>` section, the trigger will not find local services on that host.

## Auto sync git integration (embedded)

If you use `--setup-auto-sync-git`, the installer:

- install `git` if missing (apt/dnf/yum)
- create/update `auto-git-sync.service`
- enable and start the auto sync service
- configure log in `/var/log/auto-git-sync.log`

Quick check:

```bash
systemctl status auto-git-sync.service --no-pager -l
tail -n 100 /var/log/auto-git-sync.log
```

## What you will see in the log

Useful examples:

- `Probe OK: <host> (rc=0)`
- `New local services on <host>: ...`
- `Local services vanished on <host>: ...`
- `No change: <host>`
- `cmk -d timeout ...`
- `Done: changed=..., discovery_ok=..., unchanged=...`

## Tuning recommended

Balanced parameters (production):

- `--interval-min 5`
- `--agent-timeout 90`

For very slow environments you can increase `--agent-timeout`.

## Quick troubleshooting

### Error copying command with parentheses

If an error like this appears:

```text
-bash: syntax error near unexpected token `('
```

you pasted a markdown link instead of a shell command.

Always use real path, for example:

```bash
python3 /opt/checkmk-tools/script-tools/full/sync_update/install-cmk-local-discovery-trigger.py --help
```

### Log file missing

```bash
touch /var/log/checkmk_server_autoheal.log
chown monitoring:monitoring /var/log/checkmk_server_autoheal.log
chmod 664 /var/log/checkmk_server_autoheal.log
```

### Service seems "stuck"

With `Type=oneshot` it is normal to see `activating` during the loop.

Live verification:

```bash
journalctl -u checkmk-local-discovery-trigger.service -f
```

## Future update

To update to new versions:

```bash
cd /opt/checkmk-tools
git pull
python3 /opt/checkmk-tools/script-tools/full/sync_update/install-cmk-local-discovery-trigger.py --site monitoring --run-as-user monitoring --run-as-group monitoring --interval-min 5 --agent-timeout 90 --log-file /var/log/checkmk_server_autoheal.log
```