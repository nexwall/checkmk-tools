# CheckMK REST API — Reference Guide

CheckMK 2.4.x and 2.5.x — verified on srv-monitoring-sp and srv-monitoring-us.

## CRITICAL: API version path changed in 2.5.0

| CheckMK version | API path |
|---|---|
| 2.4.x | `/monitoring/check_mk/api/1.0/` |
| 2.5.x | `/monitoring/check_mk/api/v1/` |

**Always check OMD version first:**

```bash
su - monitoring -c "omd version"
```

If `2.5.x` → use `api/v1/`. If `2.4.x` → use `api/1.0/`.

---

## Authentication

### Bearer token format

```
Authorization: Bearer <username> <secret>
```

Note the **space** between username and secret — NOT a colon.

```python
req.add_header("Authorization", f"Bearer {user} {secret}")
```

### Automation user

- Username: `automation`
- Role: `admin`
- Connector: `None` (not in htpasswd — uses dedicated secret file)
- Secret file: `/omd/sites/monitoring/var/check_mk/web/automation/automation.secret`

Read secret from server:

```bash
cat /omd/sites/monitoring/var/check_mk/web/automation/automation.secret
```

---

## Base URL

```
https://<external_hostname>/<site>/check_mk/api/1.0/
```

OMD site name on all servers: `monitoring`

| Server | External API URL |
|---|---|
| srv-monitoring-sp | `https://45.33.235.86:2333/monitoring/check_mk/api/1.0` |
| srv-monitoring-us | `https://195.223.159.26/monitoring/check_mk/api/1.0` |
| checkmk-vps-01 | `https://monitor.nethlab.it/monitoring/check_mk/api/1.0` |
| checkmk-vps-02 | `https://monitor01.nethlab.it/monitoring/check_mk/api/1.0` |

---

## Critical: calling from inside the server via localhost does NOT work

On srv-monitoring-us (and likely all OMD servers):

```bash
# FAILS — 404
curl -sk "https://localhost/monitoring/check_mk/api/v1/..."

# FAILS — 301 redirect to https, then 404
curl -sk "http://localhost/monitoring/check_mk/api/v1/..."

# FAILS — gunicorn on :8000 does not route the API path
curl -sk "http://127.0.0.1:8000/monitoring/check_mk/api/v1/..."

# FAILS — 127.0.1.1 (same as above, certificate IP mismatch too)
curl -sk "https://127.0.1.1/monitoring/check_mk/api/v1/..."
```

Root cause: mod_wsgi serving the REST API requires the correct `ServerName` to match
the incoming `Host:` header. When calling via `localhost` the VirtualHost does not match.
When calling via IP (127.x or private), SSL certificate does not cover IP addresses.

**NEVER run these API calls from inside the server via SSH.**

**Solution A (preferred):** call the API from the Kali local terminal using the private
IP of the server (e.g. `192.168.10.46`) and SSL verification disabled.
The certificate CN is `srv-monitoring-us` — use that hostname with `--resolve` or just
use the private IP with `-sk` (skip verify):

```bash
# From Kali local terminal (NOT via SSH):
SECRET=$(ssh srv-monitoring-us "cat /omd/sites/monitoring/var/check_mk/web/automation/automation.secret")
curl -sk \
  -H "Authorization: Bearer automation $SECRET" \
  -H "Accept: application/json" \
  "https://192.168.10.46/monitoring/check_mk/api/v1/domain-types/folder_config/collections/all"
```

## CRITICAL: do NOT touch htpasswd for the automation user

The automation user Bearer auth uses ONLY the secret file:
`/omd/sites/monitoring/var/check_mk/web/automation/automation.secret`

Running `htpasswd -b ... automation <password>` overwrites the htpasswd entry and
**breaks Bearer authentication** — do not do this. The two auth mechanisms are separate.

**Solution B (always works from anywhere):** edit `rules.mk` directly + reload with `cmk -O`. See section below.

