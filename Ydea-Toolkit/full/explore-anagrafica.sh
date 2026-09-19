#!/bin/bash
# explore-anagrafica.sh - Explore the registry data to find the ALS

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ydea-toolkit.sh"

ANAGRAFICA_ID="${1:-2339268}"  # Default: AZIENDA MONITORATA test

echo " Esplorazione anagrafica ID: $ANAGRAFICA_ID..."
echo ""

ensure_token
TOKEN="$(load_token)"

# Test various registry endpoints
declare -a ENDPOINTS=(
  "/anagrafica/$ANAGRAFICA_ID"
  "/anagrafiche/$ANAGRAFICA_ID"
  "/clienti/$ANAGRAFICA_ID"
  "/cliente/$ANAGRAFICA_ID"
  "/aziende/$ANAGRAFICA_ID"
  "/azienda/$ANAGRAFICA_ID"
  "/anagrafiche?id=$ANAGRAFICA_ID"
  "/sla?anagrafica_id=$ANAGRAFICA_ID"
  "/contracts?anagrafica_id=$ANAGRAFICA_ID"
  "/contratti?anagrafica_id=$ANAGRAFICA_ID"
)

echo "Attempt to recover personal data..."
echo ""

for ENDPOINT in "${ENDPOINTS[@]}"; do
  echo -n "   GET $ENDPOINT ... "
  
  RESPONSE=$(curl -s -w '\n%{http_code}' \
    -H "Accept: application/json" \
    -H "Authorization: Bearer ${TOKEN}" \
    "${YDEA_BASE_URL}${ENDPOINT}" 2>&1 || echo -e "\n000")
  
  HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
  
  if [[ "$HTTP_CODE" == "200" ]]; then
    echo "HTTP $HTTP_CODE - FOUND!"
    
    HTTP_BODY=$(echo "$RESPONSE" | sed '$d')
    
    echo ""
    echo "════════════════════════════════════════════════════════════════════════"
    echo "REPLY FROM: $ENDPOINT"
    echo "════════════════════════════════════════════════════════════════════════"
    echo ""
    
    echo "$HTTP_BODY" | jq '.'
    
    echo ""
    
    # Cerca campi contenenti "sla", "premium", "mon"
    echo " Campi contenenti 'SLA', 'Premium' o 'Mon':"
    echo "$HTTP_BODY" | jq 'walk(if type == "object" then with_entries(select(.key | test("sla|premium|mon|contract|contratt"; "i"))) else . end)' 2>/dev/null || echo "None found"
    
    echo ""
    
    # Save the result
    echo "$HTTP_BODY" | jq '.' > "/tmp/anagrafica-${ANAGRAFICA_ID}.json"
    echo "Saved in: /tmp/anagrafica-${ANAGRAFICA_ID}.json"
    echo ""
  elif [[ "$HTTP_CODE" == "404" ]]; then
    echo "HTTP $HTTP_CODE - Not found"
  elif [[ "$HTTP_CODE" == "401" ]]; then
    echo "HTTP $HTTP_CODE - Unauthorized"
  elif [[ "$HTTP_CODE" == "403" ]]; then
    echo " HTTP $HTTP_CODE - Accesso negato"
  else
    echo " HTTP $HTTP_CODE"
  fi
done

echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "SEARCH TICKETS WITH THIS PERSONAL GRAPHIC"
echo "════════════════════════════════════════════════════════════════════════"
echo ""

echo "I am looking for tickets with anagrafica_id=$ANAGRAFICA_ID to see all the available fields..."
echo ""

RESPONSE=$(curl -s \
  -H "Accept: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  "${YDEA_BASE_URL}/tickets?limit=50")

MATCHING_TICKETS=$(echo "$RESPONSE" | jq --arg aid "$ANAGRAFICA_ID" '[.objs[] | select(.anagrafica_id == ($aid|tonumber))]')
COUNT=$(echo "$MATCHING_TICKETS" | jq 'length')

echo "$COUNT ticket found with this registry"

if [[ "$COUNT" -gt 0 ]]; then
    echo ""
    echo "First ticket found (for field analysis):"
    echo "$MATCHING_TICKETS" | jq '.[0]'
    echo ""
    
    echo "All the keys available in the tickets of this registry:"
    echo "$MATCHING_TICKETS" | jq '[.[].keys[]] | unique | sort[]'
    echo ""
    
    # Cerca campi custom o sla
    echo "customAttributes values ​​in the tickets of this registry:"
    echo "$MATCHING_TICKETS" | jq '[.[].customAttributes // {}] | unique'
fi

echo ""
echo " Esplorazione completata!"
