#!/bin/bash
/usr/bin/env bashset -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"source "$SCRIPT_DIR/ydea-toolkit.sh"
SEARCH="${1:-OFFERTA PRO FORMA}"
echo "ƒöì Personal data search: $SEARCH"ensure_token
TOKEN=$(load_token)
echo ""
echo "=== List of personal details and search ==="curl -s "https://my.ydea.cloud/app_api_v2/anagrafica" \  -H "Authorization: Bearer $TOKEN" \  -H "Accept: application/json" | jq -r '.[] | "\(.id) - \(.ragioneSociale)"' | grep -i "${SEARCH}"
echo ""
echo "=== Dettagli completi ==="
ANAGRAFICA_ID=$(curl -s "https://my.ydea.cloud/app_api_v2/anagrafica" \  -H "Authorization: Bearer $TOKEN" \  -H "Accept: application/json" | jq -r ".[] | select(.ragioneSociale | test(\"${SEARCH}\"; \"i\")) | .id" | head -1)
if [[ -n "$ANAGRAFICA_ID" && "$ANAGRAFICA_ID" != "null" ]]; then
    echo "Found ID: $ANAGRAFICA_ID"  curl -s "https://my.ydea.cloud/app_api_v2/anagrafica/${ANAGRAFICA_ID}" \    -H "Authorization: Bearer $TOKEN" \    -H "Accept: application/json" | jq '.'else  
echo "Personal data not found"
fi 