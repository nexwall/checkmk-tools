#!/bin/bash
# list-tipo-values.sh - List all values ​​of the 'type' field

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ydea-toolkit.sh"

PAGES="${1:-30}"

echo "Collecting 'type' field values ​​from $PAGES pages..."
echo ""

ensure_token
TOKEN="$(load_token)"

declare -A TIPO_MAP

for PAGE in $(seq 1 $PAGES); do
  echo -n "   Pagina $PAGE/$PAGES... "
  
  RESPONSE=$(curl -s \
    -H "Accept: application/json" \
    -H "Authorization: Bearer ${TOKEN}" \
    "${YDEA_BASE_URL}/tickets?limit=100&page=${PAGE}")
  
  if ! echo "$RESPONSE" | jq -e '.objs' >/dev/null 2>&1; then
    echo "Mistake"
    break
  fi
  
  COUNT=$(echo "$RESPONSE" | jq -r '.objs | length')
  if [[ "$COUNT" -eq 0 ]]; then
    echo "End"
    break
  fi
  
  echo "$COUNT ticket"
  
  # Extract all 'type' values
  while IFS= read -r tipo; do
    [[ -z "$tipo" || "$tipo" == "null" ]] && continue
    TIPO_MAP["$tipo"]=1
  done < <(echo "$RESPONSE" | jq -r '.objs[].tipo // empty')
done

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "ALL VALUES OF THE 'type' FIELD ($(printf '%s\n'"${!TIPO_MAP[@]}" | wc -l) valori unici)"
echo "════════════════════════════════════════════════════════════════════"
echo ""

printf '%s\n' "${!TIPO_MAP[@]}" | sort | while IFS= read -r tipo; do
  echo "  • $tipo"
done

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "MAPPING WITH THE REQUIRED SUBCATEGORIES"
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo "Sottocategorie richieste → Valori 'tipo' trovati:"
echo ""

# Array of required subcategories
declare -a REQUIRED=(
  "Centrale telefonica NethVoice"
  "Firewall UTM NethSecurity"
  "Collaboration Suite NethService"
  "Computer client"
  "Server"
  "Apparati di rete - Networking"
  "Hypervisor"
  "Consulenza tecnica specialistica"
)

# Cerca corrispondenze
for required in "${REQUIRED[@]}"; do
  found=""
  
  # Cerca tra i tipi trovati
  while IFS= read -r tipo; do
    # Case-insensitive match with keywords
    keyword=$(echo "$required" | sed 's/ .*//' | tr '[:upper:]' '[:lower:]')
    if echo "$tipo" | tr '[:upper:]' '[:lower:]' | grep -q "$keyword"; then
      found="$tipo"
      break
    fi
  done < <(printf '%s\n' "${!TIPO_MAP[@]}")
  
  if [[ -n "$found" ]]; then
    echo "   $required"
    echo "     → '$found'"
  else
    echo "   $required"
    echo "→ NOT FOUND"
  fi
  echo ""
done

echo "════════════════════════════════════════════════════════════════════"
echo "PRIORITY SEARCH (priorita_id)"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Also collect priorities
declare -A PRIO_MAP

for PAGE in $(seq 1 5); do
  RESPONSE=$(curl -s \
    -H "Accept: application/json" \
    -H "Authorization: Bearer ${TOKEN}" \
    "${YDEA_BASE_URL}/tickets?limit=100&page=${PAGE}")
  
  while IFS='|' read -r pid pname; do
    [[ -z "$pid" || "$pid" == "null" ]] && continue
    PRIO_MAP["$pid"]="$pname"
  done < <(echo "$RESPONSE" | jq -r '.objs[] | "\(.priorita_id // "")|\(.priorita // "")"')
done

echo "Priority Mapping (ID → Name):"
for pid in $(printf '%s\n' "${!PRIO_MAP[@]}" | sort -n); do
  echo "  $pid → ${PRIO_MAP[$pid]}"
done

echo ""
echo " Analisi completata!"
