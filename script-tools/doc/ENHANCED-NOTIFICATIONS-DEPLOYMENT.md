# IMPLEMENTATION SUMMARY - Enhanced Notifications for CheckMK
> **Category:** Specialist

## What has been implemented

I have created a completely independent **new advanced notification system** that improves communication of two critical CheckMK scenarios:

### 1⃣ **HOST DOWN Alerts** 
When a host loses connectivity (Connection Refused, Network Down, Timeout)

### 2⃣ **HOST UP - NO DATA Alerts**   
When a host is online but is not sending tracking data

---

## Files Created

| Files | Type | Description |
|------|------|-------------|
| `ydea_ag_host_down` | Bash scripts | Enhanced Ydea - smart alert detection + context-aware tickets |
| `rydea_ag_host_down` | Remote launcher | Remote deployment version from GitHub |
| `ENHANCED-NOTIFICATIONS-README.md` | Doc | Detailed Guide |
| `ENHANCED-TESTING-GUIDE.md` | Doc | Testing Procedures |

**Routes**:
- Full: `script-notify-checkmk/full/`
- Remote: `script-notify-checkmk/remote/`

---

## How it works

### Architecture

```
CheckMK Alert
    ↓
┌─────────────────────────────────────┐
│ ydea_ag_host_down Script │
├─────────────────────────────────────┤
│ 1. Analyze alert output │
│ 2. Detect type (DOWN/NODATA/etc) │
│ 3. Generate context-aware descriptions │
│ 4. Create Ydea ticket │
│ 5. Cache tracking (tickets/flapping)│
│ 6. Detects and manages flapping │
└─────────────────────────────────────┘
    ↓
Ydea ticket with improved description
```

### Workflow

1. **Alert Type Detection**: Analyze CheckMK output to recognize: REFUSED, NETWORK, TIMEOUT, NODATA, MISSING_DATA, STALE_DATA
2. **Context-Aware Descriptions**: Generate specific ticket descriptions for each type of issue
3. **Ticket Creation**: Create Ydea tickets automatically
4. **Cache Tracking**: Maintains ticket history to avoid duplicates
5. **Flapping Detection**: Detect hosts/services that repeatedly change state (escalation)

---

## Improvements Compared to Before

### BEFORE (Generic Alert)
```
[agent] Communication failed: [Errno 111] Connection refused CRIT
[piggyback] Success (but no data found for this host) WARN
Missing monitoring data for all plugins WARN
```
 Confused |  Technical |  Not actionable

### AFTER (Improved Alert)
```
 HOST DOWN - hostname (<host-ip>)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROBLEM:
The host refused the connection. It could be:
  • Host shut down or restarting
  • CheckMK agent service not listening
  • Firewall blocks the port
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUGGESTED ACTIONS:
  1. Check if host is reachable: ping <host-ip>
  2. Check agent status: ssh hostname 'systemctl status check-mk-agent'
  3. Check firewall towards port 6556
```
 Clear |  Operational |  Actionable

---

## Quick Start installation

### Option 1: Manual (Recommended) 

```bash
# On CheckMK server - as monitoring user
on - monitoring
cd ~/local/share/check_mk/notifications/

# Copy the new ydea_ag_host_down from GitHub
curl -fsSL https://raw.githubusercontent.com/nethesis/checkmk-tools/main/script-notify-checkmk/full/ydea_ag_host_down\
  -o ydea_ag_host_down && chmod +x ydea_ag_host_down

# Verify that it is executable
ls -la ydea_ag_host_down
```

### Option 2: Remote Launcher (With automatic updates)

```bash
# On CheckMK server - as monitoring user
on - monitoring
cd ~/local/share/check_mk/notifications/

# Copy the remote launcher
curl -fsSL https://raw.githubusercontent.com/nethesis/checkmk-tools/main/script-notify-checkmk/remote/rydea_ag_host_down\
  -o rydea_ag_host_down && chmod +x rydea_ag_host_down

# Check
ls -la rydea_ag_host_down
```

### Configure in CheckMK Web UI

1. **Setup** → **Events** → **Notifications**
2. **Create New Notification Rule**
   - **Notification Method**: `Script based notification`
   - **Script name**: `ydea_ag_host_down` (or `rydea_ag_host_down`)
   - **Conditions** - select at least one:
     - Host state is `Down` 
     - Service state is `Critical` AND output contains `no data`
     - Output contains `Connection refused` OR `Network unreachable` OR `timeout`
   - **Contact**: Assign to admin or ops email
3. **Activate Changes**

---

## Relationship with ydea_ag (IMPORTANT)

**`ydea_ag_host_down` is an improved version of `ydea_ag`**

- Maintains ALL original mechanisms (cache, ticket aggregation, flapping detection)
- Adds smart alert type detection (REFUSED, NETWORK, TIMEOUT, NODATA, etc.)
- Generate improved, context-aware ticket descriptions
- Fully compatible - you can replace ydea_ag with ydea_ag_host_down

---

## Features

