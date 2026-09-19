#!/bin/bash
/usr/bin/env bashset -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"source "$SCRIPT_DIR/ydea-toolkit.sh"ensure_token
TOKEN=$(load_token)
echo "ƒº¬ Test ticket creation with direct curl"
echo "Token: ${TOKEN:0:20}..."
echo ""
echo "=== Test 1: sla_id ==="curl -X POST "https://my.ydea.cloud/app_api_v2/ticket" \  -H "Authorization: Bearer $TOKEN" \  -H "Content-Type: application/json" \  -d '{    "titolo": "TEST SLA 1",    "descrizione": "Test sla_id",    "anagrafica_id": 2339268,    "priorita_id": 30,    "fonte": "Partner portal",    "tipo": "Server",    "sla_id": "Premium_Mon"  }' | jq '.'
echo ""
echo "=== Test 2: nomeSla ==="curl -X POST "https://my.ydea.cloud/app_api_v2/ticket" \  -H "Authorization: Bearer $TOKEN" \  -H "Content-Type: application/json" \  -d '{    "titolo": "TEST SLA 2",    "descrizione": "Test nomeSla",    "anagrafica_id": 2339268,    "priorita_id": 30,    "fonte": "Partner portal",    "tipo": "Server",    "nomeSla": "Premium_Mon"  }' | jq '.'
echo ""
echo "=== Test 3: nome_sla ==="curl -X POST "https://my.ydea.cloud/app_api_v2/ticket" \  -H "Authorization: Bearer $TOKEN" \  -H "Content-Type: application/json" \  -d '{    "titolo": "TEST SLA 3",    "descrizione": "Test nome_sla",    "anagrafica_id": 2339268,    "priorita_id": 30,    "fonte": "Partner portal",    "tipo": "Server",    "nome_sla": "Premium_Mon"  }' | jq '.'
