#!/usr/bin/env python3
"""ydea_templates.py - Default templates for Ydea tickets

Generate JSON for ticket creation via Ydea API with predefined templates
for various scenarios: infrastructure, applications, security, maintenance.

Usage:
    ydea_templates.py server-down <hostname> [service]
    ydea_templates.py disk-full <hostname> <mount_point> <usage_%>
    ydea_templates.py app-errors <app_name> <error_rate_%> [threshold]
    
Examples:
    ydea_templates.py server-down web-prod-01 nginx
    ydea_templates.py disk-full server-01 /var 92

Version: 1.0.0 (ported from Bash)"""

VERSION = "1.0.0"

import sys
import json
from datetime import datetime, timedelta
from typing import Dict, Any


# ===== TEMPLATE INFRASTRUTTURA =====

def template_server_down(hostname: str, service: str = "N/A") -> Dict[str, Any]:
    """Template for server unreachable"""
    return {
        "title": f"[CRITICAL] Server {hostname} non raggiungibile",
        "description": f"""Server Down Alert

**Details:**
- Hostname: {hostname}
- Service: {service}
- Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- Detected by: Automatic monitoring system

**Impact:**
- [ ] Completely offline service
- [ ] Degraded performance
- [ ] Limited access

**Immediate actions:**
1. Check network connectivity
2. Check hardware status
3. Check system logs
4. Attempt restart if appropriate

**Diagnostic Commands:**
```bash
ping {hostname}
ssh {hostname} 'uptime; systemctl status'
journalctl -xe
```

**Priority:** CRITICAL
**SLA:** 15 minutes""",
        "priority": "critical",
        "tags": ["infrastruttura", "downtime", "server"]
    }


def template_backup_failed(backup_job: str, error_msg: str = "Unknown error") -> Dict[str, Any]:
    """Template for failed backup"""
    return {
        "title": f"[HIGH] Backup fallito: {backup_job}",
        "description": f"""Backup Failure Alert

**Job Details:**
- Job name: {backup_job}
- Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- Error: {error_msg}

**Impact:**
- [ ] Data not protected for this cycle
- [ ] RPO at risk
- [ ] Storage backup not updated

**Action Required:**
1. Check available disk space
2. Check file/directory permissions
3. Verify remote storage connectivity
4. Check detailed backup logs
5. Attempt manual backup if possible

**Log Path:**
```
/var/log/backup/{backup_job}.log
```

**Priority:** HIGH
**SLA:** 2 hours""",
        "priority": "high",
        "tags": ["backup", "storage", "dati"]
    }


def template_disk_full(hostname: str, mount_point: str, usage: str) -> Dict[str, Any]:
    """Template for almost full disk"""
    return {
        "title": f"[HIGH] Disco quasi pieno su {hostname}:{mount_point}",
        "description": f"""Disk Space Alert

**Details:**
- Hostname: {hostname}
- Mount Point: {mount_point}
- Usage: {usage}%
- Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Potential impact:**
- [ ] Applications may fail
- [ ] Logs may not be written
- [ ] Database at risk of corruption
- [ ] System may become unstable

**Immediate actions:**
1. Identify larger files
2. Clean old logs
3. Remove temporary files
4. Check for expansion needs

**Cleaning commands:**
```bash
# Find large files
du -sh {mount_point}/* | sort -rh | head -20

# Clean old logs
find /var/log -type f -name '*.log' -mtime +30 -delete

# Clear apt/yum cache
apt-get clean # or yum clean all

# Empty trash
rm -rf ~/.local/share/Trash/*
```

**Priority:** HIGH
**SLA:** 4 hours""",
        "priority": "high",
        "tags": ["storage", "disk", "infrastruttura"]
    }


def template_ssl_expiring(domain: str, days_left: str) -> Dict[str, Any]:
    """Template for expiring SSL certificate"""
    try:
        expiry_date = (datetime.now() + timedelta(days=int(days_left))).strftime('%Y-%m-%d')
    except:
        expiry_date = "N/A"
    
    return {
        "title": f"[MEDIUM] Certificato SSL in scadenza per {domain}",
        "description": f"""SSL Certificate Expiration Warning

**Details:**
- Domain: {domain}
- Days remaining: {days_left}
- Expiry date: {expiry_date}
- Date/Time control: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Impact if it expires:**
- [ ] Website inaccessible
- [ ] Browser errors for users
- [ ] API may fail
- [ ] Email may not work

**Action Required:**
1. Renew certificate via CA
2. Update web server configuration
3. Test new certificate
4. Update monitoring

**Let's Encrypt renewal:**
```bash
certbot renew --dry-run # test
certbot renew # effective renewal
sudo systemctl reload nginx
```

**Verify certificate:**
```bash
echo | openssl s_client -servername {domain} -connect {domain}:443 2>/dev/null | openssl x509 -noout -dates
```

**Priority:** MEDIUM
**SLA:** Before expiration""",
        "priority": "normal",
        "tags": ["ssl", "sicurezza", "certificati"]
    }


