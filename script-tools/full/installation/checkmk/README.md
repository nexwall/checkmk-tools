# checkmk (Python)

Re-implementation in Python of what is present in `install-cmk8/install-cmk/` (bootstrap + modules 10/15/20/...).

## Usage (Ubuntu)

```bash
cd /opt/checkmk-tools/script-tools/full/installation/checkmk

# Menu (recommended)
./installer.py

# Guided setup: generate .env without having to edit it by hand
./installer.py init --interactive

# Alternatively (manual):
# cp .env.example /etc/checkmk-installer.env
```

The env file lives at `/etc/checkmk-installer.env` by default (`--env-file` to override) - deliberately outside `/opt/checkmk-tools`, since that directory is kept in sync by auto-git-sync and a stray sync mechanism can run `git clean -fd` on it before being reconciled away, which would wipe an in-repo env file.

```bash

# Complete installation (run with sudo)
sudo -E ./installer.py bootstrap

# Check
sudo -E ./installer.py verify

# Complete removal (uninstall)
sudo -E ./installer.py remove-all
```

Note: `bootstrap`, `certbot` and `verify` explicitly require root (`sudo -E`).

Tip: Non-interactive mode makes sense if `.env` is already complete.
For this use `./installer.py init --interactive` only once, then you can relaunch `bootstrap` without prompt.

During `bootstrap` also comes:

- installed `git` and `python3-pip`
- deployed OS-aware local checks in `/usr/lib/check_mk_agent/local` (via `script-tools/full/deploy/auto-deploy-checks.py`)
- installed and enabled `auto-git-sync.service` (sync of `/opt/checkmk-tools`)

To disable:

- `DEPLOY_LOCAL_CHECKS=false`
- `ENABLE_AUTO_GIT_SYNC=false`

## Certbot

```bash
./installer.py certbot install
./installer.py certbot run --domain monitor01.example.com --email admin@example.com --webserver apache
./installer.py certbot auto
```