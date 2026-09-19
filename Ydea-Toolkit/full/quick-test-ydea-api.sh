#!/bin/bash
# quick-test-ydea-api.sh — Ydea API connection quick test
# Verify that your credentials work before running full discovery

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YDEA_TOOLKIT="${SCRIPT_DIR}/ydea-toolkit.sh"

# Load functions from ydea-toolkit
# shellcheck disable=SC1090
source "$YDEA_TOOLKIT"

echo ""
echo "Ydea API Connection Test"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Test 1: Check environment variables
echo "Test 1: Check configuration..."

if [[ -z "${YDEA_ID:-}" || "${YDEA_ID}" == "ID" ]]; then
  echo "YDEA_ID not configured correctly"
  echo "Edit the .env file and set YDEA_ID"
  exit 1
fi

if [[ -z "${YDEA_API_KEY:-}" || "${YDEA_API_KEY}" == "TOKEN" ]]; then
  echo "YDEA_API_KEY not configured correctly"
  echo "Edit the .env file and set YDEA_API_KEY"
  exit 1
fi

echo " Variabili configurate:"
echo "   YDEA_ID: ${YDEA_ID}"
echo "   YDEA_API_KEY: ${YDEA_API_KEY:0:10}..."
echo ""

# Test 2: Login
echo " Test 2: Autenticazione..."

if ! ensure_token 2>&1; then
  echo "Authentication failed"
  echo "Verify that YDEA_ID and YDEA_API_KEY are correct"
  exit 1
fi

echo "Authentication successful"
echo ""

# Test 3: Test chiamata API categorie
echo " Test 3: Test chiamata API categorie..."

set +e  # Disabilita exit on error temporaneamente
categories_data=$(ydea_api GET "/categories" 2>&1)
exit_code=$?
set -e  # Riabilita exit on error

if [[ $exit_code -ne 0 ]]; then
  echo "Error in category API call (exit code: $exit_code)"
  echo ""
  echo "Response/Error:"
  echo "$categories_data"
  echo ""
  echo "Possibili cause:"
  echo "- Endpoint /categories does not exist or is not accessible"
  echo "- Connection problem or timeout"
  echo "- Expired or invalid token"
  exit 1
fi

# Check if the response is valid JSON
if ! echo "$categories_data" | jq empty 2>/dev/null; then
  echo "Response is not valid JSON"
  echo ""
  echo "Response received:"
  echo "$categories_data" | head -30
  exit 1
fi

# Check if there is an error in the answer
if echo "$categories_data" | jq -e 'has("error")' >/dev/null 2>&1; then
  echo "Error in API response"
  echo "$categories_data" | jq '.'
  exit 1
fi

cat_count=$(echo "$categories_data" | jq -r '.objs | length' 2>/dev/null || echo "0")
echo " API categorie funzionante - $cat_count categorie trovate"
echo ""

# Test 4: Test chiamata API ticket
echo " Test 4: Test chiamata API tickets..."
tickets_data=$(ydea_api GET "/tickets?limit=1" 2>&1)

if [[ $? -ne 0 ]] || echo "$tickets_data" | jq -e '.error' >/dev/null 2>&1; then
  echo "Error in tickets API call"
  echo "API Response:"
  echo "$tickets_data" | head -20
  exit 1
fi

echo " API tickets funzionante"
echo ""

# Test 5: Test chiamata API users
echo " Test 5: Test chiamata API users..."
users_data=$(ydea_api GET "/users?limit=1" 2>&1)

if [[ $? -ne 0 ]] || echo "$users_data" | jq -e '.error' >/dev/null 2>&1; then
  echo "Error calling API users"
  echo "API Response:"
  echo "$users_data" | head -20
  exit 1
fi

echo " API users funzionante"
echo ""

# Riepilogo
echo "════════════════════════════════════════════════════════════════"
echo "All tests passed!"
echo ""
