# CheckMK Distributed Monitoring - Setup Guide
> **Category:** Operational

## Architecture
```
VPS <your-checkmk-server> (Central Master)
├── Site: monitoring
├── Livestatus TCP: port 6557 (TLS)
└── Collect data from remote site

Local Box (Remote Site)
├── Site: monitoring
├── Connects to central via HTTPS
└── Send monitoring data to the central
```

## Phase 1: Remote Site Configuration (Local Box)

### 1.1 Run setup script
```bash
cd /opt/checkmk-tools && git pull
sudo bash /opt/checkmk-tools/distributed-monitoring-setup.sh
```

The script:
- Configure the site as remote
- Create automation user
- Generate secrets per connection
- Show the credentials to use

**Expected output:**
```
══════════════════════════ ══════════════════════════
Connection Information for Central Site:
══════════════════════════ ══════════════════════════
Site ID: local-box
Site URL: https://<your-checkmk-server>/monitoring/
Automation User: automation
Automation Secret: (secret string)
══════════════════════════ ══════════════════════════
```

** IMPORTANT:** Copy the secret, you will need it later!

---

## Phase 2: Central Site (VPS) configuration via UI

### 2.1 Log in to the CheckMK UI
1. Open browser: https://<your-checkmk-server>/monitoring/
2. Login with your credentials

### 2.2 Add Remote Site
1. Menu: **Setup → General → Distributed monitoring**
2. Click: **Add connection**

### 2.3 Configure Connection
Fill in the fields:

**Basic settings:**
- **Site ID:** `local-box`
- **Alias:** `Local Monitoring Site` (or name of your choice)

**Connection:**
- **Method:** `Connect to the remote site using Livestatus`
- **Protocol:** `Livestatus over HTTPS`
- **URL:** `https://<LOCAL-IP-BOX>/monitoring/check_mk/`
  - Or if the box has hostname: `https://hostname-box.locale/monitoring/check_mk/`
- **Port:** `443`

**Authentication:**
- **Username:** `automation`
- **Automation secret:** `<SECRET-COPIED-BEFORE>`

**Advanced settings:**
- Enable configuration replication
- Replicate Event Console configuration
- Sync with LDAP connections

**Host status:**
- Create host status
- **Host name:** `Local-Box-Status`

### 2.4 Test Connection
1. Click: **Test connection**
2. Check that it shows: **Connection successful**

### 2.5 Save
1. Click: **Save**
2. Click: **Activate pending changes** (orange icon at the top)

---

## Phase 3: Check Operation

### 3.1 Check on Central (VPS)
1. Menu: **Setup → General → Distributed monitoring**
2. Check Status: It should be **Online**

### 3.2 Add host on Remote Site
On the local box:
```bash
# Log in to the site
sudo -i -u monitoring
cd ~/
omd status

# Add a local host (e.g. the box itself)
# Via UI or via command line
```

### 3.3 Synchronize configuration
On the VPS UI:
1. Menu: **Setup → Hosts**
2. You should see the remote site hosts
3. Click: **Activate pending changes**

### 3.4 Check Dashboard
1. Menu: **Monitor → Overview → Main Overview**
2. You should see:
   - Central site host
   - Remote site host (with site icon)
   - Total aggregation

---

## Troubleshooting

### Problem: Connection failed
**Solution:**
```bash
# On the local box, check:
sudo omd status monitoring
sudo ss -tlnp | grep 6557

# VPS connection test:
curl -k https://<LOCAL-IP-BOX>/monitoring/check_mk/
```

### Problem: Authentication failed
**Solution:**
```bash
# On the local box, regenerate secret:
sudo -i -u monitoring
cd ~/
cat var/check_mk/web/automation/automation.secret

# Update the secret in the central UI
```

### Problem: Remote site shows as offline
**Solution:**
1. Check firewall on local box (port 443 open?)
2. Verify SSL certificates
3. Check log: `/omd/sites/monitoring/var/log/web.log`

---

## Important Notes

### Connection
- The remote site must be able to reach the central on port 6557
- If local box is behind NAT, consider FRP tunnel

### Security
- The connection uses TLS/SSL
- The automation secret is sensitive, treat it like a password

### Performances
- Data is aggregated in real time
- The central polls the remote every 60 seconds by default

### Configuration
- Configuration changes are made on the central
- The central replicates the config on the remote sites

---

## Useful Commands

### On the Remote Site
```bash
# Status site
sudo omd status monitoring

# Restart site
sudo omd restart monitoring

# View automation secret
sudo -u monitoring cat /omd/sites/monitoring/var/check_mk/web/automation/automation.secret
# Check Livestatus
echo "GET status" | unixcat /omd/sites/monitoring/tmp/run/live
```

### On the Central Site
```bash
# Test connection to remote
sudo -u monitoring lq "GET sites\nColumns: site_id name state"

# View remote site config
sudo -u monitoring cat /omd/sites/monitoring/etc/check_mk/multisite.d/wato/sites.mk
```

---

## References

- [CheckMK Documentation - Distributed Monitoring](https://docs.checkmk.com/latest/en/distributed_monitoring.html)
- [Livestatus Protocol](https://docs.checkmk.com/latest/en/livestatus.html)