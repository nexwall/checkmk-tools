#!/bin/bash
/usr/bin/env bashset -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"source "$SCRIPT_DIR/ydea-toolkit.sh"
TICKET_ID="${1:-1530128}"
echo "­ƒôï Recupero TUTTI i campi del ticket 
#${TICKET_ID}..."ensure_token
TOKEN=$(load_token)
RESPONSE=$(curl -s "https://my.ydea.cloud/app_api_v2/tickets?limit=100" \  -H "Authorization: Bearer $TOKEN" \  -H "Accept: application/json")
echo ""
echo "­ƒöì Ticket 
#${TICKET_ID} (ALL FIELDS):"
echo "$RESPONSE" | jq ".objs[] | select(.id == ${TICKET_ID})"
echo ""
echo "­ƒöì Confronto con ticket 
#1528466 (with manual SLA):"
echo "$RESPONSE" | jq ".objs[] | select(.id == 1528466)" 2>/dev/null || 
echo "Ticket not on this page"
