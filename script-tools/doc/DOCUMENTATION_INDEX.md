# Documentation Index - script-tools/doc
> **Category:** Operational

Last update: 2026-02-18

## Objective

This page is the quick map to remember **what does what** without having to open 20 files.

## Start Here (recommended order)

1. `README.md`  
   Quick overview of how to find your way around the doc folder.

2. `CONVERSION-STATUS-SCRIPT-TOOLS.md`  
   Real state of Bash → Python conversion in `script-tools/full`.

3. Task-specific README (`README-*.md`)  
   Operational guides for deploy/install/upgrade.

## Main operational documents

- `README-Install-Agent-Interactive.md`  
  Interactive installation of CheckMK agent (Linux).

- `README-Install-Agent-Interactive-Windows.md`  
  Interactive installation of CheckMK agent on Windows.

- `README-Setup-Auto-Upgrade-CheckMK.md`  
  CheckMK automatic updates/upgrade setup.

- `README-Setup-Auto-Updates.md`  
  Automatic update and scheduling configurations.

- `README-Smart-Deploy.md` / `README-Smart-Deploy-Enhanced.md`  
  Smart script deployment and advanced variants.

- `cleanup-checkmk-retention.md`  
  CheckMK data retention and cleanup.

- `DISTRIBUTED-MONITORING-GUIDE.md`  
  Setup distributed monitoring.

## Technical support documents (valid but specialized)

- `install-checkmk-agent-debtools-frp-nsec8c-rocksolid.md`
- `ROCKSOLID_INSTALLATION.md`
- `checkmk-host-labels-config.md`
- `ENHANCED-NOTIFICATIONS-DEPLOYMENT.md`
- `INTEGRATION-CHECKMK-YDEA-SUMMARY.md`

## Historical documents/session (consult only if necessary)

These files are useful as a history, but are not the operational starting point:

- `CURRENT_STATUS.md`
- `PROJECT_STATUS.md`
- `COMPLETION_SUMMARY.md`
- `SESSION_COMPLETE.md`
- `CODE_COMPARISON.md`
- `FRPC_FIX_CHANGELOG.md`
- `FRPC_FIX_SUMMARY.md`
- `FRPC_SERVICE_STARTUP_FIX.md`
- `SERVICE_CREATION_FIX.md`

## Practical rule to avoid getting confused

- First search in `README-*` or the how-to guides.
- If you can't find it immediately, use this index to understand category and priority.
- Keep history files mentally separated: useful for context, not for current runbook.