# ===== TEMPLATE APPLICAZIONI =====

def template_app_error_rate(app_name: str, error_rate: str, threshold: str = "5") -> Dict[str, Any]:
    """Template for high error rate"""
    return {
        "title": f"[HIGH] Error rate elevato per {app_name}",
        "description": f"""Application Error Rate Alert

**Details:**
- Application: {app_name}
- Error rate: {error_rate}%
- Threshold: {threshold}%
- Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Metrics:**
- Total requests: [TO BE CHECKED]
- Errors: [MUST CHECK]
- Most affected endpoints: [TO BE CHECKED]

**Immediate actions:**
1. Check application log
2. Check dependencies (DB, cache, external APIs)
3. Check recent deployments
4. Check system resources
5. Consider rollbacks if necessary

**Logs to check:**
```bash
tail -f /var/log/{app_name}/error.log
grep -i 'error\\|exception' /var/log/{app_name}/*.log | tail -50
```

**Priority:** HIGH
**SLA:** 1 hour""",
        "priority": "high",
        "tags": ["applicazione", "errori", "performance"]
    }


def template_db_slow_queries(db_name: str, slow_count: str) -> Dict[str, Any]:
    """Template for slow database queries"""
    return {
        "title": f"[MEDIUM] Query lente rilevate su database {db_name}",
        "description": f"""Database Performance Alerts

**Details:**
- Database: {db_name}
- Slow queries: {slow_count}
- Period: last hour
- Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Impact:**
- [ ] Degraded application performance
- [ ] Timeout for users
- [ ] High DB load

**Action Required:**
1. Identify problematic queries
2. Check for missing indexes
3. Analyze execution plans
4. Check statistics tables
5. Evaluate optimizations

**MySQL/MariaDB Diagnostics:**
```sql
-- Slower queries
SELECT * FROM mysql.slow_log ORDER BY query_time DESC LIMIT 10;

-- Active queries
FULL PROCESS SHOW;

-- Indexes not used
SELECT * FROM sys.schema_unused_indexes;
```

**PostgreSQL Diagnostics:**
```sql
-- Slow queries
SELECT * FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10;

-- Active sessions
SELECT * FROM pg_stat_activity WHERE state = 'active';
```

**Priority:** MEDIUM
**SLA:** 4 hours""",
        "priority": "normal",
        "tags": ["database", "performance", "ottimizzazione"]
    }


# ===== TEMPLATE SICUREZZA =====

def template_security_breach(incident_type: str, affected_system: str) -> Dict[str, Any]:
    """Security Incident Template"""
    return {
        "title": f"[CRITICAL] Potenziale incidente di sicurezza: {incident_type}",
        "description": f"""SECURITY INCIDENT ALERT

**WARNING: IMMEDIATE INCIDENT RESPONSE REQUIRED**

**Details:**
- Incident type: {incident_type}
- Affected system: {affected_system}
- Date/Time detection: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- Severity: CRITICAL

**Immediate actions (DO NOT MODIFY THE SYSTEM):**
1. Isolate compromised system from network
2. Preserve logs and evidence
3. Notify security team
4. Activate incident response plan
5. Document every action

**DON'T:**
- Do not restart the system
- Do not modify files
- Do not delete logs
- Do not inform publicly

**Emergency contacts:**
- Security Team: [INSERT CONTACT]
- Manager: [INSERT CONTACT]
- Legal: [INSERT CONTACT]

**Evidence preservation:**
```bash
# Log backups
tar czf /tmp/incident-logs-$(date +%s).tar.gz /var/log/

# Capture system state
ps auxf > /tmp/processes.txt
netstat -tulpn > /tmp/connections.txt
lsof > /tmp/openfiles.txt
```

**Priority:** CRITICAL
**SLA:** IMMEDIATE""",
        "priority": "critical",
        "tags": ["sicurezza", "incident", "emergenza"]
    }


def template_failed_login(username: str, ip_address: str, attempts: str) -> Dict[str, Any]:
    """Template for failed login attempts"""
    return {
        "title": f"[HIGH] Tentativi di login falliti per {username}",
        "description": f"""Failed Login Attempts Alert

**Details:**
- Username: {username}
- IP Address: {ip_address}
- Attempts: {attempts}
- Period: last hour
- Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Immediate actions:**
1. Check if brute force attack
2. Check other compromised accounts
3. Check if IP already known
4. Consider temporary IP blocking
5. Notify user if legitimate

**Log analysis:**
```bash
# SSH failed logins
grep 'Failed password' /var/log/auth.log | tail -50

# Most active IPs
grep 'Failed password' /var/log/auth.log | awk '{{print $(NF-3)}}' | sort | uniq -c | sort -rn

# IP blocking with fail2ban
fail2ban-client status sshd
fail2ban-client set sshd banip {ip_address}
```

**IP geolocation:**
```bash
whois {ip_address} | grep -i country
curl -s ipinfo.io/{ip_address}
```

**Priority:** HIGH
**SLA:** 2 hours""",
        "priority": "high",
        "tags": ["sicurezza", "autenticazione", "brute-force"]
    }


