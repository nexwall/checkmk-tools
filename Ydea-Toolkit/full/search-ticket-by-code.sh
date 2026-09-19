#!/bin/bash
# search-ticket-by-code.sh - Search for a ticket by code (e.g. TK25/003209)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Toolkit source for helper functions only
source "$SCRIPT_DIR/ydea-toolkit.sh"

TICKET_CODE="${1:-}"

if [[ -z "$TICKET_CODE" ]]; then
    echo " Uso: $0 <ticket_code>"
    echo ""
    echo "Esempio:"
    echo "  $0 TK25/003209"
    exit 1
fi

echo "Searching for tickets with code: $TICKET_CODE..."
echo ""

# Make sure you have the token
ensure_token
TOKEN="$(load_token)"

# Try with higher limit to find older tickets
for LIMIT in 100 200 500 1000; do
    echo "Attempting limit=$LIMIT..."
    
    RESPONSE=$(curl -s -w '\n%{http_code}' \
      -H "Accept: application/json" \
      -H "Authorization: Bearer ${TOKEN}" \
      "${YDEA_BASE_URL}/tickets?limit=${LIMIT}")
    
    HTTP_BODY="$(echo "$RESPONSE" | sed '$d')"
    HTTP_CODE="$(echo "$RESPONSE" | tail -n1)"
    
    if [[ "$HTTP_CODE" != "200" ]]; then
      echo "HTTP Error $HTTP_CODE"
      continue
    fi
    
    # Search for the ticket by code
    TICKET_DATA=$(echo "$HTTP_BODY" | jq --arg code "$TICKET_CODE" '.objs[] | select(.codice == $code)')
    
    if [[ -n "$TICKET_DATA" && "$TICKET_DATA" != "null" ]]; then
      echo "Ticket found with limit=$LIMIT!"
      echo ""
      
      TICKET_ID=$(echo "$TICKET_DATA" | jq -r '.id')
      
      echo "════════════════════════════════════════════════════════════════════"
      echo "COMPLETE TICKET STRUCTURE $TICKET_CODE (ID: $TICKET_ID)"
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
      
      echo " Custom Attributes:"
      if echo "$TICKET_DATA" | jq -e '.customAttributes' >/dev/null 2>&1; then
        echo "$TICKET_DATA" | jq '.customAttributes'
      elif echo "$TICKET_DATA" | jq -e '.custom_attributes' >/dev/null 2>&1; then
        echo "$TICKET_DATA" | jq '.custom_attributes'
      else
        echo "No custom attributes found"
      fi
      echo ""
      
      echo " Assegnazione:"
      echo "   Assegnato A: $(echo "$TICKET_DATA" | jq -r '.assegnatoA // .assegnato_a // "N/A"')"
      echo ""
      
      echo " Azienda:"
      echo "   Azienda: $(echo "$TICKET_DATA" | jq -r '.azienda // "N/A"')"
      echo "   Azienda ID: $(echo "$TICKET_DATA" | jq -r '.azienda_id // .aziendaId // "N/A"')"
      echo ""
      
      echo "════════════════════════════════════════════════════════════════════"
      echo "ALL KEYS AVAILABLE IN JSON"
      echo "════════════════════════════════════════════════════════════════════"
      echo ""
      
      echo "$TICKET_DATA" | jq -r 'keys[]' | sort
      
      echo ""
      echo "════════════════════════════════════════════════════════════════════"
      echo "CAMPI CONTENENTI 'CATEGORIA', 'SLA' O 'PREMIUM'"
      echo "════════════════════════════════════════════════════════════════════"
      echo ""
      
      echo "$TICKET_DATA" | jq 'to_entries | map(select(.key | test("categoria|sla|premium|categor"; "i"))) | from_entries'
      
      echo ""
      echo " Ispezione completata!"
      exit 0
    fi
done

echo "Ticket $TICKET_CODE not found in first 1000 tickets"
echo ""
echo "Tip: It could be a very old or archived ticket."
echo "Try searching manually on Ydea: https://my.ydea.cloud"

exit 1
