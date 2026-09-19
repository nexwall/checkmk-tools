#!/bin/bash
/usr/bin/env bash
# test-ticket-creation.sh - Test ticket creation for each typeset -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "ƒº¬ Ydea Ticket Creation Test for CheckMK Monitoring"
echo "ÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöü"
echo "Test with CRITICAL and WARNING states to verify priority"
echo ""
# Test cases for each type (including WARNING)declare -A
TEST_CASES=(  ["NethVoice-CRIT"]="pbx.example.com|Asterisk Status|CRITICAL|SIP trunk offline"  ["NethSecurity-WARN"]="firewall.example.com|VPN Status|WARNING|VPN tunnel down"  ["NethService-CRIT"]="mail.example.com|SMTP|CRITICAL|Connection timeout"  ["Client-WARN"]="workstation-01|Disk Space|WARNING|Disk C: 90% full"  ["Server-CRIT"]="server-db01|MySQL Status|CRITICAL|Database connection failed"  ["Network-WARN"]="switch-core|Port Status|WARNING|Port 24 down"  ["Hypervisor-CRIT"]="proxmox01|VM Status|CRITICAL|VM web01 not responding"  ["Consulenza-WARN"]="support-request|Manual Check|WARNING|Richiesta assistenza")
echo "Do you want to take the test? (will create 8 test tickets)"read -p "Procedi? [y/N]: " -n 1 -r
echo ""if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Test annullato"
    exit 0
fi echo ""
echo "ƒÜÇ Creating test tickets..."
echo ""for tipologia in "${!TEST_CASES[@]}"; do  
IFS='|' read -r host service state output <<< "${TEST_CASES[$tipologia]}"    
echo "ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ"  
echo "­ƒôï Test: $tipologia"  
echo "Host: $host | Service: $service | State: $state"  
echo ""    "$SCRIPT_DIR/create-monitoring-ticket.sh" \    "$host" \    "$service" \    "$state" \    "$output" \    "192.168.1.100"    
echo ""  sleep 2  
# Pause between creations
done
echo "ÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöüÔöü"
echo "Ô£à Test completed!"
echo ""
echo "Check the tickets created on: https://my.ydea.cloud"
