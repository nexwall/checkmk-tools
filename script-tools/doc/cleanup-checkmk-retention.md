# Cleanup Retention CheckMK - Installation Guide
> **Category:** Operational

## Description

Automatic script for CheckMK data retention management:
- **180 days** for RRD files (P4P performance metrics)
- **180 days** for Nagios archives (with compression after 30 days)
- **30 days** for notification backup (with compression after 1 day)

## Installation

### 1. Copy the script to the CheckMK server

```bash
# On CheckMK server (as monitoring user)
cd /omd/sites/monitoring/local/bin
wget https://raw.githubusercontent.com/nethesis/checkmk-tools/main/script-tools/full/backup_restore/cleanup-checkmk-retention.sh
chmod +x cleanup-checkmk-retention.sh
```

### 2. Test in DRY-RUN mode (without modification)

```bash
# Check what would be deleted without changing anything
DRY_RUN=true ./cleanup-checkmk-retention.sh
```

### 3. Manual execution (first time)

```bash
# Perform real cleanup
./cleanup-checkmk-retention.sh
```

### 4. Automatic cron configuration

```bash
# Edit monitoring user crontab
crontab -e

# Add this line (running daily at 2:00 AM)
0 2 * * * /omd/sites/monitoring/local/bin/cleanup-checkmk-retention.sh >> /omd/sites/monitoring/var/log/cleanup-retention-cron.log 2>&1
```

## Custom Configuration

You can change parameters via environment variables:

```bash
# Change retention to 90 days for RRD
RETENTION_RRD=90 ./cleanup-checkmk-retention.sh

# Compress after 7 days instead of 30
COMPRESS_AFTER=7 RETENTION_NAGIOS=180 ./cleanup-checkmk-retention.sh

# Site other than "monitoring"
OMD_SITE=cmk ./cleanup-checkmk-retention.sh
```

## Output and Log

The script generates detailed logs in:
```
/omd/sites/monitoring/var/log/cleanup-retention.log
```

Example output:
```
[2026-01-22 16:30:00] [INFO] CLEANUP FILE RRD (retention: 180 days)
[2026-01-22 16:30:05] [OK] RRDs deleted: 245 files
[2026-01-22 16:30:05] [OK] Space freed: 156MB
[2026-01-22 16:30:10] [OK] Compressed files: 89
[2026-01-22 16:30:10] [OK] Space saved: 1.2GB
```

## Expected Results

**Before cleanup** (current state):
- Total: 8.4 GB
- RRD: 1.8GB
- Nagios: 4.6 GB
- Notify: 582 MB

**After cleanup** (estimate):
- Total: ~4.3-4.8 GB
- RRD: ~900 MB (files deleted >180 days)
- Nagios: ~1.4-1.8 GB (compressed 30-180 days, deleted >180 days)
- Notify: ~120 MB (compressed 1-30 days, deleted >30 days)

**Savings**: ~43-50% (3.6-4.1 GB freed)

## Important Notes

1. **Backup before use**: The first cleanup can delete a lot of data. Make a full backup first.

2. **Unrecoverable RRD files**: Deleted RRD files cannot be recovered. Historical metrics beyond 180 days will be permanently lost.

3. **Incremental compression**: Compression after 30 days reduces space but files remain accessible.

4. **Execution Frequency**: Recommended daily (at night) to avoid accumulation.

## Troubleshooting

### Script does not delete anything
```bash
# Check permissions
ls -la /omd/sites/monitoring/var/nagios
ls -la /omd/sites/monitoring/var/pnp4nagios

# Verify ownership
stat /omd/sites/monitoring/local/bin/cleanup-checkmk-retention.sh
```

### "Site not found" error
```bash
# Check site name
omd sites

# Use correct site
OMD_SITE=yoursite ./cleanup-checkmk-retention.sh
```

### Log is not created
```bash
# Check log folder exists
mkdir -p /omd/sites/monitoring/var/log
chmod 755 /omd/sites/monitoring/var/log
```

## Monitoring

Monitor disk space with:
```bash
# Current size
du -sh /omd/sites/monitoring/var/{nagios,pnp4nagios,notify-backup}

# Count RRD files
find /omd/sites/monitoring/var/pnp4nagios -name "*.rrd" | wc -l

# Older files
find /omd/sites/monitoring/var/nagios -type f -printf "%T@ %p\n" | sort -n | head -5
```

## Script update

```bash
cd /omd/sites/monitoring/local/bin
wget -O cleanup-checkmk-retention.sh https://raw.githubusercontent.com/nethesis/checkmk-tools/main/script-tools/full/backup_restore/cleanup-checkmk-retention.sh
chmod +x cleanup-checkmk-retention.sh
```