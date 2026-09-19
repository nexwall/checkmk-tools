# CheckMK Auto-Upgrade Setup - Automatic Upgrade Configuration
> **Category:** Operational

## WARNING - Advanced Script

This script sets up **AUTOMATIC** CheckMK upgrades via crontab. This is a potentially risky operation that must be configured carefully.

## Description

Script to schedule automatic upgrades of CheckMK RAW Edition. The system will periodically check for the availability of new versions and perform the upgrade completely automatically and non-interactively.

## Components

### 1. Script Full (Interactive)
**Path:** `script-tools/full/upgrade_maintenance/setup-auto-upgrade-checkmk.sh`

Full version with interactive interface to configure automatic upgrades.

### 2. Remote Launcher
**Path:** `script-tools/remote/rsetup-auto-upgrade-checkmk.sh`

Launcher that downloads and runs the complete script directly from GitHub.

### 3. Upgrade Script
**Dependency:** `script-tools/full/upgrade_maintenance/upgrade-checkmk.sh`

Script that actually upgrades CheckMK (must be present).

## Security Features

- **Automatic backup** before each upgrade
- Fully automated **non-interactive upgrade**
- **Detailed logging** of all operations
- Optional **email notifications** for success/failure
- **Check version** - upgrade only if new version available
- **Automatic restart** of CheckMK site after upgrade
- **Backup crontab** before changes
- **Duplicate management** in crontab

## Prerequisites

### Software Required
- CheckMK RAW Edition installed
- `omd` command available
- Root permissions (sudo)
- `curl`, `wget`, `dpkg` installed
- `upgrade-checkmk.sh` script present in `script-tools/full/upgrade_maintenance/`

### Optional
- `mailutils` for email notifications

```bash
# Install mailutils if you want email notifications
apt install mailutils
```

## Usage

### Local Execution (Interactive)

```bash
# From the script folder
cd /path/to/script-tools/full
sudo bash setup-auto-upgrade-checkmk.sh
```

### Remote Execution

```bash
# Download and run in one command
bash <(curl -fsSL https://raw.githubusercontent.com/nethesis/checkmk-tools/main/script-tools/remote/rsetup-auto-upgrade-checkmk.sh)
```

## Scheduling Options

### 1. Weekly (RECOMMENDED)
- **Frequency:** Every Sunday
- **Default time:** 02:00
- **Cron:** `0 2 * * 0`
- **Pros:** Balance security and timely updates

### 2. Monthly
- **Frequency:** 1st day of the month
- **Default time:** 02:00
- **Chron:** `0 2 1 * *`
- **Pros:** Maximum stability, time to test new versions

### 3. Customized
- **Frequency:** Manual entry
- **Format:** `minute hour day month weekday`
- **Example:** `0 3 1.15 * *` (1st and 15th of the month at 03:00)

## Interactive Menu

```
╔════════════════════════════════ ════════════════════════════════╗
║ CheckMK Automatic Upgrade Configuration ║
╚════════════════════════════════ ════════════════════════════════╝

ATTENTION: You are about to set up AUTOMATIC CheckMK upgrades!

Important considerations:
  - The script will make automatic backup before each upgrade
  - The upgrade will be completely non-interactive
  - The CheckMK site will be restarted during the upgrade
  - Upgrades will ONLY occur if a new version is available

Are you sure you want to proceed? [y/N]:

Select the frequency of automatic upgrades:

  1) Weekly - Every Sunday at 02:00 (RECOMMENDED)
  2) Monthly - The first day of the month at 02:00
  3) Custom - Specify custom time and frequency
  4) Cancel

Choice [1-4]:
```

## Log files

### Location
```
/var/log/auto-upgrade-checkmk.log
```

### Log Format
```
[Sun Jan 12 02:00:01 2026] Starting CheckMK auto-upgrade
[INFO] Site: mysite
[INFO] Current version: 2.3.0p1
[INFO] Latest version: 2.3.0p2
Expected update: 2.3.0p1 -> 2.3.0p2
[INFO] Backups: /opt/omd/backups/mysite_pre-upgrade_20260112_020015.tar.gz
[INFO] Download: https://download.checkmk.com/checkmk/2.3.0p2/...
[INFO] Package installation (.deb)
[INFO] Stop site: mysite
[INFO] Site upgrade (omd update) - automatic mode
[INFO] Start site: mysite
[INFO] Version after upgrade: 2.3.0p2
[Sun Jan 12 02:08:45 2026] CheckMK upgrade completed successfully
```