---

## Python API client pattern (from rename_hosts_api.py)

```python
import urllib.request, urllib.error, json, ssl

def make_ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def api_call(base_url, user, secret, method, path, body=None, etag=None):
    url = base_url.rstrip("/") + "/" + path.lstrip("/")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {user} {secret}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    if etag:
        req.add_header("If-Match", etag)
    try:
        with urllib.request.urlopen(req, context=make_ssl_ctx(), timeout=30) as resp:
            etag_out = resp.headers.get("ETag", "*")
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}, etag_out
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            err = json.loads(raw)
        except Exception:
            err = raw.decode()
        return e.code, err, ""
```

---

## Common API endpoints

### Hosts

```python
# List all hosts
api_call(base_url, user, secret, "GET",
    "domain-types/host_config/collections/all")

# Get single host (also returns ETag needed for PUT/DELETE)
api_call(base_url, user, secret, "GET",
    f"objects/host_config/{hostname}")

# Create host
api_call(base_url, user, secret, "POST",
    "domain-types/host_config/collections/all",
    body={"host_name": name, "folder": "/", "attributes": {...}})

# Delete host (requires ETag from GET)
api_call(base_url, user, secret, "DELETE",
    f"objects/host_config/{hostname}", etag=etag)
```

### Rules (WATO)

```python
# List rules for a ruleset
api_call(base_url, user, secret, "GET",
    "domain-types/rule/collections/all?ruleset_name=extra_service_conf%3Amax_check_attempts")

# Create rule
api_call(base_url, user, secret, "POST",
    "domain-types/rule/collections/all",
    body={
        "ruleset": "extra_service_conf:max_check_attempts",
        "folder": "/",
        "properties": {"disabled": False, "description": "Rule description"},
        "value_raw": "5",
        "conditions": {
            "service_description": [{"match_regex": "^Host Connectivity$"}],
            "host_name": [{"match_regex": "^marcatempo-colibri$"}],
        }
    })
```

### Service discovery

```python
# Trigger discovery on a host
api_call(base_url, user, secret, "POST",
    f"objects/host_config/{hostname}/actions/discover_services/invoke",
    body={"mode": "tabula_rasa"})
```

### Activate changes

```python
# ALWAYS required after any WATO modification
api_call(base_url, user, secret, "POST",
    "domain-types/activation_run/actions/activate-changes/invoke",
    body={"force_foreign_changes": True},
    etag="*")
```

---

## Alternative: direct rules.mk editing (no API needed, always works)

When the REST API is inaccessible (localhost issue, network issue, auth issue),
edit `rules.mk` directly on the server and reload with `cmk -O`.

Reference script: `copilot/fix_host_max_attempts.py`

```python
RULES_MK = "/omd/sites/monitoring/etc/check_mk/conf.d/wato/rules.mk"

NEW_RULE = """
extra_service_conf.setdefault('max_check_attempts', [])

extra_service_conf['max_check_attempts'] = [
{'id': '<unique-uuid>', 'value': 5,
 'condition': {
   'service_description': [{'$regex': '^Host Connectivity$'}],
   'host_name': [{'$regex': '^marcatempo-colibri$'}]
 },
 'options': {'disabled': False, 'description': 'Colibri: 5 attempts before HARD CRIT'}},
] + extra_service_conf['max_check_attempts']

"""

with open(RULES_MK, "r") as f:
    content = f.read()

# Insert after a stable anchor (adapt to actual file content)
anchor = "] + extra_service_conf['retry_interval']"
content = content.replace(anchor, anchor + NEW_RULE, 1)

with open(RULES_MK, "w") as f:
    f.write(content)
```

Then reload (run as root, OMD site must be running):

```bash
su - monitoring -c 'cmk -O'
# or if that fails:
omd reload monitoring
```

**Rules to follow when editing rules.mk directly:**

