# NSec8 APK Migration & DHCP Lease Persistence Guide

CheckMK local check migration from OPKG to APK on NethSecurity 8.8.

## Overview

NethSecurity 8.8 (based on OpenWRT 25.12) replaces the legacy OPKG package manager
with Alpine Package Keeper (APK). All CheckMK local checks that depend on package
management must be updated accordingly.

Additionally, NethSecurity 8.8 introduces persistent DHCP lease storage:
dnsmasq now writes leases to `/mnt/data/dnsmasq/dhcp.leases` when persistent storage
is mounted, falling back to `/tmp/dhcp.leases` when it is not.

### Target system

Test host: **NethSec88-test** (192.168.10.131)

```bash
$ cat /etc/os-release
NAME="NethSecurity"
VERSION="8.8.0-dev.42.20260618095133.67d7dc9"
ID="nethsecurity"
ID_LIKE="lede openwrt"
PRETTY_NAME="NethSecurity 8.8.0-dev.42.20260618095133.67d7dc9"
VERSION_ID="8.8.0-dev.42.20260618095133.67d7dc9"
OPENWRT_RELEASE="NethSecurity 8.8.0-dev.42.20260618095133.67d7dc9 v25.12.4"
OPENWRT_BOARD="x86/64"
OPENWRT_ARCH="x86_64"
```

---

## 1. New script: `check_apk_packages.py`

Replaces `check_opkg_packages.py` for APK-based systems.

### APK command mapping

| Operation | OPKG (legacy) | APK (new) |
|---|---|---|
| Installed packages | `opkg list-installed` | `apk info` |
| Available upgrades | `opkg list-upgradable` | `apk list --upgradable` |
| Repository index dir | `/var/opkg-lists` | `/var/cache/apk` (APKINDEX.*.tar.gz) |
| Log file | `/var/log/messages` | `/var/log/apk.log` (fallback `/var/log/messages`) |
| Index age calculation | `glob("*")` on lists dir | `rglob("*APKINDEX*")` on cache dir |

### Key implementation details

- **Upgradable count**: filters `apk list --upgradable` output, keeping only lines
  containing `{` and `}` (actual package lines), ignoring `WARNING:`, `ERROR:`,
  and blank lines.
- **Log parsing**: counts install events only when both `apk` and (`add` or `install`)
  appear on the same line; counts remove events when both `apk` and (`del` or `remove`)
  appear on the same line.
- **Overlay**: preserved identical thresholds (85% warning, 95% critical).
- **Service name**: changed from `OPKG.Packages` to `APK.Packages`.

### Verification on target host

```bash
# Copy and test
scp script-check-nsec8/full/check_apk_packages.py NethSec88-test:/tmp/
ssh NethSec88-test "PYTHONDONTWRITEBYTECODE=1 python3 -B /tmp/check_apk_packages.py"

# Expected output:
# 0 APK.Packages - OK - 593 packages installed
# | installed=593 updates_available=0 overlay_free_kb=177776 overlay_used_pct=22
#   last_update_age_days=0 recent_installs=1 recent_removes=0
```

---

## 2. Updated script: `check_dhcp_leases.py` (v2.1.0)

