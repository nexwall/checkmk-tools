#!/bin/bash
# analyze-custom-attributes.sh - Analyze the customAttributes of many tickets

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ydea-toolkit.sh"

PAGES="${1:-20}"  # Numero di pagine da analizzare (default: 20 = 2000 ticket)

echo "Analyzing customAttributes on $PAGES ticket pages..."
echo ""

ensure_token
TOKEN="$(load_token)"

# Temporary file to collect all customAttributes
TEMP_FILE="/tmp/all-custom-attributes.json"
echo "[]" > "$TEMP_FILE"

echo "Data collection in progress..."

for PAGE in $(seq 1 $PAGES); do
  echo -n "   Pagina $PAGE/$PAGES... "
  
  RESPONSE=$(curl -s -w '\n%{http_code}' \
    -H "Accept: application/json" \
    -H "Authorization: Bearer ${TOKEN}" \
    "${YDEA_BASE_URL}/tickets?limit=100&page=${PAGE}")
  
  HTTP_BODY="$(echo "$RESPONSE" | sed '$d')"
  HTTP_CODE="$(echo "$RESPONSE" | tail -n1)"
  
  if [[ "$HTTP_CODE" != "200" ]]; then
    echo "HTTP Error $HTTP_CODE"
    break
  fi
  
  COUNT=$(echo "$HTTP_BODY" | jq -r '.objs | length')
  
  if [[ "$COUNT" -eq 0 ]]; then
    echo "No tickets, the end"
    break
  fi
  
  echo "$COUNT ticket"
  
  # Extract customAttributes with ticket ID
  echo "$HTTP_BODY" | jq '[.objs[] | select(.customAttributes != null) | {id, codice, customAttributes}]' >> "$TEMP_FILE.part"
done

echo ""
echo " Elaborazione dati..."

# Combine all results
jq -s 'add' "$TEMP_FILE.part" 2>/dev/null > "$TEMP_FILE" || echo "[]" > "$TEMP_FILE"
rm -f "$TEMP_FILE.part"

TOTAL_TICKETS=$(jq 'length' "$TEMP_FILE")
echo "Total tickets with customAttributes: $TOTAL_TICKETS"
echo ""

echo "════════════════════════════════════════════════════════════════════"
echo "ALL CUSTOM ATTRIBUTES NAMES FOUND"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Extract all unique custom attribute names
jq -r '[.[].customAttributes | keys[]] | unique | sort[]' "$TEMP_FILE"

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "CUSTOM ATTRIBUTES CONTENENTI 'CATEGORIA', 'SLA' O 'PREMIUM'"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Search attributes with keywords
MATCHING_ATTRS=$(jq -r '[.[].customAttributes | keys[]] | unique | map(select(test("categoria|sla|premium|mon|macro"; "i"))) | sort[]' "$TEMP_FILE")

if [[ -n "$MATCHING_ATTRS" && "$MATCHING_ATTRS" != "null" ]]; then
    echo "$MATCHING_ATTRS"
    echo ""
    
    # For each attribute found, show some examples
    while IFS= read -r ATTR; do
      [[ -z "$ATTR" ]] && continue
      echo "──────────────────────────────────────────────────────────────────"
      echo "Examples for attribute: '$ATTR'"
      echo "──────────────────────────────────────────────────────────────────"
      
      jq --arg attr "$ATTR" -r '
        [.[] | select(.customAttributes[$attr] != null) |
          {id, codice, valore: .customAttributes[$attr]}] |
        unique_by(.valore) |
        sort_by(.valore) |
        .[] |
        "  [\(.id)] \(.codice) → \(.valore)"
      ' "$TEMP_FILE" | head -20
      
      echo ""
    done <<< "$MATCHING_ATTRS"
else
    echo "No custom attributes found with these keywords"
    echo ""
fi

echo "════════════════════════════════════════════════════════════════════"
echo "FIELD VALUES 'type' (Potential Subcategories)"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# It also analyzes the type field
TIPO_FILE="/tmp/all-tipo-values.json"
echo "[]" > "$TIPO_FILE"

for PAGE in $(seq 1 $PAGES); do
  curl -s \
    -H "Accept: application/json" \
    -H "Authorization: Bearer ${TOKEN}" \
    "${YDEA_BASE_URL}/tickets?limit=100&page=${PAGE}" | \
    jq '[.objs[] | select(.tipo != null) | {tipo}]' >> "$TIPO_FILE.part" 2>/dev/null || true
done

jq -s 'add | map(.tipo) | unique | sort[]' "$TIPO_FILE.part" 2>/dev/null > "$TIPO_FILE" || echo "[]" > "$TIPO_FILE"
rm -f "$TIPO_FILE.part"

echo "Unique values ​​of the 'type' field:"
jq -r '.[]' "$TIPO_FILE" | sed 's/^/  - /'

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "SPECIFIC SEARCH: Ticket with 'Premium' or 'Mon' in customAttributes"
echo "════════════════════════════════════════════════════════════════════"
echo ""

PREMIUM_TICKETS=$(jq '[.[] | select(.customAttributes | tostring | test("Premium|Mon|premium|mon"))] | length' "$TEMP_FILE")

echo "Ticket trovati: $PREMIUM_TICKETS"

if [[ "$PREMIUM_TICKETS" -gt 0 ]]; then
    echo ""
    echo "First 10 tickets with 'Premium' or 'Mon':"
    jq -r '[.[] | select(.customAttributes | tostring | test("Premium|Mon|premium|mon"))] |
      .[0:10][] |
      "  [\(.id)] \(.codice) → " + (.customAttributes | tojson)' "$TEMP_FILE"
fi

echo ""
echo " Analisi completata!"
echo ""
echo "Saved files:"
echo "- $TEMP_FILE (all customAttributes)"
echo "- $FILE_TYPE (all 'type' values)"
echo ""
echo "Use these commands for further analysis:"
echo "   cat $TEMP_FILE | jq '.[] | select(.customAttributes | has(\"NOME_CAMPO\"))'"
echo "   cat $TEMP_FILE | jq '[.[].customAttributes | keys[]] | unique'"
