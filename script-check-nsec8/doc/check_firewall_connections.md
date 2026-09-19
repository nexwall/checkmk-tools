# check_firewall_connections.sh

## Description
Monitor the number of active connections in the connection tracking (conntrack) of the NSecFirewall8 firewall.

## Features
- Read connection counter from `/proc/sys/net/netfilter/nf_conntrack_count`
- Read maximum limit from `/proc/sys/net/netfilter/nf_conntrack_max`
- Calculate the percentage of use
- Configured thresholds: WARNING 80%, CRITICAL 90%

## States
- **OK (0)**: Usage < 80%
- **WARNING (1)**: Usage >= 80%
- **CRITICAL (2)**: Usage >= 90%

## Output CheckMK
```
0 Firewall_Connections connections=1234;52428;59032;0;65536 Active connections: 1234/65536 (1%) - Status: OK | current=1234 max=65536 percent=1
```

## Performance Data
- `connections`: Current number with threshold (warning;critical;min;max)
- `current`: Current connections
- `max`: Configured maximum limit
- `percent`: Percentage of use

## Requirements
- Linux kernel with netfilter/conntrack enabled
- Accessible `/proc/sys/net/netfilter/nf_conntrack_*` files

## Installation
```bash
cp check_firewall_connections.sh /usr/lib/check_mk_agent/local/rcheck_firewall_connections.sh
chmod +x /usr/lib/check_mk_agent/local/rcheck_firewall_connections.sh
```

## Manual testing
```bash
bash /opt/checkmk-tools/script-check-nsec8/full/check_firewall_connections.sh
```

## Notes
- The `nf_conntrack_max` limit can be increased if necessary:
  ```bash
  echo 131072 > /proc/sys/net/netfilter/nf_conntrack_max
  ```
- High connections may indicate:
  - Lots of legitimate traffic
  - DDoS attack
  - Connection leaks (timeouts too high)