# script-tools/full - Speaking structure

This folder is organized for **functional use**.

## Subfolders

- `backup_restore/`  
  Backup, restore, backup compression, retention, rclone space.

- `deploy/`  
  Deploy script/check, smart deployment, deployment monitoring.

- `installation/`  
  Installation of agents, FRPC, related components and setups.

- `upgrade_maintenance/`  
  Upgrade, pre-upgrade, rocksolid startup check, optimizations and maintenance.

- `sync_update/`  
  Auto-git-sync, update script, update crontab, sync from repo.

- `monitoring_diagnostics/`  
  Tuning, diagnostics, debug monitor, distributed monitoring setup.

- `network_scan/`  
  nmap scan script.

- `wrappers_templates/`  
  Example template and wrapper.

- `misc/`  
  Scripts not yet reclassified to a more specific domain.

## Operational rule

- The scripts are in their respective category subfolders.
- There must be no `.sh`/`.py` scripts in root `script-tools/full`.
- No legacy wrappers: the paths to use are those of the category folders.