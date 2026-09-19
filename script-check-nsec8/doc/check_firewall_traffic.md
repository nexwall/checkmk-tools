# check_firewall_traffic.py

## Description
Monitor network traffic (RX/TX bytes, packets, errors) on the WAN and LAN interfaces of a NethSecurity 8.8 firewall.

## Features
- Detects WAN/LAN devices via firewall zone membership (`nethsec.utils.get_all_wan_devices`/`get_all_lan_devices`), not by interface name pattern - correctly follows whatever devices are actually assigned to those zones and excludes unrelated interfaces (bridge member NICs already reflected in their bridge's counters, DPI/redirect virtual devices, etc.)
- Reads bytes, packets and errors for RX and TX from `/proc/net/dev`
- Generates a WARNING alarm if RX or TX errors exceed 100

## States
- **OK (0)**: RX/TX errors <= 100
- **WARNING (1)**: RX/TX errors > 100

## Output CheckMK
```
0 eth1.Traffic - RX: 123456789 bytes, TX: 987654321 bytes - OK | rx_bytes=123456789 tx_bytes=987654321 rx_packets=12345 tx_packets=98765 rx_errors=0 tx_errors=0
0 br-lan.Traffic - RX: 987654321 bytes, TX: 123456789 bytes - OK | rx_bytes=987654321 tx_bytes=123456789 rx_packets=98765 tx_packets=12345 rx_errors=0 tx_errors=0
```

## Performance Data
- `rx_bytes`: Bytes received (cumulative counter)
- `tx_bytes`: Bytes transmitted (cumulative counter)
- `rx_packets`: Received packets
- `tx_packets`: Packets transmitted
- `rx_errors`: Receiving errors
- `tx_errors`: Transmission errors

## Requirements
- Python 3 with `euci`/`nethsec` (`python3-nethsec`) for WAN/LAN device discovery
- `/proc/net/dev` accessible

## Installation
```bash
cp check_firewall_traffic.py /usr/lib/check_mk_agent/local/check_firewall_traffic
chmod +x /usr/lib/check_mk_agent/local/check_firewall_traffic
```

## Manual testing
```bash
python3 /opt/checkmk-tools/script-check-nsec8/full/check_firewall_traffic.py
```

## Notes
- The counters are cumulative since the last boot
- CheckMK automatically calculates rates (bytes/sec, packets/sec)
- Perfect for creating bandwidth graphs over time
- High errors can indicate:
  - Hardware problems (cable, network card)
  - Collisions on half-duplex
  - MTU mismatch
- A device with no zone assignment (or entirely absent, e.g. an unplugged WAN NIC) is silently skipped, not reported as an error - only assigned WAN/LAN devices that actually exist are checked
