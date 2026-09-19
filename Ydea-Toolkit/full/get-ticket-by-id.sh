#!/bin/bash
# get-ticket-by-id.sh - Retrieves a specific ticket by numeric ID

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Toolkit source for helper functions only
source "$SCRIPT_DIR/ydea-toolkit.sh"

TICKET_ID="${1:-}"

if [[ -z "$TICKET_ID" ]]; then
    echo " Uso: $0 <ticket_id>"
    echo ""
    echo "Esempio:"
    echo "  $0 1486125"
    exit 1
fi

echo " Recuperando ticket ID: $TICKET_ID..."
echo ""

# Make sure you have the token
ensure_token
TOKEN="$(load_token)"

# Try with the direct endpoint /tickets/{id} first
echo " Tentativo 1: GET /tickets/$TICKET_ID"
RESPONSE=$(curl -s -w '\n%{http_code}' \
  -H "Accept: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  "${YDEA_BASE_URL}/tickets/${TICKET_ID}" 2>&1 || echo -e "\n404")

HTTP_BODY="$(echo "$RESPONSE" | sed '$d')"
HTTP_CODE="$(echo "$RESPONSE" | tail -n1)"

echo "   HTTP Status: $HTTP_CODE"
echo ""

if [[ "$HTTP_CODE" == "200" ]]; then
    TICKET_DATA="$HTTP_BODY"
else
    # If that fails, try pagination
    TICKET_DATA=""
    LIMIT=100
    MAX_PAGES=100
    
    # Cerca fino a 100 pagine (10000 ticket totali)
    echo "Pagination search (limit=$LIMIT per page)..."
    echo ""
    
    for PAGE in $(seq 1 $MAX_PAGES); do
        echo -n "   Pagina $PAGE... "
        
        RESPONSE=$(curl -s -w '\n%{http_code}' \
          -H "Accept: application/json" \
          -H "Authorization: Bearer ${TOKEN}" \
          "${YDEA_BASE_URL}/tickets?limit=${LIMIT}&page=${PAGE}")
        
        HTTP_BODY="$(echo "$RESPONSE" | sed '$d')"
        HTTP_CODE="$(echo "$RESPONSE" | tail -n1)"
        
        if [[ "$HTTP_CODE" != "200" ]]; then
            echo "HTTP Error $HTTP_CODE"
            break
        fi
        
        # Check if there are any results
        COUNT=$(echo "$HTTP_BODY" | jq -r '.objs | length')
        if [[ "$COUNT" -eq 0 ]]; then
            echo "No ticket, end of search"
            break
        fi
        
        # Mostra range ID disponibili
        MIN_ID=$(echo "$HTTP_BODY" | jq -r '.objs | map(.id) | min')
        MAX_ID=$(echo "$HTTP_BODY" | jq -r '.objs | map(.id) | max')
        echo "Range: $MIN_ID - $MAX_ID ($COUNT ticket)"
        
        # Filter by ID
        TICKET_DATA=$(echo "$HTTP_BODY" | jq --arg tid "$TICKET_ID" '.objs[] | select(.id == ($tid|tonumber))')
        
        if [[ -n "$TICKET_DATA" && "$TICKET_DATA" != "null" ]]; then
            echo ""
            echo "Ticket found on $PAGE!"
            break
        fi
        
        # If the searched ID is less than the minimum, continue to next page
        if [[ "$TICKET_ID" -lt "$MIN_ID" ]]; then
            # Continue searching on subsequent pages (older tickets)
            continue
        fi
        
        # If the searched ID is greater than the maximum, the ticket is on the previous page or does not exist
        if [[ "$TICKET_ID" -gt "$MAX_ID" ]]; then
            echo ""
            echo "Ticket ID $TICKET_ID > $MAX_ID, searched beyond range"
            break
        fi
    done
    
    if [[ -z "$TICKET_DATA" || "$TICKET_DATA" == "null" ]]; then
        echo ""
        echo "Ticket ID $TICKET_ID not found"
        echo ""
        echo "The ticket could be:"
        echo "- Beyond the $MAX_PAGES page (more than 10000 tickets ago)"
        echo "- State archived or deleted"
        echo "- With wrong ID"
        exit 1
    fi
fi

echo "Ticket found!"
echo ""

TICKET_CODE=$(echo "$TICKET_DATA" | jq -r '.codice // "N/A"')

echo "════════════════════════════════════════════════════════════════════"
echo "FULL TICKET STRUCTURE ID=$TICKET_ID CODE=$TICKET_CODE"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Show all formatted JSON
echo "$TICKET_DATA" | jq '.'

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "KEY FIELDS EXTRACTED"
echo "════════════════════════════════════════════════════════════════════"
echo ""

echo " Info Base:"
echo "   ID: $(echo "$TICKET_DATA" | jq -r '.id')"
echo "   Codice: $(echo "$TICKET_DATA" | jq -r '.codice // "N/A"')"
echo "   Titolo: $(echo "$TICKET_DATA" | jq -r '.titolo // "N/A"')"
echo "   Descrizione: $(echo "$TICKET_DATA" | jq -r '.descrizione // .testo // "N/A"')"
echo ""

echo " Priorità:"
echo "   Priorità: $(echo "$TICKET_DATA" | jq -r '.priorita // "N/A"')"
echo "   Priorità ID: $(echo "$TICKET_DATA" | jq -r '.priorita_id // .prioritaId // "N/A"')"
echo ""

echo " Categorie:"
echo "   Categoria: $(echo "$TICKET_DATA" | jq -r '.categoria // "N/A"')"
echo "   Categoria ID: $(echo "$TICKET_DATA" | jq -r '.categoria_id // .categoriaId // "N/A"')"
echo "   Sotto-categoria: $(echo "$TICKET_DATA" | jq -r '.sottocategoria // .sotto_categoria // "N/A"')"
echo "   Sotto-categoria ID: $(echo "$TICKET_DATA" | jq -r '.sottocategoria_id // .sottocategoriaId // "N/A"')"
echo "   Macro Categoria: $(echo "$TICKET_DATA" | jq -r '.macrocategoria // .macro_categoria // "N/A"')"
echo "   Macro Categoria ID: $(echo "$TICKET_DATA" | jq -r '.macrocategoria_id // .macrocategoriaId // "N/A"')"
echo ""

echo "  SLA:"
echo "   SLA: $(echo "$TICKET_DATA" | jq -r '.sla // "N/A"')"
echo "   SLA ID: $(echo "$TICKET_DATA" | jq -r '.sla_id // .slaId // "N/A"')"
echo "SLA Name: $(echo"$TICKET_DATA" | jq -r '.sla_nome // .slaNome // "N/A"')"
echo "   SLA Descrizione: $(echo "$TICKET_DATA" | jq -r '.sla_descrizione // .slaDescrizione // "N/A"')"
echo ""

echo "State:"
echo "Status: $(echo"$TICKET_DATA" | jq -r '.stato // "N/A"')"
echo "ID Status: $(echo"$TICKET_DATA" | jq -r '.stato_id // .statoId // "N/A"')"
echo ""

echo " Assegnazione:"
echo "   Assegnato A: $(echo "$TICKET_DATA" | jq -r '.assegnatoA // .assegnato_a // "N/A"')"
echo ""

echo " Azienda/Cliente:"
echo "   Azienda: $(echo "$TICKET_DATA" | jq -r '.azienda // "N/A"')"
echo "   Azienda ID: $(echo "$TICKET_DATA" | jq -r '.azienda_id // .aziendaId // "N/A"')"
echo "   Cliente: $(echo "$TICKET_DATA" | jq -r '.cliente // "N/A"')"
echo ""

echo " Custom Attributes:"
if echo "$TICKET_DATA" | jq -e '.customAttributes' >/dev/null 2>&1; then
    echo "$TICKET_DATA" | jq '.customAttributes'
elif echo "$TICKET_DATA" | jq -e '.custom_attributes' >/dev/null 2>&1; then
    echo "$TICKET_DATA" | jq '.custom_attributes'
elif echo "$TICKET_DATA" | jq -e '.campiCustom' >/dev/null 2>&1; then
    echo "$TICKET_DATA" | jq '.campiCustom'
else
    echo "No custom attributes found"
fi
echo ""

echo "════════════════════════════════════════════════════════════════════"
echo "ALL KEYS AVAILABLE IN JSON"
echo "════════════════════════════════════════════════════════════════════"
echo ""

echo "$TICKET_DATA" | jq -r 'keys[]' | sort

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "CAMPI CONTENENTI 'CATEGORIA', 'SLA', 'PREMIUM' O 'MON'"
echo "════════════════════════════════════════════════════════════════════"
echo ""

echo "$TICKET_DATA" | jq 'to_entries | map(select(.key | test("categoria|sla|premium|mon|categor|custom"; "i"))) | from_entries'

echo ""
echo " Ispezione completata!"
echo ""
echo "I save the complete JSON in /tmp/ticket-${TICKET_ID}.json for future reference..."
echo "$TICKET_DATA" | jq '.' > "/tmp/ticket-${TICKET_ID}.json"
echo "Saved file: /tmp/ticket-${TICKET_ID}.json"
