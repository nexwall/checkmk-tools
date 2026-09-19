# Setup Auto-Updates - Configure Automatic System Updates
> **Category:** Operational

## Description

Script to configure automatic Linux system updates via crontab. Allows you to schedule periodic execution of `apt update`, `apt full-upgrade` and `apt autoremove` with automatic logging.

## Components

### 1. Script Full (Interactive)
**Path:** `script-tools/full/upgrade_maintenance/setup-auto-updates.sh`

Full version with interactive interface that guides the user through configuration.

### 2. Remote Launcher
**Path:** `script-tools/remote/rsetup-auto-updates.sh`

Launcher that downloads and runs the complete script directly from GitHub.

## Features

- **Interactive menu** with predefined options
- **Automatic backup** of existing crontab
- **Full logging** of updates
- **Input validation** for security
- **Duplicate management** - removes existing entries
- **Colored output** for better readability
- Flexible **Time customization**

## Usage

### Local Execution (Interactive)

```bash
# From the script folder
cd /path/to/script-tools/full
sudo bash setup-auto-updates.sh
```

### Remote Execution

```bash
# Download and run in one command
bash <(curl -fsSL https://raw.githubusercontent.com/nethesis/checkmk-tools/main/script-tools/remote/rsetup-auto-updates.sh)
```

### Running from Cloned Repository

```bash
# If you cloned the repository
cd script-tools/remote
sudo bash rsetup-auto-updates.sh
```

## Scheduling Options

### 1. Daily
- **Frequency:** Every day
- **Default time:** 03:00
- **Chron:** `0 3 * * *`

### 2. Weekly
- **Frequency:** Every Sunday
- **Default time:** 03:00
- **Chron:** `0 3 * * 0`

### 3. Monthly
- **Frequency:** 1st day of the month
- **Default time:** 03:00
- **Chron:** `0 3 1 * *`

### 4. Customized
- **Frequency:** Manual entry
- **Format:** `minute hour day month weekday`
- **Example:** `30 2 * * 1` (every Monday at 02:30)

## Interactive Menu

```
╔════════════════════════════════ ════════════════════════════════╗
║ Configuring Automatic System Updates ║
╚════════════════════════════════ ════════════════════════════════╝

Command that will be executed:
sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove -y

Select the frequency of automatic updates:

  1) Daily - Every day at 03:00
  2) Weekly - Every Sunday at 03:00
  3) Monthly - The first day of the month at 03:00
  4) Custom - Specify custom time and frequency
  5) Cancel

Choice [1-5]:
```

## Examples of Custom Configurations

### Every 6 hours
```
Cron Schedule: 0 */6 * * *
```

### Every Monday at 02:30
```
Cron schedule: 30 2 * * 1
```

### Twice a day (02:00 and 14:00)
```
First entry: 0 2 * * *
Second entry: 0 14 * * *
```

### First and fifteenth of the month
```
Cron Schedule: 0 3 1.15 * *
```

## Log files

### Location
```
/var/log/auto-updates.log
```

### Log Format
```
[Sun Jan 12 03:00:01 2026] Starting system updates
Hit:1 http://archive.ubuntu.com/ubuntu jammy InRelease
...
[Sun Jan 12 03:05:23 2026] Updates completed successfully
```

### Real-Time Monitoring
```bash
# View the latest updates
tail -f /var/log/auto-updates.log

# See last 50 lines
tail -n 50 /var/log/auto-updates.log

# Look for errors
grep -i error /var/log/auto-updates.log
```

## Backup Crontab

### Backup location
```
/root/crontab_backups/
```

### File Format
```
crontab_backup_YYYYMMDD_HHMMSS.txt
```

### Restore Backup
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

### Remove All Entries
```bash
crontab -r
```

### Remove Auto-Updates Only
```bash
crontab -l | grep -v "apt update.*apt full-upgrade" | crontab -
```

## System Requirements

- **OS:** Linux (Debian/Ubuntu based)
- **Package Manager:** APT
- **Permissions:** Root (sudo)
- **Dependencies:** bash, cron, curl (for remote version)

## Check Installation

```bash
# Verify that cron is active
systemctl status cron

# Verify entry in crontab
crontab -l | grep "apt update"

# Manual testing of the command
sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove -y
```

## Troubleshooting

### Entry is not executed

1. Check that cron is active:
```bash
systemctl status cron
systemctl start cron
```

2. Check the system logs:
```bash
grep CRON /var/log/syslog
```

3. Check cron syntax:
```bash
crontab -l
```

### Insufficient permissions

```bash
# Make sure you run with sudo
sudo bash setup-auto-updates.sh
```

### Log file not accessible

```bash
# Check permissions
ls -l /var/log/auto-updates.log

# Recreate the file if necessary
sudo touch /var/log/auto-updates.log
sudo chmod 644 /var/log/auto-updates.log
```

### Remote script not downloadable

```bash
# Check connection
curl -I https://raw.githubusercontent.com/nethesis/checkmk-tools/main/script-tools/full/upgrade_maintenance/setup-auto-updates.sh

# Use local version
git clone https://github.com/nethesis/checkmk-tools.git
cd checkmk-tools/script-tools/full
sudo bash setup-auto-updates.sh
```

## Best Practices

### 1. Execution Time
- Choose low traffic times (e.g. 02:00-04:00)
- Avoid working hours for production servers
- Consider the server's time zone

### 2. Update Frequency
- **Production Server:** Weekly or monthly
- **Development Server:** Daily
- **Workstation:** Weekly

### 3. Tracking
- Check logs regularly
- Set alerts for critical errors
- Check available disk space

### 4. Backup
- Keep crontab backup
- Test restores periodically
- Document custom configurations

### 5. Security
- Review installed updates
- Monitor necessary reboots
- Schedule maintenance window for kernel updates

## Testing

### Immediate Manual Test
```bash
# Execute the command without waiting for the scheduler
sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove -y
```

### Dry-Run Test
```bash
# Simulate updates without installing them
sudo apt update
sudo apt list --upgradable
```

### Check Next Run
```bash
# Install at to see next run
# (cron doesn't have a native command for this)
```

## Uninstall

### Method 1: Manual Removal
```bash
crontab -e
# Delete the auto-updates line
```

### Method 2: Automatic Removal
```bash
crontab -l | grep -v "apt update.*apt full-upgrade" | grep -v "^# Auto-updates:" | crontab -
```

### Complete Cleaning
```bash
# Remove crontab entry
crontab -l | grep -v "apt update.*apt full-upgrade" | crontab -

# Remove log files
sudo rm /var/log/auto-updates.log

# (Optional) Remove backup
sudo rm -rf /root/crontab_backups/
```

## Support and Contributions

- **Repository:** https://github.com/nethesis/checkmk-tools
- **Issues:** https://github.com/nethesis/checkmk-tools/issues
- **Documentation:** `script-tools/doc/`

## Changelog

### Version 1.0 (2026-01-12)
- Initial release
- Interactive menu with 5 options
- Automatic backup crontab
- Complete logging
- Input validation
- Duplicate management
- Colorful output

## License

This script is part of the checkmk-tools project.

## Important Notes

 **ATTENTION:**
- Automatic updates may require reboots
- Always monitor logs after first runs
- Test on non-critical systems first
- Keep up-to-date system backups

 **TIP:**
- Configure email notifications for update results
- Consider using `unattended-upgrades` for more advanced configurations
- Integrate with existing monitoring systems (CheckMK, Nagios, etc.)