# CheckMK Host Labels Configuration Template
> **Category:** Operational

# Template to configure 'real_ip' labels in CheckMK hosts

## OBJECTIVE
Configure the 'real_ip' label in CheckMK hosts to enable 
using real IP in emails instead of 127.0.0.1

## PREREQUISITES
- Administrative access to CheckMK Web UI
- Know the public/real IP of the CheckMK server
- Permissions to modify host configuration

## CONFIGURATION VIA WEB UI

### Method 1: Single Host Configuration

1. **Log in to CheckMK Web UI**
   ```
   URL: https://YOUR_CHECKMK_SERVER/YOUR_SITE/
   ```

2. **Navigate to host configuration**
   ```
   Setup → Hosts → [Select CheckMK server host]
   ```

3. **Add label 'real_ip'**
   ```
   Section: Host tags
   → Effective host tags
   → Host labels
   → Add new label
   
   Label key: real_ip
   Label value: YOUR_REAL_IP_ADDRESS
   ```

4. **Configuration examples**
   ```
   Label key: real_ip
   Label value: 192.168.1.100 # IP LAN
   
   Label key: real_ip  
   Label value: 203.0.113.50 # Public IP
   
   Label key: real_ip
   Label value: example.com # FQDN (if resolves correctly)
   ```

5. **Save and activate**
   ```
   → Save & go to folder
   → Activate affected
   → Activate changes
   ```

### Method 2: Configuration via File (Advanced)

1. **Log in to CheckMK server**
   ```bash
   ssh user@checkmk-server
   on - SITENAME
   ```

2. **Change host configuration**
   ```bash
   # Find the host configuration file
   find etc/check_mk/conf.d/ -name "*.mk" -exec grep -l "YOUR_HOSTNAME" {} \;
   
   # Edit the found file
   vi etc/check_mk/conf.d/wato/hosts.mk
   ```

3. **Add label in configuration**
   ```python
   # Example of host configuration with label
   all_hosts += [
       "your-checkmk-server|host|wato|/",
   ]
   
   # Add label
   host_labels.update({
       "your-checkmk-server": {
           "real_ip": "192.168.1.100",
       },
   })
   ```

4. **Activate changes**
   ```bash
   cmk -R
   # Or via Web UI: Activate changes
   ```

## CHECK CONFIGURATION

### Testing via Web UI
1. **Check applied label**
   ```
   Monitoring → Hosts → [Select host]
   → "Properties" tab
   → Check the presence of the "real_ip" label
   ```

### Test via Command Line
```bash
# On CheckMK server
on - SITENAME

# Check host label
cmk --debug -v YOUR_HOSTNAME | grep -i labels

# Test notification variables
export NOTIFY_HOSTLABEL_real_ip="192.168.1.100"
echo $NOTIFY_HOSTLABEL_real_ip
```

### Test Script Notification
```bash
# Test with mail_realip_graphs script
export NOTIFY_CONTACTEMAIL="test@domain.com"
export NOTIFY_HOSTNAME="your-server"
export NOTIFY_HOSTLABEL_real_ip="192.168.1.100"
export NOTIFY_WHAT="HOST"
export NOTIFY_NOTIFICATIONTYPE="PROBLEM"

# Run scripts for testing
./local/share/check_mk/notifications/mail_realip_graphs
```

## CONFIGURATION EXAMPLES

### Example 1: Server with Static IP LAN
```
Host: checkmk-prod
Real IP: 192.168.10.50
Label: real_ip = 192.168.10.50

Email result:
- Link: https://192.168.10.50/monitoring/check_mk/...
- Graphs: Generated with IP 192.168.10.50
```

### Example 2: Server with Public IP
```
Host: monitoring.company.com  
Real IP: 203.0.113.100
Label: real_ip = 203.0.113.100

Email result:
- Link: https://203.0.113.100/monitoring/check_mk/...
- Charts: Publicly accessible
```

### Example 3: Server with FQDN
```
Host: internal monitoring
Real IP: monitoring.internal.company.com
Label: real_ip = monitoring.internal.company.com

Email result:
- Link: https://monitoring.internal.company.com/site/check_mk/...
- Charts: Automatic DNS resolution
```

## ATTENTION

### Security Considerations
- **Public IPs**: Make sure CheckMK is only publicly accessible if necessary
- **Firewall**: Configure firewall rules appropriately
- **SSL/TLS**: Always use HTTPS for public access

### Network Considerations
- **DNS Resolution**: If you use FQDN, make sure it resolves correctly
- **Reachability**: The IP/FQDN must be reachable by email clients
- **Certificates**: For HTTPS, certificates must be valid for the IP/FQDN used

## TROUBLESHOOTING

### Problem: Label not applied
```bash
# Check syntax configuration file
cmk --check-config

# Restart CheckMK services
cmk -R
systemctl restart checkmk-SITENAME
```

### Problem: Script cannot find real_ip
```bash
# Check notification environment variables
env | grep NOTIFY_HOSTLABEL

# Script debugging
PYTHONDONTWRITEBYTECODE=1 python3 -B -c "
import os
real_ip = os.environ.get('NOTIFY_HOSTLABEL_real_ip')
print(f'Real IP found: {real_ip}')
"
```

### Problem: Email still with 127.0.0.1
- Verify that mail_realip_graphs script is used
- Check active notification rules
- Check host label configured correctly

## CONFIGURATION CHECKLIST

- [ ] Label 'real_ip' added to host
- [ ] Correct label value (reachable IP/FQDN)
- [ ] Changes activated in CheckMK
- [ ] mail_realip_graphs script installed
- [ ] Notification rule configured to use new script
- [ ] Notification test sent and verified
- [ ] Received emails show real IP instead of 127.0.0.1
- [ ] Graphics working and accessible via real IP

---

** Note **: This configuration is critical for correct 
functioning of the email system with real IP and graphics enabled.