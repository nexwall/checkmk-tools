# NethSecurity 8.8 CheckMK Local Checks

Production CheckMK local check set for NethSecurity 8.8 systems using APK.

This directory contains the production scripts intended for installation by the `ns-checkmk-utils` package.

## Production check set

The production set is composed of these 10 Python local checks:

| Script | Service | Purpose |
|---|---|---|
| `check_dhcp_leases.py` | `DHCP.Leases` | DHCP lease usage and pool status |
| `check_dns_resolution.py` | `DNS.Resolution` | DNS resolution checks |
| `check_firewall_connections.py` | `Firewall.Connections` | Active connection tracking usage |
| `check_firewall_rules.py` | `Firewall.Rules` | nftables/UCI firewall rule visibility |
| `check_firewall_traffic.py` | `<iface>.Traffic` | Interface RX/TX counters |
| `check_ovpn_host2net.py` | `OVPN.HostToNet` | OpenVPN host-to-net status |
| `check_root_access.py` | `Root.Access` | Active root sessions and recent root login signals |
| `check_vpn_tunnels.py` | `VPN.Tunnels` | VPN tunnel status |
| `check_wan_status.py` | `WAN.Interface.<label>` / `WAN.Status.<label>` / `WAN.Metrics` | WAN reachability |
| `check_wan_throughput.py` | `WAN.Throughput` | WAN throughput counters |

## Firewall rules check

`check_firewall_rules.py` supports two firewall data sources:

1. `nft` lookup from:
   - `/usr/sbin/nft`
   - `/usr/bin/nft`
   - `/sbin/nft`
   - `/bin/nft`
   - `PATH`
2. `nft -j list ruleset` (structured JSON) for a precise table/chain/rule count. No separate `fw4 print` fallback exists or is needed - `nft` alone already reflects the NethSecurity-managed ruleset.
3. UCI firewall fallback (via `nethsec.utils.get_all_by_type`) for named NethSecurity/OpenWrt sections such as:
   - `firewall.ns_lan=zone`
   - `firewall.ns_wan=zone`
   - `firewall.ns_lan2wan=forwarding`
   - `firewall.ns_allow_https=rule`

The check must not report that nftables is unavailable when `/usr/sbin/nft` exists and works.

## Root access check

`check_root_access.py` reviews root access using data available on NethSecurity/OpenWrt systems.

Expected behavior:

- Count active root sessions where reliable.
- Detect recent root login signals where logs are available.
- Detect failed login signals only when the source is available.
- Do not invent reliable failed-login counts when logs are unavailable.
- Use meaningful thresholds for active root sessions and failed login attempts.

Current thresholds:

| Signal | WARN | CRIT |
|---|---:|---:|
| Active root sessions | 5 | 10 |
| Failed root login attempts | 5 | 10 |

## Packaging requirements

`ns-checkmk-utils` must install only the 10 production `.py` checks listed above.

During package upgrade, the package must remove obsolete files left by previous versions (from before these scripts were removed from this directory entirely), including:

- old extensionless local checks replaced by `.py` scripts;
- `check_apk_packages` / `check_apk_packages.py`;
- `check_uptime` / `check_uptime.py` (removed - no longer part of the check set);
- `check_opkg_packages` / `check_opkg_packages.py`;
- `check_martian_packets` / `check_martian_packets.py`.

The package must avoid duplicate old/new CheckMK services in `/usr/lib/check_mk_agent/local/`.

## Validation notes

The current production script set was manually validated on a NethSecurity 8.8 test VM with CheckMK agent 2.5.0.

Important distinction:

- The corrected script set was validated manually after copying it to the VM.
- Package/feed installation from the PR was not validated successfully.
- Packaging still needs separate validation to confirm clean installation and upgrade behavior.

## Expected local section properties

A valid deployment should satisfy:

- no `APK.Packages` service;
- no `Firewall.Uptime` service;
- no `OPKG.Packages` service;
- no `Martian.Packets` service;
- `Firewall.Rules` detects firewall data when nft/UCI are available;
- no duplicate legacy and `.py` services;
- no Python traceback;
- no raw command failure output.
