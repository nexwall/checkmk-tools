# Nexwall Checkmk checks

Checkmk local checks for Nexwall Firewall, in `script-check-nsec8/full/`:

`check_dhcp_leases`, `check_dns_resolution`, `check_firewall_connections`, `check_firewall_rules`,
`check_firewall_traffic`, `check_ovpn_host2net`, `check_root_access`, `check_vpn_tunnels`, `check_wan_status`,
`check_wan_throughput`.

They are packaged as `ns-checkmk-utils` and installed under `/usr/lib/check_mk_agent/local/`.

## License

GPL-3.0, see `LICENSE`. Attribution and the list of changes are in `NOTICE.md`.
