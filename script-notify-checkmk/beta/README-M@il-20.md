# M@il-20

M@il-20 is a beta Checkmk HTML notification handler with an audit-only
fail2ban-style transition rate limiter and adaptive learning for
**HOST STATE** and **SERVICE STATE PING** notifications.

## Architecture

```
Checkmk notification event
        │
        ▼
  evaluate_rate_limit()
        │
        ├── BYPASS ──────► send M@il-compatible mail (non-PING, disabled)
        │
        ├── SEND ────────► send mail
        │
        ├── WOULD_SUPPRESS ──► send mail (audit mode)
        │
        ├── SUPPRESS ────► log + return (enforce mode)
        │
        └── FAIL_OPEN ───► send mail (error path)
                │
                ▼
        Adaptive learning
        (recommendation only, never auto-applied)
```

## Modes

### audit (default)
Every notification is always sent. The rate-limit decision is calculated
and logged but never enforced. Safe for production dry-run.

### enforce
Once the transition threshold is reached, further notifications for that
host/category are suppressed until the suppression window expires.
The first genuine problem notification (the one that triggers suppression
entry) is always sent.

## Static rate-limiter

### HOST STATE
Tracks only real changes between `UP ↔ DOWN`. Repeated identical states
(e.g. `DOWN → DOWN`) are not counted. A persistent DOWN does not trigger
suppression.

### SERVICE STATE PING
Tracks only the exact service description `PING` and only real changes
between `OK ↔ CRIT` (or `OK ↔ CRITICAL`). `WARN`, `UNKNOWN` are logged
but not counted. Non-PING services bypass the limiter.

### Threshold semantics
Threshold evaluation uses **inclusive** comparison:
```
transitions >= trigger_transitions  → enter suppression
```

| Category | Observation window | Trigger transitions | Suppression time |
|---|---|---|---|
| HOST STATE | 30 min | 4 | 60 min |
| SERVICE STATE PING | 30 min | 6 | 60 min |

## Adaptive learning

The adaptive subsystem observes transition frequency per host and per
category, and calculates recommended thresholds. It **never** changes
active thresholds automatically.

### Configuration

```json
{
    "adaptive": {
        "enabled": true,
        "mode": "learning",
        "minimum_learning_days": 14,
        "minimum_transition_samples": 20,
        "recalculate_every_hours": 24,
        "percentile": 95,
        "safety_margin": 2,
        "auto_apply": false
    }
}
```

Only `mode=learning` and `auto_apply=false` are supported.

### Recommendation formula

```
raw = percentile_95(window_counts_30m) + safety_margin
clamped = max(hard_min, min(hard_max, raw))
```

### Hard limits

| Category | Min | Max |
|---|---|---|
| HOST STATE | 4 | 10 |
| SERVICE STATE PING | 6 | 20 |

### Statuses

| Status | Meaning |
|---|---|
| `INSUFFICIENT_DATA` | Not enough learning days or samples |
| `STABLE` | Current threshold matches recommendation |
| `RECOMMEND_HIGHER_THRESHOLD` | Observed instability suggests raising threshold |
| `RECOMMEND_LOWER_THRESHOLD` | Observed stability suggests lowering threshold |
| `EXCESSIVE_INSTABILITY` | Host exceeds max safe range consistently |

## Fail-open

Any error in rate-limiting or adaptive learning causes the notification
to fall through to normal mail delivery with a `FAIL_OPEN` log entry.
A rate-limit failure never silently drops a notification.

## Files

All under `script-notify-checkmk/beta/`:

| File | Purpose |
|---|---|
| `M@il-20` | Main notification script |
| `M@il-20-config.json` | Configuration (mode, thresholds, adaptive) |
| `README-M@il-20.md` | This file |
| `test-M@il-20.py` | Test suite (26 tests) |

## Runtime paths

| Resource | Path |
|---|---|
| State file | `$OMD_ROOT/var/check_mk/M@il-20/state.json` |
| Lock file | `$OMD_ROOT/var/check_mk/M@il-20/state.lock` |
| Log file | `$OMD_ROOT/var/log/notifications/mail-20.log` |

## Logging format

All lifecycle records use JSON Lines format with the `NOTIFY_EVENT ` prefix:

```
NOTIFY_EVENT {"level":"INFO","execution_id":"...","status":"INVOKED",...}
```

Each physical line is exactly one JSON object, parseable with `json.loads()` after
stripping the `NOTIFY_EVENT ` prefix.  The log is also grep-compatible:

```bash
grep "NOTIFY_EVENT" $OMD_ROOT/var/log/notifications/mail-20.log
```

## Debug logging

Set the environment variable `MAIL20_DEBUG=1` before invoking the script to enable
additional diagnostic output in the log:

```bash
MAIL20_DEBUG=1 /opt/checkmk-tools/script-notify-checkmk/beta/M@il-20
```

## State retention

The state file is bounded by the following defaults (configurable via
`state_retention` in the JSON configuration):

| Setting | Default | Description |
|---|---|---|
| `stale_host_days` | 30 | Remove hosts with no activity after this many days |
| `max_transitions_per_category` | 500 | Cap transition lists after age-based pruning |
| `cleanup_interval_seconds` | 3600 | Minimum seconds between full stale-host scans |

Cleanup runs under the state lock; expired records are removed, active
suppression and recent adaptive-learning data are preserved.

If the state file exceeds 10 MB, a warning is logged but the file is still
loaded.  Corrupted files are replaced with an empty state.  Writes use an
atomic temporary-file + `os.replace()` pattern.  If a write fails, the
original state file remains intact and temporary files are cleaned up.

## CLI

```bash
# Print read-only adaptive learning report
python3 -B M@il-20 --learning-report

# Print version
python3 -B M@il-20 --version
```

## Reporting