# ===== TEMPLATE MANUTENZIONE =====

def template_planned_maintenance(system: str, date_time: str, duration: str) -> Dict[str, Any]:
    """Template for scheduled maintenance"""
    return {
        "title": f"[PLANNED] Manutenzione programmata: {system}",
        "description": f"""Scheduled Maintenance

**Details:**
- System: {system}
- Date/Time: {date_time}
- Estimated duration: {duration}
- Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Planned works:**
- [ ] Full system backup
- [ ] Update operating system
- [ ] Update applications
- [ ] Restarting services
- [ ] Post-maintenance testing

**Expected impact:**
- [ ] Total downtime
- [ ] Reduced performance
- [ ] Limited access
- [ ] No impact

**Pre-Maintenance Checklist:**
- [ ] Backup verified
- [ ] Users notified
- [ ] Change request approved
- [ ] Rollback plan ready
- [ ] Support team alerted

**Post-maintenance checklist:**
- [ ] Services restarted
- [ ] Smoke test completed
- [ ] Monitoring verified
- [ ] Baseline performance re-established
- [ ] Users notified (completion)

**Rollback procedures:**
```bash
# [INSERT ROLLBACK COMMANDS]
```

**Priority:** NORMAL
**Deadline:** {date_time}""",
        "priority": "normal",
        "tags": ["manutenzione", "programmato", "change"]
    }


# ===== CLI =====

def print_usage():
    """Print usage"""
    print("""Ydea Ticket Templates

USE:
  # Infrastructure template
  ydea_templates.py server-down <hostname> [service]
  ydea_templates.py backup-failed <job_name> [error_msg]
  ydea_templates.py disk-full <hostname> <mount_point> <usage_%>
  ydea_templates.py ssl-expiring <domain> <days_left>
  
  # Application templates
  ydea_templates.py app-errors <app_name> <error_rate_%> [threshold]
  ydea_templates.py db-slow <db_name> <slow_query_count>
  
  # Security template
  ydea_templates.py security-breach <incident_type> <affected_system>
  ydea_templates.py failed-login <username> <ip_address> <attempts>
  
  # Maintenance template
  ydea_templates.py maintenance <system> <date_time> <duration>

EXAMPLES:
  # Print JSON template
  ydea_templates.py server-down web-prod-01 nginx
  
  # Use in Python scripts
  import ydea_templates
  template = ydea_templates.template_disk_full("server-01", "/var", "92")
  print(json.dumps(template, indent=2))""", file=sys.stderr)


def main():
    """Main function"""
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    
    command = sys.argv[1]
    args = sys.argv[2:]  # type: ignore
    
    template = None
    
    if command == "server-down":
        if len(args) < 1:
            print("Errore: hostname richiesto", file=sys.stderr)
            sys.exit(1)
        template = template_server_down(*args)
    
    elif command == "backup-failed":
        if len(args) < 1:
            print("Errore: job_name richiesto", file=sys.stderr)
            sys.exit(1)
        template = template_backup_failed(*args)
    
    elif command == "disk-full":
        if len(args) < 3:
            print("Errore: hostname, mount_point, usage richiesti", file=sys.stderr)
            sys.exit(1)
        template = template_disk_full(*args)
    
    elif command == "ssl-expiring":
        if len(args) < 2:
            print("Errore: domain, days_left richiesti", file=sys.stderr)
            sys.exit(1)
        template = template_ssl_expiring(*args)
    
    elif command == "app-errors":
        if len(args) < 2:
            print("Errore: app_name, error_rate richiesti", file=sys.stderr)
            sys.exit(1)
        template = template_app_error_rate(*args)
    
    elif command == "db-slow":
        if len(args) < 2:
            print("Errore: db_name, slow_count richiesti", file=sys.stderr)
            sys.exit(1)
        template = template_db_slow_queries(*args)
    
    elif command == "security-breach":
        if len(args) < 2:
            print("Errore: incident_type, affected_system richiesti", file=sys.stderr)
            sys.exit(1)
        template = template_security_breach(*args)
    
    elif command == "failed-login":
        if len(args) < 3:
            print("Errore: username, ip_address, attempts richiesti", file=sys.stderr)
            sys.exit(1)
        template = template_failed_login(*args)
    
    elif command == "maintenance":
        if len(args) < 3:
            print("Errore: system, date_time, duration richiesti", file=sys.stderr)
            sys.exit(1)
        template = template_planned_maintenance(*args)
    
    else:
        print_usage()
        sys.exit(1)
    
    # Print JSON
    print(json.dumps(template, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
