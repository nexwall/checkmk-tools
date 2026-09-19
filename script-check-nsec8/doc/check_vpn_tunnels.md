# check_vpn_tunnels.sh

## Description
Monitor the status of VPN tunnels on NSecFirewall8, supporting OpenVPN, WireGuard and IPSec (strongSwan).

## Features
- **OpenVPN**: Read status file in `/var/run/openvpn/*.status`, count connected clients
- **WireGuard**: Use `wg show` to check recent handshakes (< 3 minutes)
- **IPSec**: Use `ipsec status` to count ESTABLISHED tunnels
- Distinguishes total tunnels from active tunnels

## States
- **OK (0)**: All VPN tunnels are active or no VPN configured
- **WARNING (1)**: Some tunnels are down
- **CRITICAL (2)**: All tunnels are down

## Output CheckMK
```
0 VPN_Tunnels active=2;0;0;0;2 Total:2 Active:2 - OK - All VPN active | total=2 active=2 inactive=0
0 VPN_Details - OpenVPN_server: 3 clients, WireGuard_wg0: 2/5 peers active
```

## Performance Data
- `total`: Total number of tunnels configured
- `active`: Number of active/connected tunnels
- `inactive`: Number of inactive/disconnected tunnels

## OpenVPN requirements
- File status in `/var/run/openvpn/`
- OpenVPN status format with `CLIENT_LIST`

## WireGuard requirements
- `wg` command available
- WireGuard interfaces configured

## IPSec requirements
- strongSwan installed
- `ipsec status` command available

## Installation
```bash
cp check_vpn_tunnels.sh /usr/lib/check_mk_agent/local/rcheck_vpn_tunnels.sh
chmod +x /usr/lib/check_mk_agent/local/rcheck_vpn_tunnels.sh
```

## Manual testing
```bash
bash /opt/checkmk-tools/script-check-nsec8/full/check_vpn_tunnels.sh
```

## Notes
- WireGuard: peer considered active if handshake < 180 seconds
- OpenVPN: server considered active if it has at least 1 client connected
- IPSec: only ESTABLISHED tunnels are counted as active
- If no VPN configured, status is OK (normal for firewalls without VPN)