- Always generate a fresh UUID for the `'id'` field (use `PYTHONDONTWRITEBYTECODE=1 python3 -B -c "import uuid; print(uuid.uuid4())"`)
- Always backup before editing: `cp rules.mk rules.mk.backup_$(date +%Y-%m-%d_%H-%M-%S)`
- Regex in conditions uses `'$regex'` key (not `'match_regex'` — that's API format only)
- After editing run `cmk -O` to reload config without full restart

---

## Ruleset names reference

| WATO setting | rules.mk key | API ruleset name |
|---|---|---|
| Host max check attempts | `extra_host_conf['max_check_attempts']` | `extra_host_conf:max_check_attempts` |
| Host retry interval | `extra_host_conf['retry_interval']` | `extra_host_conf:retry_interval` |
| Host normal check interval | `extra_host_conf['check_interval']` | `extra_host_conf:check_interval` |
| Service max check attempts | `extra_service_conf['max_check_attempts']` | `extra_service_conf:max_check_attempts` |
| Service retry interval | `extra_service_conf['retry_interval']` | `extra_service_conf:retry_interval` |
| Service normal check interval | `extra_service_conf['check_interval']` | `extra_service_conf:check_interval` |
| Flap detection | `active_checks['flap_detection']` | — |

---

## Flap detection (WATO only — no API ruleset)

Flap detection is configured in WATO under:
*Setup → Service monitoring rules → Flap detection parameters for services*

Global status (via LiveStatus):

```python
import socket
s = socket.socket(socket.AF_UNIX)
s.connect('/omd/sites/monitoring/tmp/run/live')
s.send(b'GET status\nColumns: enable_flap_detection low_service_flap_threshold high_service_flap_threshold\n')
s.shutdown(socket.SHUT_WR)
print(s.makefile().read().strip())
# Returns: 1;low_threshold;high_threshold
# Default thresholds: low=5, high=20 (percentage of state changes in history window)
```

Flap detection only becomes effective when `max_check_attempts` is high enough to build
a meaningful state history. With `max_check_attempts=1` flap detection is essentially useless.

---

## Troubleshooting auth errors

| Error | Cause | Fix |
|---|---|---|
| `401 Invalid Bearer token` | Used `Bearer user:secret` (colon) | Use `Bearer user secret` (space) |
| `401 Wrong credentials (Bearer header)` | Correct format but wrong secret | Read actual secret from `automation.secret` file |
| `404 Not Found` | Calling from inside server via `localhost` | Call from external Kali terminal using external IP/hostname |
| `404 Not Found` | Wrong site name in URL | Check with `omd sites` |
| `428 Precondition Required` | PUT/DELETE without `If-Match` header | Add `If-Match: *` or use ETag from prior GET |

---

## Current configuration on srv-monitoring-us (as of 2026-04-30)

| Rule | Applies to | Value |
|---|---|---|
| `max_check_attempts` host | all hosts | **25** |
| `retry_interval` host | all hosts | **5 min** |
| `max_check_attempts` service | `Check_MK Agent` | 3 |
| `max_check_attempts` service | `Check_MK` | 1 |
| `max_check_attempts` service | **everything else** | **default = 1** ← problem |
| `check_interval` service | `Check_MK HW/SW Inventory` | 1442 min (1/day) |
| `check_interval` service | `Check_MK Discovery` | 120 min |

**Known flapping services:**

- `marcatempo-colibri` → `Host Connectivity` — oscillates CRIT/OK due to packet loss on Colibri branch line
- `srv-monitoring-us.urbinoservizi.it` → `Infra-Sede-Colibri` and all `Infra-Sede-*` — same issue, `max_check_attempts=1`

**Pending fix (approved 2026-04-30, not yet applied):**
Add service rule: `max_check_attempts=5` + `retry_interval=2min` for `Host Connectivity` on `marcatempo-colibri`
and for all `Infra-Sede-*` services on `srv-monitoring-us.urbinoservizi.it`.