Adapted for NethSecurity 8.8 persistent lease file support
([GitHub issue #1694](https://github.com/NethServer/nethsecurity/issues/1694)).

### Lease file resolution logic

```python
def resolve_lease_file():
    """
    1. UCI:      uci get dhcp.ns_dnsmasq.leasefile  (authoritative)
    2. Storage:  /proc/mounts contains " /mnt/data " → /mnt/data/dnsmasq/dhcp.leases
    3. Fallback: /tmp/dhcp.leases
    4. None:     return (None, "no lease file found") → CheckMK UNKNOWN
    """
```

### State handling

| State | Behavior |
|---|---|
| `/mnt/data` mounted + persistent file exists | Read `/mnt/data/dnsmasq/dhcp.leases` |
| `/mnt/data` not mounted | Read `/tmp/dhcp.leases` |
| Both files exist | Use UCI-configured path (authoritative) |
| Configured file unreadable | Return `UNKNOWN` with diagnostic |
| Neither file exists | Return `UNKNOWN` |
| Empty active file | Treated as zero active leases |
| Storage mount/unmount transition | Follow active dnsmasq path |

### Mount detection

On NethSecurity 8.8, `mountpoint` command is not available. Use `/proc/mounts` instead:

```python
mounts = Path("/proc/mounts").read_text()
if " /mnt/data " in mounts:
    # persistent storage is mounted
```

### Output

Each pool output now includes the lease source:

```
0 DHCP.lan active=5;8;9;0;10 [192.168.1.0/24] Lease attivi: 5/10 (50%) - OK source=/tmp/dhcp.leases
```

### Evidence from NethSec88-test (8.8.0-dev)

```bash
# UCI config
$ uci show dhcp.ns_dnsmasq.leasefile
dhcp.ns_dnsmasq.leasefile='/tmp/dhcp.leases'

# Mount state
$ grep /mnt/data /proc/mounts
# (empty — not mounted)

# Lease file
$ ls -l /tmp/dhcp.leases
-rw-r--r-- 1 root root 0 Jun 18 16:06 /tmp/dhcp.leases

# mountpoint NOT available
$ which mountpoint
# (not found)

# mount available
$ which mount
/bin/mount
```

---

## 3. CheckMK Agent Installation on NethSecurity 8.8

NethSecurity 8.8 uses `apk` (APK) instead of `opkg`. The checkmk-agent package is
available from the NethSecurity APK repository as `checkmk-agent` (v2.5.0).

### Installation commands

```bash
# Update repository indexes
apk update

# Install CheckMK agent
apk add checkmk-agent

# Install NethSecurity-specific local checks
apk add ns-checkmk-utils
```

Expected output:

```
(1/1) Installing checkmk-agent (2.5.0-r1)
  Executing checkmk-agent-2.5.0-r1.post-install
OK: 239.8 MiB in 594 packages
```

### Agent verification

```bash
# Check installed agent version via APK
$ apk list checkmk-agent
checkmk-agent-2.5.0-r1 noarch {nspackages/checkmk-agent} (GPL-2.0-only)

$ apk list ns-checkmk-utils
ns-checkmk-utils-0.0.5-r1 noarch {nspackages/ns-checkmk-utils} (GPL-3.0-only)

# Check agent binary version
$ check_mk_agent --version
<<<check_mk>>>
Version: 2.5.0
AgentOS: openwrt

$ ls /usr/lib/check_mk_agent/local/
check_apk_packages      check_firewall_traffic  check_uptime
check_dhcp_leases       check_martian_packets   check_vpn_tunnels
check_dns_resolution    check_opkg_packages     check_wan_status
check_firewall_connections  check_ovpn_host2net     check_wan_throughput
check_firewall_rules    check_root_access
```

### Deploy updated scripts from repository

```bash
LOCAL="/usr/lib/check_mk_agent/local"
SRC="/path/to/checkmk-tools/script-check-nsec8/full"

for f in "$SRC"/*.py; do
  name=$(basename "$f" .py)
  scp "$f" "NethSec88-test:$LOCAL/$name"
done
```

Scripts are copied **without** the `.py` extension — CheckMK runs all executable
files in the local directory regardless of extension.

---

## 4. Full Agent Output on NethSec88-test

```
<<<check_mk>>>
Version: 2.5.0
AgentOS: openwrt
Hostname: NethSec88-test
[...]

<<<local>>>
0 APK.Packages - OK - 593 packages installed
1 DHCP.Leases - No active DHCP pool found
0 DNS.Resolution response_time=0ms;500;1000 Test: 3/3 OK, avg time: 0ms - OK
0 Firewall.Connections connections=135;50790;57139;0;63488 Active connections: 135/63488 (0%) - OK
0 Firewall.Rules - OK - 3 tabelle, 40 catene, ~57 regole
0 Martian.Packets count=0;10;50;0 unique_ips=0 - OK - No martian packets
2 OPKG.Packages - opkg not available
0 OVPN.HostToNet - OpenVPN not configured or not running
0 Root.Access sessions=1;2;3;0 logins=0 failed=0;5;10;0 - OK
0 Firewall.Uptime - Uptime: 0d 0h 45m, Load: 0.00 0.00 0.00 (1 CPU) - OK
0 VPN.Tunnels active=0;0;0;0;0 Total:0 Active:0 - No VPN configured
0 WAN.Status status=OK lan=OK - lan: UP (gateway 192.168.10.250 reachable)
0 WAN.Metrics - Total=1 Up=1 Down=0 Degraded=0
```

---

## 5. Host Reference

| Host | IP | OS | Agent | Notes |
|---|---|---|---|---|
| `NethSec88-test` | 192.168.10.131 | NethSecurity 8.8.0-dev (v25.12.4) | checkmk-agent 2.5.0-r1 | APK-based, no /mnt/data |
| `nsec8-stable` | 10.155.100.100 | NethSecurity 8 | checkmk-agent 2.4.0p24 | OPKG-based (legacy) |

---

## 6. Files changed in repository (`script-check-nsec8/full/`)

| File | Action | Version | Description |
|---|---|---|---|
| `check_apk_packages.py` | **Created** | v1.0.0 | APK package check (replaces OPKG) |
| `check_dhcp_leases.py` | **Modified** | v2.0.4 → v2.1.0 | Persistent lease file support |
| `.gitignore` | **Created** | — | Python cache artifact ignore |
| `check_opkg_packages.py` | **Unchanged** | v2.0.4 | Kept for legacy OPKG systems |

---

## 7. Git alignment

```bash
# Commit
git commit -m "feat(misc): python-cache-cleanup v1.0.0, check_apk_packages, check_dhcp_leases v2.1.0, docs"

# Push to origin
git push origin main

# Tag
git tag v0.0.16
git push origin v0.0.16

# Release
gh release create v0.0.16 \
  --title "v0.0.16 - python-cache-cleanup, APK migration, DHCP lease persistence" \
  --notes 'Added:
• script-tools/full/misc/python-cache-cleanup.py v1.0.0
• script-check-nsec8/full/check_apk_packages.py v1.0.0
• script-check-nsec8/full/.gitignore
Changed:
• script-check-nsec8/full/check_dhcp_leases.py v2.1.0'
```

---

## 8. Safety confirmation

- ✅ No staging, commit, tag, push, release to `upstream` (nethesis)
- ✅ Only `origin` (Coverup20 fork) used
- ✅ Original `check_opkg_packages.py` left intact
- ✅ All scripts tested on target host before commit
- ✅ No bytecode created (`PYTHONDONTWRITEBYTECODE=1 python3 -B`)
- ✅ Temporary test files removed from `/tmp/` on remote host

---

*Generated: 2026-06-18 — Session covering Python cache cleanup, APK migration,
DHCP lease persistence, agent installation, and script deployment on NethSec88-test.*