### Log monitoring
```bash
# View the latest upgrades
tail -f /var/log/auto-upgrade-checkmk.log

# See last 100 lines
tail -n 100 /var/log/auto-upgrade-checkmk.log

# Look for errors
grep -i error /var/log/auto-upgrade-checkmk.log

# See all completed upgrades
grep "upgrade completed successfully" /var/log/auto-upgrade-checkmk.log
```

## Email notifications

### Configuration
During setup, the script asks if you want to receive email notifications:

```bash
Do you want to receive email notifications about upgrade results? [y/N]: yes
Enter your email address: admin@example.com
```

### Email Format - Success
```
Subject: CheckMK Auto-Upgrade Report
Body: CheckMK upgrade completed on monitor01 at Sun Jan 12 02:08:45 2026
```

### Email Format - Error
```
Subject: [ERROR] CheckMK Auto-Upgrade Failed
Body: CheckMK upgrade failed on monitor01 at Sun Jan 12 02:15:30 2026
```

## Backup and Restore

### CheckMK Automatic Backups
Before each upgrade a complete backup is created:
```
/opt/omd/backups/
├── mysite_pre-upgrade_20260112_020015.tar.gz
├── mysite_pre-upgrade_20260119_020012.tar.gz
└── mysite_pre-upgrade_20260126_020009.tar.gz
```

### Restore Backup CheckMK
```bash
# List of available backups
ls -lh /opt/omd/backups/

# Restore a specific backup
omd restore mysite /opt/omd/backups/mysite_pre-upgrade_20260112_020015.tar.gz

# Verify recovery
omd status mysite
```

### Backup Crontab
```
/root/crontab_backups/
└── crontab_backup_20260112_100530.txt
```

### Restore Crontab
```bash
# View available backups
ls -lh /root/crontab_backups/

# Restore a specific backup
crontab /root/crontab_backups/crontab_backup_20260112_100530.txt

# Verify recovery
crontab -l
```

## Crontab management

### View Current Entries
```bash
crontab -l
```

### Edit Manually
```bash
crontab -e
```

### Remove Auto-Upgrade CheckMK
```bash
crontab -l | grep -v "upgrade-checkmk.sh" | crontab -
```

## Best Practices

### 1. Execution Time
- **Recommended:** 02:00-04:00 (low traffic)
- **Avoid:** Rush hours and business hours
- **Weekend:** Preferable for production systems
- **Consider:** Server time zone

### 2. Upgrade Frequency
- **Critical production:** Monthly + preventive tests on staging environment
- **Standard production:** Weekly
- **Development/Testing:** Weekly is fine too
- **Never:** Daily (too risky)

### 3. Tracking
- Check logs **after each automatic upgrade**
- Set alerts for failures
- Check CheckMK operation post-upgrade
- Check disk space for backup

### 4. Backup Management
- Backups accumulate in `/opt/omd/backups/`
- Implement backup rotation (keep last 5-10)
- Regularly check the integrity of backups
- Consider additional external backups

### 5. Testing
- **First time:** Test the manual upgrade
- **Staging:** Test on test environment first
- **Check:** Check the first automatic upgrade
- **Rollback:** Be prepared to rollback if necessary

### 6. Notifications
- Configure email for administrators
- Integrate with existing monitoring systems
- Check that emails arrive correctly
- Initial email sending test

## Maintenance Script

### Cleaning Old Backups
```bash
#!/bin/bash
# Keep only the latest 5 backups for each site
cd /opt/omd/backups/
for site in $(omd sites | awk '{print $1}' | grep -v SITE); do
    ls -t ${site}_pre-upgrade_*.tar.gz | tail -n +6 | xargs -r rm
done
```

### Log Rotation
```bash
# Add to /etc/logrotate.d/checkmk-auto-upgrade
/var/log/auto-upgrade-checkmk.log {
    weekly
    rotate 12
    compressed
    delaycompress
    missingok
    notifempty
}
```

## Troubleshooting

### Upgrade fails

**1. Check active cron:**
```bash
systemctl status cron
systemctl start cron
```

**2. Check crontab entry:**
```bash
crontab -l | grep upgrade-checkmk
```

**3. Check cron log:**
```bash
grep CRON /var/log/syslog | grep upgrade-checkmk
```

**4. Manual test:**
```bash
bash /path/to/upgrade-checkmk.sh
```

### Upgrade fails

**1. Check detailed log:**
```bash
tail -n 200 /var/log/auto-upgrade-checkmk.log
```

**2. Check disk space:**
```bash
df -h
```

**3. Check dependencies:**
```bash
apt-get -f install
```

**4. Check download:**
```bash
ls -lh /tmp/checkmk-upgrade/
```

### Emails not arriving

**1. Check installed mailutils:**
```bash
dpkg -l | grep mailutils
apt install mailutils
```

