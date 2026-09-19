#!/bin/bash
/usr/bin/env bashset -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"source "$SCRIPT_DIR/ydea-toolkit.sh"
TICKET_ID="${1:-1528466}"
echo "­ƒôï Recupero dettagli completi ticket 
#${TICKET_ID}..."ensure_token
TOKEN=$(load_token)
echo ""
echo "=== GET /ticket/${TICKET_ID} ==="curl -s "https://my.ydea.cloud/app_api_v2/ticket/${TICKET_ID}" \  -H "Authorization: Bearer $TOKEN" \  -H "Accept: application/json" | jq '.'
echo ""
echo "=== I'm looking for fields with 'sla' in the name ==="curl -s "https://my.ydea.cloud/app_api_v2/ticket/${TICKET_ID}" \  -H "Authorization: Bearer $TOKEN" \  -H "Accept: application/json" | jq 'to_entries | .[] | select(.key | test("sla|SLA|Sla"))'
