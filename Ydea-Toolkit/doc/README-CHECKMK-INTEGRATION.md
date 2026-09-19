# CheckMK → Ydea Ticketing integration

Complete system for the automatic management of Ydea tickets from CheckMK alerts with bidirectional monitoring of service availability.

## Index

- [Overview](#-overview)
- [Components](#-components)
- [Installation](#-installation)
- [CheckMK Configuration](#%EF%B8%8F-checkmk-configuration)
- [Cron Configuration](#-cron-configuration)
- [Test and Verify](#-test-and-verify)
- [Troubleshooting](#-troubleshooting)
- [FAQ](#-faq)

---

## Overview

This system automates the management of Ydea tickets for CheckMK alerts with the following features:

### Alert CheckMK → Ydea Ticket

- **New CRITICAL/DOWN alert** → Create automatic ticket
- **Change status** → Add private note (not visible to the customer)
- **Flapping detection** → Alert if service changes status frequently
- **Duplicate prevention** → Smart cache to avoid multiple tickets
- **Summary notes** → Complete tracking of status changes

### Ydea monitoring

- **Periodic check** (every 15 min) of Ydea API availability
- **Email notification** if Ydea is not reachable
- **Recovery notification** when service comes back online

---

## Components

### 1. `ydea_realip` (in `script-notify-checkmk/`)

CheckMK notification script that manages alerts and creates/updates Ydea tickets.

**Features:**

- Get environment variables from CheckMK (`NOTIFY_*`)
- Identifies unique ticket for IP/Hostname + Service
- Create ticket on CRITICAL/DOWN alert
- Add private notes on status changes
- Detect flapping (5+ changes in 10 minutes)
- Cache: `/tmp/ydea_checkmk_tickets.json`

### 2. `ydea-health-monitor.sh` (in `Ydea-Toolkit/`)

Periodic monitor of Ydea API availability.

**Features:**

- Test Ydea login every 15 minutes (via cron)
- Threshold 3 failures before notifying
- Email alert if Ydea down
- Email recovery when back up
- State: `/tmp/ydea_health_state.json`

### 3. `mail_ydea_down` (in `script-notify-checkmk/`)

Email notification script for Ydea offline.

**Features:**

- Professional HTML email with details
- Information on impact and actions
- Used by `ydea-health-monitor.sh`

---

## Installation

### Prerequisites

1. **CheckMK** already installed and working
2. **Ydea Toolkit** configured in `/opt/ydea-toolkit/`
3. **Ydea credentials** (ID and API Key)

### Step 1: Copy Script

```bash
# From the repository on CheckMK server
cd /path/to/checkmk-tools

# Copy CheckMK notification script
sudo cp script-notify-checkmk/ydea_realip \
   /omd/sites/monitoring/local/share/check_mk/notifications/

sudo cp script-notify-checkmk/mail_ydea_down \
   /omd/sites/monitoring/local/share/check_mk/notifications/

# Make executable
sudo chmod +x /omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip
sudo chmod +x /omd/sites/monitoring/local/share/check_mk/notifications/mail_ydea_down

# Copy health monitor
sudo cp Ydea-Toolkit/ydea-health-monitor.sh /opt/ydea-toolkit/
sudo chmod +x /opt/ydea-toolkit/ydea-health-monitor.sh
```

### **Step 2: Configure Credentials**

```bash
# Edit .env with your credentials
sudo nano /opt/ydea-toolkit/.env
```

Enter:

```bash
export YDEA_ID="your_company_id"
export YDEA_API_KEY="your_api_key"
export YDEA_ALERT_EMAIL="massimo.palazzetti@nethesis.it"
```

### Step 3: Initial Test

```bash
# Ydea login test
cd /opt/ydea-toolkit
source .env
./ydea-toolkit.sh login
# Expected output: Login (valid token ~1h)

# Test health monitor
./ydea-health-monitor.sh
# Expected output: [timestamp] Ydea API reachable
```

---

## CheckMK configuration

### Setup Notification Rule

1. **Log in to CheckMK** → **Setup** → **Notifications**

2. **Create new rule**: "Ydea Ticketing"

3. **Configuration:**

   **Contact Selection:**
   - Specify users/groups who should receive tickets

   **Conditions:**
   - **Match host/service labels:** `real_ip` (optional, if using labels)
   - **Match event type:** State changes
   - **Restrict to certain states:**
     - Host: DOWN
     - Service: CRITICAL, WARNING (optional)

   **Notification Method:**
   - Select: **Custom notification script**
   - Script name: `ydea_realip`

4. **Save** and **Activate Changes**

### Advanced Configuration Example

```python
# In WATO Rules → Notifications
{
  "description": "Ydea Ticketing - Critical Alert",
  "disabled": False,
  "comment": "Create Ydea tickets for critical alerts with automatic note management",
  
  # Match conditions
"match_servicestate": ["CRIT", "WARN"],
  "match_hoststate": ["DOWN"],
  "match_event": "statechange",
  
  # Notification
  "notify_plugin": ("ydea_realip", {}),
  
  # Contact selection
  "contact_all": False,
  "contact_users": ["admin"],
}
```

---

## Chron. Configuration

### Setup Cron Job for Health Monitor

```bash
# Edit CheckMK site crontab
sudo su - monitoring
crontab -e
```

Add:

```cron
# Ydea Health Monitor - every 15 minutes
*/15 * * * * /opt/ydea-toolkit/ydea-health-monitor.sh >> /tmp/ydea_health.log 2>&1
```

Or as root user:

```bash
sudo crontab -e
```

```cron
*/15 * * * * /opt/ydea-toolkit/ydea-health-monitor.sh >> /var/log/ydea_health.log 2>&1
```

### Check Chron

```bash
# Cron jobs list
crontab -l

# Monitor logs
tail -f /tmp/ydea_health.log
```

---

## Test and Verification

### Test 1: Manual CheckMK Notification

```bash
# Simulate SERVICE CRITICAL notification
sudo su - monitoring

export NOTIFY_WHAT="SERVICE"
export NOTIFY_HOSTNAME="test-server"
export NOTIFY_HOSTADDRESS="192.168.1.100"
export NOTIFY_SERVICEDESC="CPU Load"
export NOTIFY_SERVICESTATE="CRIT"
export NOTIFY_LASTSERVICESTATE="OK"
export NOTIFY_SERVICEOUTPUT="CPU load at 95%"
export NOTIFY_SERVICESTATETYPE="HARD"

/omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip
```

**Expected output:**

```text
[2025-11-13 14:30:00] SERVICE Alert: test-server (192.168.1.100) - CPU Load | OK -> CRIT
[2025-11-13 14:30:01] Ticket Created: #12345 for 192.168.1.100:CPU Load
```

### Test 2: State Change (Private Note)

```bash
# Simulate alert return (CRIT → OK)
export NOTIFY_SERVICESTATE="OK"
export NOTIFY_LASTSERVICESTATE="CRIT"
export NOTIFY_SERVICEOUTPUT="CPU load normal at 35%"

/omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip
```

**Expected output:**

```text
[2025-11-13 14:35:00] SERVICE Alert: test-server (192.168.1.100) - CPU Load | CRIT -> OK
[2025-11-13 14:35:01] Existing Ticket Found: #12345
[2025-11-13 14:35:02] Private Note added to ticket #12345
```

### Test 3: Health Monitor

```bash
# Run manually
/opt/ydea-toolkit/ydea-health-monitor.sh

# Check status
cat /tmp/ydea_health_state.json
```

### Test 4: Check Cache

```bash
# Show cached tickets
cat /tmp/ydea_checkmk_tickets.json | jq .

# Example output:

```json
{
  "192.168.1.100:CPU Load": {
    "ticket_id": "12345",
    "state": "OK",
    "created_at": "1699887000",
    "last_update": "1699887300"
  }
}
```

---

## Troubleshooting

### Problem: Ticket is not created

Check 1: CheckMK Log

```bash
tail -f /omd/sites/monitoring/var/log/notify.log
```

Check 2: Script permissions

```bash
ls -la /omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip
# Must be: -rwxr-xr-x (executable)
```

Check 3: Ydea credentials

```bash
cd /opt/ydea-toolkit
source .env
./ydea-toolkit.sh login
```

Check 4: Debug mode

```bash
# Enable debugging in .env
export DEBUG_YDEA=1

# Rerun notification and check output
```

### Problem: Email Ydea down does not arrive

Check 1: Sendmail configured

```bash
echo "Test mail" | mail -s "Test" massimo.palazzetti@nethesis.it
```

Check 2: Email script path

```bash
ls -la /omd/sites/monitoring/local/share/check_mk/notifications/mail_ydea_down
```

Check 3: Log health monitor

```bash
tail -f /tmp/ydea_health.log
```

### Problem: Too many duplicate tickets

**Cause:** Cache corrupted or not accessible

**Solution:**

```bash
# Clear cache
sudo rm /tmp/ydea_checkmk_tickets.json
sudo rm /tmp/ydea_checkmk_flapping.json

# Recreate with correct permissions
sudo touch /tmp/ydea_checkmk_tickets.json
sudo chmod 666 /tmp/ydea_checkmk_tickets.json
```

### Problem: Flapping not detected

**Check thresholds:**

```bash
# In ydea_realip, check:
FLAPPING_THRESHOLD=5 # Number of state changes
FLAPPING_WINDOW=600 # 10 minute window
```

**Check flapping cache:**

```bash
cat /tmp/ydea_checkmk_flapping.json | jq .
```

---

## FAQ

### Q: Can I change the format of private notes?

**A:** Yes, edit the `NOTE=` section in the `ydea_realip` script (around line 280-290).

### Q: How do I automatically close tickets when the alert is cleared?

**A:** Tickets currently remain open with private note. For automatic closing, edit the script by adding:

```bash
if [[ "$STATE" == "OK" ]]; then
  "$YDEA_TOOLKIT" close "$TICKET_ID" "Alert automatically closed"
fi
```

### Q: Can I filter which services create tickets?
**A:** Yes, in CheckMK notification rule add conditions on service names or labels.

### Q: How do I change the health monitor interval?

**A:** Edit the cron job (ex: `*/5 * * * *` for every 5 minutes).

### Q: How do I see all automatically created tickets?

**A:**

```bash
cat /tmp/ydea_checkmk_tickets.json | jq 'to_entries | .[] | {service: .key, ticket: .value.ticket_id}'
```

### Q: Does the system work with CheckMK Raw Edition?

**A:** Yes, compatible with all CheckMK editions (Raw, Enterprise, Cloud).

### Q: Can I use Telegram instead of email for Ydea down?

**A:** Yes, edit `ydea-health-monitor.sh` to call a Telegram script instead of `mail_ydea_down`.

---

## Maintenance

### Periodic Cache Cleanup

```bash
# Cleanup script (run weekly)
#!/bin/bash
# cleanup-ydea-cache.sh

# Remove tickets older than 30 days
NOW=$(date +%s)
MAX_AGE=$((30*24*3600))

jq --arg now "$NOW" --arg max "$MAX_AGE" '
  to_entries | 
  map(select(($now|tonumber) - (.value.created_at|tonumber) < ($max|tonumber))) | 
  from_entries
' /tmp/ydea_checkmk_tickets.json > /tmp/ydea_checkmk_tickets.json.tmp

mv /tmp/ydea_checkmk_tickets.json.tmp /tmp/ydea_checkmk_tickets.json
```

### Backup Configuration

```bash
# Weekly backup
tar czf ydea-integration-backup-$(date +%Y%m%d).tar.gz \
  /opt/ydea-toolkit/.env \
  /omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip \
  /omd/sites/monitoring/local/share/check_mk/notifications/mail_ydea_down \
  /tmp/ydea_checkmk_tickets.json
```

---

## Support

For problems or questions:

1. Check the logs: `/omd/sites/monitoring/var/log/notify.log`
2. Check cache: `/tmp/ydea_checkmk_tickets.json`
3. Manually test the scripts as shown above

---

## Changelog

### v1.0.0 (2025-11-13)

- First CheckMK → Ydea integration release
- Automatic ticket management with private notes
- Flapping detection
- Ydea health monitoring with email notification
- Duplicate prevention with intelligent cache

---

**Documentation updated:** November 13, 2025  
**Author:** Ydea-Toolkit system  
**Repository:** checkmk-tools