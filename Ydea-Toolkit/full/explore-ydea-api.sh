#!/bin/bash
# explore-ydea-api.sh — Explore available Ydea API endpoints
# Use this script to find out what endpoints exist and how the API responds

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YDEA_TOOLKIT="${SCRIPT_DIR}/ydea-toolkit.sh"

# Load functions from ydea-toolkit
# shellcheck disable=SC1090
source "$YDEA_TOOLKIT"

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "   ESPLORAZIONE API YDEA"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Verify authentication
echo " Step 1: Autenticazione..."

set +e
ensure_token 2>&1
if [[ $? -ne 0 ]]; then
    echo "Authentication error"
    exit 1
fi
set -e

echo " Autenticato"
echo ""

# Load token
TOKEN=$(load_token)
BASE_URL="${YDEA_BASE_URL%/}"

echo " Base URL: $BASE_URL"
echo "Token: ${TOKEN:0:20}..."
echo ""

# Helper function for testing an endpoint
test_endpoint() {
  local method="$1"
  local endpoint="$2"
  local description="$3"
  
  echo "==========================================================="
  echo " Test: $description"
  echo "   $method $endpoint"
  echo ""
  
  local url="${BASE_URL}${endpoint}"
  local response
  local http_code
  
  set +e
  response=$(curl -s -w '\n%{http_code}' \
    -X "$method" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    --connect-timeout 10 \
    --max-time 30 \
    "$url" 2>&1)
  local curl_exit=$?
  set -e
  
  if [[ $curl_exit -ne 0 ]]; then
    echo "Curl error (exit: $curl_exit)"
    echo "$response"
    return 1
  fi
  
  http_code=$(echo "$response" | tail -1)
  response=$(echo "$response" | head -n -1)
  
  echo " HTTP Status: $http_code"
  
  if [[ "$http_code" == "200" || "$http_code" == "201" ]]; then
    echo "Success!"
    echo ""
    echo "Response (first 50 characters):"
    echo "$response" | head -c 500
    echo ""
    echo ""
    echo "Struttura JSON:"
    echo "$response" | jq -r 'keys' 2>/dev/null || echo "This is not valid JSON"
    
    # Se ha array 'objs', mostra quanti elementi
    local count
    count=$(echo "$response" | jq -r '.objs | length' 2>/dev/null || echo "")
    if [[ -n "$count" && "$count" != "null" ]]; then
      echo "Number of objects (.objs): $count"
      if [[ "$count" -gt 0 ]]; then
        echo ""
        echo "Esempio primo oggetto:"
        echo "$response" | jq -r '.objs[0]' 2>/dev/null | head -20
      fi
    fi
  else
    echo "  HTTP $http_code"
    echo "$response" | jq '.' 2>/dev/null || echo "$response"
  fi
  echo ""
}

# Test endpoint comuni
echo "════════════════════════════════════════════════════════════════"
echo "START ENDPOINT TEST"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Endpoint categorie - varianti comuni
test_endpoint "GET" "/categories" "Lista categorie (variant 1)"
test_endpoint "GET" "/category" "Lista categorie (variant 2)"
test_endpoint "GET" "/ticket/categories" "Categorie ticket (variant 3)"
test_endpoint "GET" "/api/categories" "Categorie con prefisso api"

# Endpoint SLA - varianti comuni
test_endpoint "GET" "/sla" "Lista SLA (variant 1)"
test_endpoint "GET" "/slas" "Lista SLA (variant 2)"
test_endpoint "GET" "/ticket/sla" "SLA ticket"

# Endpoint priorità
test_endpoint "GET" "/priorities" "Lista priorità (variant 1)"
test_endpoint "GET" "/priority" "Lista priorità (variant 2)"
test_endpoint "GET" "/ticket/priorities" "Priorità ticket"

# Ticket endpoint (for reference)
test_endpoint "GET" "/tickets?limit=1" "Lista ticket (per verifica)"

# Endpoint users (for reference)
test_endpoint "GET" "/users?limit=1" "Lista utenti (per verifica)"

# Endpoint generico info
test_endpoint "GET" "/" "Info API root"
test_endpoint "GET" "/info" "Info API"
test_endpoint "GET" "/api" "API info"

echo "════════════════════════════════════════════════════════════════"
echo "   ESPLORAZIONE COMPLETATA"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "Tip: Look in the outputs above the HTTP 200 to see"
echo "   quali endpoint funzionano e quale struttura hanno i dati."
echo ""