### Smart Alert Type Detection
```
CONNECTION_REFUSED → HOST_OFFLINE_REFUSED
NETWORK_UNREACHABLE → HOST_OFFLINE_NETWORK  
TIMEOUT → HOST_OFFLINE_TIMEOUT
NO_DATA_FOUND → HOST_NODATA
MISSING_DATA → HOST_MISSING_DATA
STALE_CACHE → HOST_STALE_DATA
```

### Ticket Creation
- Create Ydea tickets automatically (same as original ydea_ag)
- Adds context-aware description based on alert type
- Maintains ticket aggregation (does not create duplicates)
- Maintains flapping detection (5 changes in 10 minutes = escalation)

### Local Caching
```
/tmp/ydea-cache/
├── tickets.json # Track created tickets
├── flapping-detection.json # Detect flapping hosts
└── /tmp/ydea-host-down.log # Event log
```

---

## Testing

### Standalone testing
```bash
export NOTIFY_HOSTNAME="test-host"
export NOTIFY_HOSTADDRESS="192.168.1.100"
export NOTIFY_HOSTSTATE="DOWN"
export NOTIFY_SERVICEDESC="Check_MK"
export NOTIFY_SERVICESTATE="CRIT"
export NOTIFY_SERVICEOUTPUT="Connection refused"
export NOTIFY_CONTACTEMAIL="admin@example.com"
export DEBUG_NOTIFY=1

bash notify-enhanced-down-nodata
```

See **ENHANCED-TESTING-GUIDE.md** for complete procedures.

---

## Monitoring

### View Log
```bash
tail -f /opt/checkmk/enhanced-notifications/enhanced-notify.log
```

### Run Test
```bash
# Test with variables
~/local/share/check_mk/notifications/ydea_ag_host_down

# Verify the ticket created on Ydea
# (Note: ticket will ONLY be created if ~/.env.ag is configured correctly)
```

### Analyze Cache
```bash
# See tickets created
cat /tmp/ydea-cache/tickets.json | jq '.'

# See flapping detection
cat /tmp/ydea-cache/flapping-detection.json | jq '.'
```

### Notification Count
```bash
# How many alerts processed
tail -50 /tmp/ydea-host-down.log

# See recognized alert types
grep "ALERT_TYPE" /tmp/ydea-host-down.log
```

---

## Troubleshooting

| Problem | Solution |
|----------|----------|
| "Script not found" | Check path: `ls -la ~/local/share/check_mk/notifications/ydea_ag_host_down` |
| "Permission denied" | Set permissions: `chmod +x ~/local/share/check_mk/notifications/ydea_ag_host_down` |
| Ticket not created | Check `~/.env.ag`: `cat ~/.env.ag` must contain YDEA_ID and YDEA_API_KEY |
| Cache permission denied | `mkdir -p /tmp/ydea-cache && chmod 777 /tmp/ydea-cache` |
| Script not executed in CheckMK | Check notification rule in Web UI - select "Script based notification" |
| Flapping detection too sensitive | Change FLAP_THRESHOLD to ydea_ag_host_down (currently 5 in 10 min) |

---

## Complete documentation

All files are in the repository:

- **ydea_ag_host_down Details**: Read the comments in the script itself
- **Testing**: `ENHANCED-TESTING-GUIDE.md` (still valid for mechanisms)
- **README**: `ENHANCED-NOTIFICATIONS-README.md` (general reference)

---

## Deployment Checklist

- [ ] Script downloaded to the correct directory: `~/local/share/check_mk/notifications/`
- [ ] Fixed permissions: `ls -la` shows `rwxr-xr-x` for ydea_ag_host_down
- [ ] `~/.env.ag` exists and contains Ydea credentials
- [ ] Notification rule created in CheckMK Web UI
- [ ] Test alert generated (simulate host down)
- [ ] Ticket created on Ydea (verify manually)
- [ ] Verified log: `tail /tmp/ydea-host-down.log`
- [ ] Cache created: `ls /tmp/ydea-cache/`

---

## Next Steps (Optional)

1. **Replace ydea_ag**: If you want to ONLY use ydea_ag_host_down (recommended)
2. **ITSM Integration**: Add KB link in Ydea ticket
3. **Escalation Logic**: Auto-escalate after N occurrences
4. **Slack Integration**: Add Slack notifications
5. **Custom Templates**: Customize ticket descriptions

---

## Support

- **GitHub**: https://github.com/nethesis/checkmk-tools
- **Repository**: checkmk-tools - branch main

---

## Version Info

| Component | Version | Date |
|-----------|----------|------|
| ydea_ag_host_down | 1.0 | 2025-12-15 |
| rydea_ag_host_down (remote) | 1.0 | 2025-12-15 |
| Documentation | 1.0 | 2025-12-15 |
| Repositories | checkmk-tools | main branch |

---

## Security

- No hardcoded credentials
- World-writable permission cache (777) for multi-user
- Sanitized log (no sensitive IPs/hosts in output)
- Independent from ydea_ag (no lock file contention)

---

## Important Note
**This script is completely independent of `ydea_ag` and does NOT modify it.**

- Does not affect the ticket creation logic
- Does not modify ydea_ag cache
- Can be used standalone or together
- Zero impact on existing system

---

**Status**: **READY FOR PRODUCTION**

All files are committed to the repository and ready for deployment.