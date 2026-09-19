# GitHub Copilot Instructions - checkmk-tools

## Repository information

This repository contains automation scripts, CheckMK local checks, notification scripts,
deployment tools, and documentation for CheckMK monitoring infrastructure.

**Remotes:**
- `origin` — personal fork (daily work)
- `upstream` — official repository (release only)

---

## Mandatory rules

### Language

- **Chat with the user**: Italian
- **Code, comments, docstrings, README, docs, commit messages, release notes**: English
- No Italian text in code or documentation files.

### No hardcoded environment data

- Never hardcode IP addresses, hostnames, domain names, ports, URLs, credentials, tokens,
  API keys, SSH paths, private host aliases, rclone remotes, buckets, or any other
  environment-specific values.
- Use environment variables, config files, or parameters passed at runtime.
- Use placeholder values in examples: `YOUR_TOKEN_HERE`, `<hostname>`, `<ip_address>`.
- This rule applies to all file types: scripts, config templates, markdown, instructions.

### No personal names or brand names

- Never include names of people, usernames, GitHub handles, internal brand names,
  customer names, or project codenames in files.
- Use generic references: "upstream standard", "reference implementation".

### Repository boundary — private vs public

- **Private operational memory** must live only in the private `.copilot` repository.
- **Project repositories** must contain only public-safe instructions, code, docs,
  examples, and sanitized templates.
- If host-specific, credential-specific, customer-specific, or private troubleshooting
  details are needed, refer generically to the private `.copilot` memory without
  naming private paths or personal identifiers.
- Every file in this repository must remain portable and public-safe.

### Emojis in files

- Zero decorative emojis in files.
- **Allowed only**: colored status circles in script/notification output:
  - `🔴` red circle — CRITICAL / error / alert
  - `🟡` yellow circle — WARNING / degraded
  - `🟢` green circle — OK / healthy / resolved

---

## Development workflow

### Python-first policy

- All new scripts must be written in Python.
- Python is the official language for new checks, tools, and automation.
- Bash only for minimal wrappers or justified exceptional cases.
- Follow the Nethesis Python style: flat functions, no `if __name__`, no classes,
  `subprocess.run([...])` with lists (never `shell=True`).

### Script testing workflow (mandatory)

```bash
# 1. Syntax validation
PYTHONDONTWRITEBYTECODE=1 python3 -B -c "compile(open('script.py').read(), 'script.py', 'exec')"

# 2. Make executable (bash only)
git update-index --chmod=+x script.sh

# 3. Copy to test server — no git push yet
scp script.py <test-host>:/tmp/script_test.py

# 4. Test on remote host + cleanup
ssh <test-host> 'python3 /tmp/script_test.py; rm -f /tmp/script_test.py'

# 5. Only if test passes → commit and push
git add script.py
git commit -m "type(scope): brief description"
git push origin main
```

### Versioning

- Version format: `MAJOR.MINOR.PATCH` (e.g., `2.0.5`).
- Always add a `VERSION` variable at the top of every script.
- Increment PATCH for fixes, maintenance, docs, refactors.
- Increment MINOR only for new backward-compatible features (explicitly approved).
- Increment MAJOR only for breaking changes (explicitly approved).

---

## Git safety rules

### Pre-command guard for risky actions

Before any destructive or push operation, always run:

```bash
pwd
git rev-parse --show-toplevel
git branch --show-current
git status --short
git remote -v
```

Confirm the correct repository, branch, and remote before proceeding.

### Push rules

- Default push target: `origin` (personal fork).
- Never push to `upstream` unless explicitly releasing.
- Never force-push or force-move existing tags.
- If a tag already exists, stop or increment the patch version.
- Do not use `git clean`.
- Do not edit synchronized production copies (e.g., `/opt/checkmk-tools/`).

### No archived/ folders

- Scripts that are replaced must be deleted (via `git rm`), not moved to `archived/`.
- Git history preserves old versions.

---

## CheckMK scripts standards

### Local check output format

```
<STATE> <SERVICE_NAME> - <message>
```

State codes: `0` = OK, `1` = WARNING, `2` = CRITICAL, `3` = UNKNOWN.

### Python template (Nethesis style)

```python
#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Check <service> status

import sys
import subprocess

SERVICE = "ServiceName"
VERSION = "1.0.0"

## Useful

def run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 1, "", str(e)

## Check

def check():
    rc, out, err = run(["systemctl", "is-active", "myservice"])
    if rc != 0:
        print(f"2 {SERVICE} - CRITICAL: service not running")
        return
    print(f"0 {SERVICE} - OK: running")

check()
```

### Deployment

- Scripts are deployed from `/opt/checkmk-tools/` (auto-synced via git pull cron).
- Deployed file name: without extension (CheckMK runs all executable files).
- No launcher scripts needed for direct deployment.

---

## Quality and validation

### Syntax validation

- **Python**: `PYTHONDONTWRITEBYTECODE=1 python3 -B -c "compile(open('file').read(), 'file', 'exec')"`
- **Bash**: `bash -n script.sh`
- **PowerShell**: `[System.Management.Automation.PSParser]::Tokenize(...)`
- Exit code must be 0 before considering a file complete.

### Integrity check

Run periodically:

```powershell
.\script-ps-tools\check-integrity.ps1
```

### Markdown quality

- Run `markdownlint` on modified `.md` files.
- Fix MD051 (invalid link fragments), MD042 (empty links), spacing errors.

---

## SSH and remote access

- **Private host access details** are stored in the private `.copilot` repository.
- Do not hardcode SSH aliases, IP addresses, or credentials in any file.
- Use base64 encoding for multi-line SSH commands to avoid quoting failures.
- Hosts with password authentication: give commands to the user to paste; do not
  attempt automated SSH connections.

---

## Notification scripts (Ydea)

- Ydea scripts are CheckMK notification hooks stored on the monitoring server.
- API keys and environment configuration are managed outside this repository
  via `.env` files on the target host.
- Cache paths and configuration details are documented in the private `.copilot` memory.
