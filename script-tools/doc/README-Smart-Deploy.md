# CheckMK Smart Deploy - Hybrid System
> **Category:** Operational

## **Files in System:**

- **`smart-deploy-hybrid.sh`** - **Master installer** (this is what you use!)
- **`smart-wrapper-template.sh`** - � **Base template** (wrapper structure that is replicated)
- **`README-Smart-Deploy.md`** - **Documentation** (this file)

## **What is it**

An intelligent system that combines:
- ** Download from GitHub ** to always have the latest version
- **Local cache** to work even without internet
- Transparent **Auto-update** with each CheckMK run

## **How It Works**

### **1. Initial Deployment**
```bash
# On the target server
curl -s https://raw.githubusercontent.com/nethesis/checkmk-tools/main/script-Tools/smart-deploy-hybrid.sh | sudo bash
```

### **2. Structure Created**
```
/usr/lib/check_mk_agent/local/
├── check_cockpit_sessions # Smart wrapper
├── check_dovecot_status # Smart wrapper  
├── check_ssh_root_sessions # Smart wrapper
└── check_postfix_status # Smart wrapper

/var/cache/checkmk-scripts/
├── check_cockpit_sessions.sh # Local cache
├── check_dovecot_status.sh # Local cache
├── update-all.sh # Maintenance script
└── *.info # Update info
```

### **3. Execution Logic**
```
CheckMK run script → Wrapper try GitHub → Success? Refresh cache → Perform local cache
                                           ↓
                                         Fail? → Use existing cache
```

## **Advantages**

- **Always updated** (when there is internet)
- **Always working** (even without internet)  
- **Zero maintenance** (transparent auto-update)
- **Robust fallback** (secure local cache)
- **Fast Deploy** (one command on all servers)

## **Useful Commands**

### **Manual Test**
```bash
# Test a single script
/usr/lib/check_mk_agent/local/check_cockpit_sessions

# Force update everyone
/var/cache/checkmk-scripts/update-all.sh
```

### **Debugging**
```bash
# See cache
ls -la /var/cache/checkmk-scripts/

# See latest update info  
cat /var/cache/checkmk-scripts/check_cockpit_sessions.sh.info

# Manual download test
curl -s https://raw.githubusercontent.com/nethesis/checkmk-tools/main/script-check-ns7/check_cockpit_sessions.sh
```

## **Monitoring**

Self-report scripts if they fail to update:
```
2 check_cockpit_sessions - CRITICAL: No script available (GitHub unreachable, no cache)
```

## **Maintenance**

### **Add New Script**
1. Push the script to GitHub
2. Edit `smart-deploy-hybrid.sh` by adding `SCRIPTS` to the list
3. Re-deploy

### **Remove Script**
```bash
rm /usr/lib/check_mk_agent/local/script_name
rm /var/cache/checkmk-scripts/script_name.*
```

## **The Best of Both Worlds**

- **Automatic updates** like your colleague
- **Stability** of traditional local files
- **Zero single point of failure**