# Changelog v1.9 - TTL Cache with Ticket Resolution

## Date
2025-01-15

## Version
ydea_realip v1.9

## Problem Solved

Ticket cache did not distinguish between active and resolved tickets, causing:
- Immediate ticket removal when operator closed ticket on Ydea
- Inability to track exact alert resolution moment
- Uniform TTL for all tickets (30 days) regardless of status

## Solution Implemented

### 1. Differentiated TTL configuration

```bash
# Tickets resolved (alert returned): 5 days
RESOLVED_TICKET_TTL=$((5*24*3600))

# Active tickets (persistent alert): 30 days
CACHE_MAX_AGE=$((30*24*3600))
```

### 2. Extended Cache Structure

**Before:**
```json
{
  "ticket_id": 1502598,
  "state": "OK",
  "created_at": 1735040400,
  "last_update": 1735126800
}
```

**After:**
```json
{
  "ticket_id": 1502598,
  "state": "OK",
  "created_at": 1735040400,
  "last_update": 1735126800,
  "resolved_at": 1735126800 // null if active ticket, timestamp if resolved
}
```

### 3. New Function: `mark_ticket_resolved()`

```bash
mark_ticket_resolved() {
  local key="$1"
  init_cache
  
  # Verify that the ticket exists in cache
  if ! ticket_in_cache "$key"; then
    debug "Ticket $key not cached, skip mark_resolved"
    return 0
  fi
  
  local updated_cache
  updated_cache=$(jq --arg key "$key" \
     --arg ts "$(date -u +%s)" \
    '.[$key].resolved_at = ($ts | tonumber) | .[$key].last_update = ($ts | tonumber)' \
    "$TICKET_CACHE" 2>/dev/null) || {
    log "WARN: Unable to mark resolved ticket for $key"
    return 1
  }
  
  atomic_cache_write "$TICKET_CACHE" "$updated_cache"
  debug "Ticket $key marked as resolved, cleanup in 5 days"
}
```

### 4. Smart Cleanup

**Before (lines 70-87):**
```bash
clean_old_cache_entries() {
  local now=$(date -u +%s)
  local cutoff=$((now - CACHE_MAX_AGE)) # Always 30 days
  
  cleaned=$(jq --arg cutoff "$cutoff" 'to_entries | map(
    select(
      .value.last_update != null and
      (.value.last_update | tonumber) > ($cutoff | tonumber)
    )
  ) | from_entries' "$TICKET_CACHE")
  
  echo "$cleaned" > "$TICKET_CACHE"
}
```

**After (lines 70-100):**
```bash
clean_old_cache_entries() {
  local now=$(date -u +%s)
  local resolved_cutoff=$((now - RESOLVED_TICKET_TTL)) # 5 days
  local active_cutoff=$((now - CACHE_MAX_AGE)) # 30 days
  
  cleaned=$(jq --arg resolved_cutoff "$resolved_cutoff" --arg active_cutoff "$active_cutoff" '
    to_entries | map(
      select(
        # Resolved tickets: Check resolved_at
        if .value.resolved_at != null then
          (.value.resolved_at | tonumber) > ($resolved_cutoff | tonumber)
        # Active tickets: Check last_update
        else
          .value.last_update != null and
          (.value.last_update | tonumber) > ($active_cutoff | tonumber)
        end
      )
    ) | from_entries
  ' "$TICKET_CACHE")
  
  atomic_cache_write "$cleaned" # Use flock for safety
}
```

### 5. Alert OK/UP - Resolution marking

**SERVICE Alerts (lines 454-461):**
```bash
if [[ $note_result -eq 0 ]]; then
  log "Private note added to ticket #$TICKET_ID"
  update_ticket_state "$TICKET_KEY" "$STATE"
  
  # If status changes to OK/UP, mark ticket as resolved (5 day timer part)
  if [[ "$STATE" == "OK" || "$STATE" == "UP" ]]; then
    mark_ticket_resolved "$TICKET_KEY"
    log "Ticket #$TICKET_ID marked as resolved, automatic cleanup in 5 days"
  fi
```

