# TTL Cache and Ticket Resolution - Update

## Summary of Changes

Correct management of the life cycle of cached tickets implemented with differentiated TTLs for resolved and active tickets.

## Complete Workflow

### 1. Alert CRITICAL/DOWN
```
1. Check cache: ticket present?
   ├─ YES → Check via API if still open
   │ ├─ Open → Add Note
   │ ├─ Closed by operator → Add endnote (if possible), keep cache
   │ └─ Deleted (404) → Remove from cache
   └─ NO → Check via API if it already exists
       ├─ Exists → Add note + save to cache
       └─ Does not exist → Create ticket + save in cache
```

### 2. Alert OK/UP (Return)
```
1. Check cached tickets
   ├─ YES → Add note "Alarm cleared"
   │ + brand ticket.resolved_at = current timestamp
   │ + part timer 5 days
   └─ NO → No action
```

### 3. Automatic Cache Cleanup
```
clean_old_cache_entries() runs check:
├─ Resolved Tickets (resolved_at != null)
│ └─ If (now - resolved_at) > 5 days → REMOVE
└─ Active tickets (resolved_at == null)
    └─ If (now - last_update) > 30 days → REMOVE
```

## Configuration

```bash
# Retention time for resolved tickets: 5 days
RESOLVED_TICKET_TTL=$((5*24*3600))

# Retention time for active tickets: 30 days (fallback)
CACHE_MAX_AGE=$((30*24*3600))
```

## JSON Cache Structure

```json
{
  "<host-ip>:Memory": {
    "ticket_id": 1502598,
    "state": "OK",
    "created_at": 1735040400,
    "last_update": 1735126800,
    "resolved_at": 1735126800 // timestamp when switching to OK/UP (null if active)
  }
}
```

## Modified functions

### 1. `save_ticket_cache()`
- **Change**: Added `resolved_at: null` field in initial creation
- **Reason**: All new tickets start as active (unresolved)

### 2. `mark_ticket_resolved()`
- **New feature**: Set timestamp `resolved_at` when alert goes OK/UP
- **Usage**: Automatically called after adding indent note
- **Effect**: The 5-day cleanup timer starts

### 3. `clean_old_cache_entries()`
- **Change**: Different logic for resolved vs active tickets
- **Logic**: 
  - `resolved_at != null` → TTL 5 days
  - `resolved_at == null` → TTL 30 days
- **Use**: `atomic_cache_write()` for concurrency safety

### 4. Alert SERVICE management (lines 434-467)
- **Change**: Added block after `update_ticket_state()`
  ```bash
  if [[ "$STATE" == "OK" || "$STATE" == "UP" ]]; then
    mark_ticket_resolved "$TICKET_KEY"
    log "Ticket #$TICKET_ID marked as resolved, automatic cleanup in 5 days"
  fi
  ```

### 5. HOST Alert Management (lines 599-622)
- **Change**: Same logic applied for alert host
- **Symmetry**: Identical behavior between SERVICE and HOST alerts

## Case Studies Managed

| Scenario | Cache Behavior | Notes |
|----------|---------------|------|
| Alert CRIT → create ticket | Save with `resolved_at: null` | Ticket active, TTL 30 days |
| Alert CRIT → OK | Set `resolved_at: timestamp` | 5 day timer part |
| Operator closes ticket on Ydea | Cache remains unchanged | Cleanup after 30 days if never resolved |
| Alert OK after operator closure | Update `resolved_at` | Cleanup 5 days after return |
| Ticket canceled (404) | Immediate removal | Unique case of synchronous removal |
| Alert CRIT → OK → CRIT again | Reset `resolved_at: null` | Ticket active again, TTL 30 days |

## Benefits Implementation

1. **Ticket Persistence**: Cache does not lose tracking even if operator closes ticket
2. **Intelligent Cleanup**: short TTL (5 days) for resolved, long (30 days) for active
3. **Anti-Duplication**: Verify API before creating new ticket
4. **Traceability**: `resolved_at` allows auditing of the exact moment of resolution
5. **Race-Safe**: Use `atomic_cache_write()` with flock in all changes

## Testing Recommended

```bash
# 1. Create CRITICAL alerts
# Check: cat /tmp/ydea_checkmk_tickets.json | jq '.["IP:SERVICE"].resolved_at'
# Expected output: null

#2. Switch alert to OK
# Check: cat /tmp/ydea_checkmk_tickets.json | jq '.["IP:SERVICE"].resolved_at'
# Expected output: 1735126800 (current timestamp)

#3. Simulate cleanup after 5+ days
# Manually change resolved_at to 6 days ago
# Run: clean_old_cache_entries
# Verify: ticket removed

# 4. Verify operator closes ticket
# Close ticket on Ydea
# Alert CRIT again
# Verification: Note added, no duplicate creation
```

## Files Modified
- `script-notify-checkmk/ydea_realip` (lines 13-14, 70-100, 145-189, 434-467, 599-622)

## Deploy

```bash
# Backup existing cache
ssh monitoring@<your-checkmk-server> "cp /tmp/ydea_checkmk_tickets.json /tmp/ydea_checkmk_tickets.json.pre-ttl"

# Deploy script updated
scp script-notify-checkmk/ydea_realip monitoring@<your-checkmk-server>:/opt/omd/sites/monitoring/local/share/check_mk/notifications/

# Check deployment
ssh monitoring@<your-checkmk-server> "grep -A5 'mark_ticket_resolved' /opt/omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip"
```

## Post-Deploy Monitoring

```bash
# Watch logs for resolution checks
tail -f /opt/omd/sites/monitoring/var/log/notify.log | grep -E "marked as resolved|automatic cleanup"

# Check cache periodically
watch -n 300 'cat /tmp/ydea_checkmk_tickets.json | jq "to_entries | map({key: .key, resolved: (.value.resolved_at != null), age_days: ((now - .value.created_at) / 86400 | floor)})"'
```