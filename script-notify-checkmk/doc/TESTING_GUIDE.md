# QUICK START TESTING GUIDE

## **Pre-Test Setup (5 minutes)**

### 1. Upload files to CheckMK server
```bash
# SCP/SFTP files to your CheckMK server
scp mail_realip_hybrid backup_and_deploy.sh pre_test_checker.sh user@your-checkmk-server:/tmp/
```

### 2. Connect to the server and prepare environment
```bash
ssh user@your-checkmk-server
sudo -i
cd /tmp
chmod +x *.sh
```

### 3. Environment control
```bash
# Check compatibility
./pre_test_checker.sh
```

---

## **Testing Phase (10 minutes)**

### Test 1: Dry Run (safe)
```bash
# Simulate deployment without modifications
./backup_and_deploy.sh --dry-run
```

### Test 2: Deploy with automatic backup
```bash
# Real deployment with automatic rollback
./backup_and_deploy.sh
```

### Test 3: FRP detection check
```bash
# Switch to CheckMK site user
up - $(cat /etc/omd/site)

# Manual test detection
PYTHONDONTWRITEBYTECODE=1 python3 -B -c "
import os, sys
# Simulate FRP scenario
os.environ['NOTIFY_HOSTADDRESS'] = '127.0.0.1:5000'  
os.environ['NOTIFY_HOSTLABEL_real_ip'] = '192.168.1.100'
os.environ['NOTIFY_HOSTNAME'] = 'test-host'
os.environ['NOTIFY_WHAT'] = 'HOST'

# Load script
exec(open('/omd/sites/$(cat /etc/omd/site)/local/share/check_mk/notifications/mail_realip_hybrid').read())
print('Detection OK!')
"
```

---

## **Real Notification Test (15 minutes)**

### 1. Configure test host with label real_ip

**Via WATO:**
1. Setup → Hosts → [Your Host] → Properties  
2. Custom attributes → Add: `real_ip = 192.168.1.100`
3. Save & Activate Changes

**Via config file:**
```bash
# Add to /etc/check_mk/conf.d/hosts.mk
extra_host_conf.setdefault("_real_ip", []).append(
    ("192.168.1.100", ["test-host"])
)
```

### 2. Configure notification rule

**WATO:** Setup → Notifications → New Rule:
- **Notification Method:** `mail_realip_hybrid`  
- **Contact Selection:** Your email
- **Host/Service Conditions:** Match your test host

### 3. Test notification
```bash
# Force notification test
up - $(cat /etc/omd/site)
cmk --notify-test test-host
```

### 4. Monitor results
```bash
# Check logs
tail -f /omd/sites/$(cat /etc/omd/site)/var/log/notify.log

# Check email content for:
# Working graphs (localhost:PORT used internally)
# Clickable URLs with real IP (192.168.1.100)
```

---

## **Rollback if necessary**

```bash
# Automatic deployment creates rollback scripts
ls /omd/sites/$(cat /etc/omd/site)/local/share/check_mk/notifications/backup_*/rollback.sh

# Perform rollback
/omd/sites/$(cat /etc/omd/site)/local/share/check_mk/notifications/backup_*/rollback.sh
```

---

## **Validation Checklist**

**After testing, check:**

- [ ] **Detection FRP:** Log confirmation "FRP scenario detected"
- [ ] **Graphics:** Email contains PNG attachments 
- [ ] **Email URL:** Links point to real IP (192.168.1.100)
- [ ] **Graphics URL:** Internal template uses localhost:PORT
- [ ] **No Errors:** clean notify.log
- [ ] **Rollback:** Works if needed

---

## **Expected Results**

**SUCCESS SCENARIO:**
```
EMAIL CONTENT:
- Subject: CheckMK notification
- Body: Text with real IP links (192.168.1.100)  
- Attachments: Graph PNG images
- Graph URL: http://192.168.1.100/site/check_mk/...

LOGS:
- "FRP scenario detected: HOSTADDRESS=127.0.0.1:5000, real_ip=192.168.1.100"
- "Graph generation successful"
- "Email sent successfully"
```

**IF FAILS:**
1. Check pre_test_checker.sh warnings
2. Check configured real_ip label
3. Check logs notify.log
4. Run rollback.sh
5. Report issues with specific logs

---

## **Quick Troubleshooting**

```bash
# Check script permissions
ls -la /omd/sites/*/local/share/check_mk/notifications/mail_realip_hybrid

# Test Python syntax
PYTHONDONTWRITEBYTECODE=1 python3 -B -c "compile(open('/omd/sites/*/local/share/check_mk/notifications/mail_realip_hybrid').read(), '/omd/sites/*/local/share/check_mk/notifications/mail_realip_hybrid', 'exec')"

# Verify environment variables in notification
env | grep NOTIFY_ | head -10

# Manual debug mode
export PYTHONUNBUFFERED=1
export DEBUG=1
```

---

 **Ready to rock? Start with `pre_test_checker.sh`!**