**HOST Alerts (lines 612-619):**
```bash
if [[ $note_result -eq 0 ]]; then
  log "Private note added to ticket #$TICKET_ID"
  update_ticket_state "$TICKET_KEY" "$STATE"
  
  # If status changes to OK/UP, mark ticket as resolved (5 day timer part)
  if [[ "$STATE" == "OK" || "$STATE" == "UP" ]]; then
    mark_ticket_resolved "$TICKET_KEY"
    log "Ticket #$TICKET_ID marked as resolved, automatic cleanup in 5 days"
  fi
```

## File Changes

### `ydea_realip`
- **Lines 13-14**: Added `RESOLVED_TICKET_TTL` configuration
- **Lines 70-100**: Rewritten `clean_old_cache_entries()` with differentiated logic
- **Line 157**: Added `resolved_at: null` to `save_ticket_cache()`
- **Lines 167-189**: New function `mark_ticket_resolved()`
- **Lines 454-461**: Alert SERVICE - marking resolution on OK/UP
- **Lines 490-497**: Alert SERVICE - resolution marking on OK/UP (API error case)
- **Lines 612-619**: Alert HOST - marking resolution on OK/UP

### `CACHE_TTL_UPDATE.md`
- Complete workflow documentation
- JSON cache structure
- Case studies managed
- Testing and deployment guides

## Workflow Updated

### 1. Alert CRITICAL/DOWN
```
Cache → API check → Add note or create ticket → Save cache (resolved_at: null)
```

### 2. Alert OK/UP (Return)
```
Add note "Alarm cleared" → mark_ticket_resolved() → Set resolved_at: now → 5-day timer
```

### 3. Automatic Cleanup
```
- Resolved tickets (resolved_at != null): removed after 5 days
- Active tickets (resolved_at == null): removed after 30 days
```

## Benefits

1. **Cache Persistence**: Tickets not removed when operator closes on Ydea
2. **Smart TTL**: 5 days for resolved (quick cleanup), 30 days for active (long tracking)
3. **Audit Trail**: Exact alert resolution timestamp plotted in `resolved_at`
4. **Anti-Duplication**: API Verification prevents creation of duplicates for closed tickets
5. **Race-Safe**: Use `atomic_cache_write()` with flock for all cache changes

## Testing Done

- Check bash syntax (`bash -n`): OK
- JSON structure valid for all cache operations
- `mark_ticket_resolved()` function properly integrated
- Cleanup uses atomic writes to prevent race conditions

## Deploy Required

```bash
#1. Backup current cache
ssh monitoring@<your-checkmk-server> "cp /tmp/ydea_checkmk_tickets.json /tmp/ydea_checkmk_tickets.json.pre-v1.9"

#2. Deploy updated script
scp script-notify-checkmk/ydea_realip monitoring@<your-checkmk-server>:/opt/omd/sites/monitoring/local/share/check_mk/notifications/

# 3. Check deployment
ssh monitoring@<your-checkmk-server> "grep -c 'mark_ticket_resolved' /opt/omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip"
# Expected output: 3 (1 definition + 2 calls)

#4. Monitor logs to confirm operation
tail -f /opt/omd/sites/monitoring/var/log/notify.log | grep -E "marked as resolved|automatic cleanup"
```

## Technical Notes

- `resolved_at` can be `null` (active ticket) or `timestamp` (resolved ticket)
- `clean_old_cache_entries()` run on every `init_cache()`
- `atomic_cache_write()` ensures concurrent cache coherence
- Ticket with `resolved_at` older than 5+ days is automatically removed
- Active ticket (`resolved_at: null`) removed after 30 days by `last_update`

## Compatibility

- Backwards compatible: cache without `resolved_at` treated as active ticket (TTL 30 days)
- jq 1.6+: Required for `if-then-else` in JSON filters
- flock: already required since v1.8 for atomic operations
- bash 4.0+: no new features required