**2. Email sending test:**
```bash
echo "Test email" | mail -s "Test" your@email.com
```
**3. Check email configuration:**
```bash
cat /etc/postfix/main.cf
```

### Interactive interface appears again

**1. Check omd update parameters:**
```bash
# Check the log to see if it uses -f and --conflict=install
grep "omd update" /var/log/auto-upgrade-checkmk.log
```

**2. Add extra protections** (edit upgrade-checkmk.sh):
```bash
DEBIAN_FRONTEND=noninteractive omd -f update --conflict=install "$SITE_NAME" < /dev/null
```

## Uninstall

### Complete Removal
```bash
#1. Remove crontab entry
crontab -l | grep -v "upgrade-checkmk.sh" | grep -v "^# Auto-upgrade CheckMK:" | crontab -

#2. Remove logs
rm /var/log/auto-upgrade-checkmk.log

#3. (Optional) Remove crontab backup
rm -rf /root/crontab_backups/

#4. (Optional) Remove old CheckMK backups
cd /opt/omd/backups/
rm *_pre-upgrade_*.tar.gz
```

### Temporary Suspension
```bash
# Comment out the line in the crontab (add # to the beginning)
crontab -e
```

## Configuration Examples

### Conservative Setup (Production)
```
Frequency: Monthly
Time: 02:00 Sunday night
Email: Yes
Log: Monitor weekly
Backup: Keep last 12 months
```

### Balanced Setup (Recommended)
```
Frequency: Weekly (Sunday)
Time: 02:00
Email: Yes
Log: Monitor monthly
Backup: Keep last 3 months
```

### Aggressive Setup (Development Only)
```
Frequency: Weekly (any day)
Time: 03:00
Email: Optional
Log: Check if it fails
Backup: Keep last month
```

## Integration with Monitoring

### CheckMK Self-Monitoring
Create a local check to monitor automatic upgrades:

```bash
# /usr/lib/check_mk_agent/local/check_auto_upgrade
#!/bin/bash
LOG_FILE="/var/log/auto-upgrade-checkmk.log"
LAST_RUN=$(grep "upgrade completed successfully" "$LOG_FILE" | tail -1)
DAYS_AGO=$(( ($(date +%s) - $(date -d "$(echo "$LAST_RUN" | cut -d']' -f1 | tr -d '[')" +%s)) / 86400 ))

if [ $DAYS_AGO -gt 14 ]; then
    echo "1 CheckMK_Auto_Upgrade - Last successful upgrade: $DAYS_AGO days ago"
elif [ $DAYS_AGO -gt 7 ]; then
    echo "1 CheckMK_Auto_Upgrade - Last successful upgrade: $DAYS_AGO days ago"
else
    echo "0 CheckMK_Auto_Upgrade - Last successful upgrade: $DAYS_AGO days ago"
fi
```

## Safety and Responsibility

### Disclaimer
- Automatic upgrades carry inherent risks
- Always test in staging environment first
- Maintain external and independent backups
- Actively monitor the system post-upgrade
- Be prepared for manual intervention in case of problems

### Safety Recommendations
1. **External backups** in addition to automatic ones
2. **Test environment** to validate upgrades
3. **Documentation** of custom configurations
4. **Rollback plan** tested and documented
5. **Contacts available** during upgrade windows
6. **Active monitoring** post-upgrade

## Support and Contributions

- **Repository:** https://github.com/nethesis/checkmk-tools
- **Issues:** https://github.com/nethesis/checkmk-tools/issues
- **Documentation:** `script-tools/doc/`

## Changelog

### Version 1.0 (2026-01-12)
- Initial release
- Interactive menu with frequency options
- Optional email notifications
- Complete logging
- Automatic backups
- Completely non-interactive upgrade
- Management of crontab duplicates
- Input validation

## License

This script is part of the checkmk-tools project.

## Final Notes

 **IMPORTANT:**
- This is a powerful but potentially dangerous tool
- ONLY use it if you completely understand the risks
- For critical systems, consider manual upgrades with preventive testing
- Upgrades may require server reboots
- Not all upgrades are backward-compatible

 **WHEN TO USE IT:**
- Development/test environments
- Non-critical systems
- With active monitoring and alerting
- With robust external backups
- When you have competence to handle problems

 **WHEN NOT TO USE IT:**
- Production critical systems without testing
- If you are not familiar with CheckMK
- Without disaster recovery plan
- Without the possibility of rapid intervention
- In environments with stringent SLAs

 **USEFUL RESOURCES:**
- [CheckMK Official Documentation](https://docs.checkmk.com/)
- [OMD Update Guide](https://docs.checkmk.com/latest/en/update.html)
- [CheckMK Backup/Restore](https://docs.checkmk.com/latest/en/backup.html)