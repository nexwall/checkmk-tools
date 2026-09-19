# check_wan_status.py

## Description
Monitoring script for CheckMK that checks the status of WAN interfaces on NethSecurity 8.8 (OpenWrt).

## Features
- Automatically detects all WAN (`role=red`) interfaces via the `nethsec` library (`nethsec.inventory.get_networks`)
- Reports each WAN by its UCI interface name (e.g. `tim_fibra`, `vodafone_adsl` - commonly the ISP/operator name, not literally "wan"), not by the raw device name (`eth1`) - falls back to the device name only if no matching UCI section is found
- Interface up/down state and the configured gateway come from `ubus call network.interface.<name> status` (the same API NethSecurity's own UI uses) - not from manually reading `/sys/class/net/<iface>/operstate` or decoding `/proc/net/route`
- Real internet reachability is tested per-WAN with `ping -I <device>` (bound to that WAN's own egress device, not the default route) against the same host list NethSecurity's dashboard "Internet" indicator uses (`packages/ns-api/files/ns.dashboard`: `check_internet()` - `8.8.8.8`, `one.one.one.one`, `www.nethserver.org`, `gstatic.com`; "reachable" if at least half answer). No API/library can answer this question, since it's inherently something that has to be tested at the moment it's asked - a plain TCP probe to the gateway (the previous approach) only proves the first hop answers on some port, which is neither necessary (most gateways don't run services) nor sufficient (e.g. a public-IP-pool gateway responding says nothing about whether that IP block actually routes to the internet) for confirming the WAN has working internet
- Falls back to `/proc/net/route` default-route detection (interfaces) and `/sys/class/net/<iface>/operstate` (up/down) if `ubus`/the `nethsec` library is unavailable

## States
Two services per WAN, each name doing only what it says - not one compound service:

- **`WAN.Interface.<label>`** - a single, simple fact, from `ubus`'s own `up` field:
  - **OK (0)**: interface is up
  - **CRITICAL (2)**: interface is down
- **`WAN.Status.<label>`** - the overall verdict for this WAN link, interface state plus internet reachability:
  - **OK (0)**: interface up and internet reachable through it
  - **WARNING (1)**: interface up but no internet reachable through it - likely an upstream/ISP problem, since the interface itself is fine
  - **CRITICAL (2)**: interface down - a local problem (cable, config, hardware)

## Output CheckMK
### WAN.Interface.\<label\> / WAN.Status.\<label\>
```
0 WAN.Interface.tim_fibra - UP
0 WAN.Status.tim_fibra - tim_fibra: UP
0 WAN.Interface.vodafone_adsl - UP
0 WAN.Status.vodafone_adsl - vodafone_adsl: UP
```

Degraded example (interface up, no internet through it):
```
1 WAN.Status.vodafone_adsl - vodafone_adsl: UP - no internet reachability, likely an upstream/ISP issue (gateway 192.168.1.1 configured)
```

### WAN.Metrics
```
0 WAN.Metrics total=2|up=2|down=0|degraded=0 Total=2 Up=2 Down=0 Degraded=0
```

## Performance Data
- `total`: Total number of WAN interfaces
- `up`: Number of interfaces that are up (regardless of internet reachability)
- `down`: Number of interfaces that are down
- `degraded`: Subset of `up` with no confirmed internet reachability through that specific device

## Requirements
- Python 3 with `euci`/`nethsec` (`python3-nethsec`) for interface discovery - falls back to `/proc/net/route` if unavailable
- `ubus` for interface up/down state and gateway - falls back to `/sys/class/net`/`/proc/net/route` if unavailable
- `ping` supporting `-I <device>` (verified against the iputils-style `ping` shipped on NethSecurity 8.8, not the limited BusyBox applet)

## Installation
```bash
cp check_wan_status.py /usr/lib/check_mk_agent/local/check_wan_status
chmod +x /usr/lib/check_mk_agent/local/check_wan_status
```

## Manual testing
```bash
python3 /opt/checkmk-tools/script-check-nsec8/full/check_wan_status.py
```

## Notes
- WAN interfaces are identified by `role=red` in `nethsec.inventory.get_networks()`, not by name pattern matching
- Displayed labels come from the UCI interface section name, so a WAN named after its ISP (`tim_fibra`, `vodafone_adsl`, etc.) shows up as such, not as an opaque `eth1`/`eth2`
- Service names are per-WAN (`WAN.Interface.<label>`, `WAN.Status.<label>`), not one combined service listing every WAN on one line - two WANs both reporting into a single `WAN.Status` service would collide as duplicate CheckMK items
- Multiple WAN interfaces are supported (failover, load balancing) - verified live with 2 simultaneous WANs, each with a custom operator name; also verified live that bringing one WAN down is correctly reported as CRITICAL on both its services while the other WAN stays OK, and that it recovers correctly once brought back up
