# CheckMK Agent - NethSecurity 8 Installation Guide

> **Category:** Operational

## Installation Procedure

**ONLY these 4 commands must be used to install CheckMK agent on NethSecurity 8:**

```bash
wget https://updates.nethsecurity.nethserver.org/checkmk_agent/8.7.2-checkmk_agent+a4de81a27/packages/x86_64/nethsecurity/ns-checkmk-utils_0.0.2-r1_all.ipk
wget https://nethsecurity.ams3.digitaloceanspaces.com/checkmk_agent/8.7.2-checkmk_agent+a4de81a27/packages/x86_64/nethsecurity/checkmk-agent_2.4.0p24-r1_all.ipk
opkg install checkmk-agent_2.4.0p24-r1_all.ipk
opkg install ns-checkmk-utils_0.0.2-r1_all.ipk
```

## What gets installed

- `checkmk-agent` installs: `/usr/sbin/check_mk_agent` + `/etc/init.d/check_mk_agent`
- `ns-checkmk-utils` installs: 13 local checks in `/usr/lib/check_mk_agent/local/`

## FRPC (optional, manual)

FRPC is NOT installed by the packages above. Install it separately and manually add entries to `/etc/sysupgrade.conf`.

## What NOT to use

- `install-checkmk-agent-persistent-nsec8.sh` — obsolete, creates unwanted artifacts
- `install-agent-nsec8.py` — obsolete
- `setup-persistent-nsec8.py` — obsolete, creates rc.local entries and cron jobs that break the system
- `rocksolid-startup-check.sh` — obsolete

## Verified on

NethSecurity 8.7.2 (x86_64), CheckMK Agent 2.4.0p24.