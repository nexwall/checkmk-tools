#!/bin/bash
# test-sla-api.sh - Test new YDEA API for automatic SLA
#
# YDEA has implemented API for automatic SLA insertion:
# - Default SLA of the registry
# - SLA of the associated contract
#
# This script tests both modes

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ydea-toolkit.sh"

CONFIG_FILE="$SCRIPT_DIR/../config/premium-mon-config.json"

if [[ ! -f "$CONFIG_FILE" ]]; then
    log_error "File configurazione non trovato: $CONFIG_FILE"
    exit 1
fi

# Load configuration
ANAGRAFICA_ID=$(jq -r '.anagrafica_id' "$CONFIG_FILE")
PRIORITA_ID=$(jq -r '.priorita_id' "$CONFIG_FILE")
FONTE=$(jq -r '.fonte' "$CONFIG_FILE")
SLA_ID=$(jq -r '.sla_id // empty' "$CONFIG_FILE")
ASSEGNATOA_ID=$(jq -r '.assegnatoa_id // empty' "$CONFIG_FILE")

echo "════════════════════════════════════════════════════════════════════"
echo "TEST NEW API YDEA - AUTOMATIC SLA"
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo "Configuration:"
echo "   Anagrafica ID: $ANAGRAFICA_ID"
echo "   Priorita ID: $PRIORITA_ID"
echo "   SLA ID (config): $SLA_ID"
echo ""

# Autenticazione
ensure_token

echo "════════════════════════════════════════════════════════════════════"
echo "TEST 1: Creazione ticket SENZA sla_id (SLA default anagrafica)"
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo "Expectation: API should use master data default SLA"
echo ""

# Ticket senza sla_id
TICKET_BODY_1=$(jq -n \
  --arg titolo "[TEST] Ticket senza SLA - $(date '+%Y-%m-%d %H:%M:%S')" \
  --arg descrizione "Test SLA automatica - caso 1: senza sla_id" \
  --argjson anagrafica "$ANAGRAFICA_ID" \
  --argjson priorita "$PRIORITA_ID" \
  --arg fonte "$FONTE" \
  --arg tipo "Consulenza tecnica specialistica" \
  '{
    titolo: $titolo,
    descrizione: $descrizione,
    anagrafica_id: $anagrafica,
    priorita_id: $priorita,
    fonte: $fonte,
    tipo: $tipo
  }')

if [[ -n "$ASSEGNATOA_ID" ]]; then
    TICKET_BODY_1=$(echo "$TICKET_BODY_1" | jq --argjson uid "$ASSEGNATOA_ID" '. + {assegnatoa: [$uid]}')
fi

echo "Sending API request..."
echo ""
echo "Body JSON:"
echo "$TICKET_BODY_1" | jq '.'
echo ""

RESPONSE_1=$(ydea_api POST "/ticket" "$TICKET_BODY_1")

TICKET_ID_1=$(echo "$RESPONSE_1" | jq -r '.id // .ticket_id // .data.id // empty')
TICKET_CODE_1=$(echo "$RESPONSE_1" | jq -r '.codice // .code // .data.codice // empty')

if [[ -n "$TICKET_ID_1" && "$TICKET_ID_1" != "null" ]]; then
  echo "Ticket 1 successfully created!"
  echo "   ID: $TICKET_ID_1"
  echo "   Codice: ${TICKET_CODE_1:-N/A}"
  echo ""
  
  # Retrieve ticket detail to verify SLA
  echo "Check assigned SLA..."
  DETAIL_1=$(ydea_api GET "/ticket/${TICKET_ID_1}")
  
  echo ""
  echo "Dettaglio ticket:"
  echo "$DETAIL_1" | jq '{id, codice, titolo, sla_id, sla_nome: .sla.nome, contratto_id, contratto_nome: .contratto.nome}'
  echo ""
  
  SLA_FOUND=$(echo "$DETAIL_1" | jq -r '.sla_id // .sla.id // empty')
  if [[ -n "$SLA_FOUND" && "$SLA_FOUND" != "null" ]]; then
    echo " SLA automaticamente assegnata: ID=$SLA_FOUND"
  else
    echo "NO SLA assigned (possible API issue)"
  fi
else
  echo "Ticket creation failed"
  echo ""
  echo "Response completa:"
  echo "$RESPONSE_1" | jq '.'
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "TEST 2: Ticket creation WITH explicit sla_id"
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo " Aspettativa: API dovrebbe usare SLA specificata (ID=$SLA_ID)"
echo ""

# Ticket with explicit sla_id
TICKET_BODY_2=$(jq -n \
  --arg titolo "[TEST] Ticket con SLA esplicita - $(date '+%Y-%m-%d %H:%M:%S')" \
  --arg descrizione "Test SLA automatica - caso 2: con sla_id=$SLA_ID" \
  --argjson anagrafica "$ANAGRAFICA_ID" \
  --argjson priorita "$PRIORITA_ID" \
  --arg fonte "$FONTE" \
  --arg tipo "Consulenza tecnica specialistica" \
  --argjson sla_id "$SLA_ID" \
  '{
    titolo: $titolo,
    descrizione: $descrizione,
    anagrafica_id: $anagrafica,
    priorita_id: $priorita,
    fonte: $fonte,
    tipo: $tipo,
    sla_id: $sla_id
  }')

if [[ -n "$ASSEGNATOA_ID" ]]; then
    TICKET_BODY_2=$(echo "$TICKET_BODY_2" | jq --argjson uid "$ASSEGNATOA_ID" '. + {assegnatoa: [$uid]}')
fi

echo "Sending API request..."
echo ""
echo "Body JSON:"
echo "$TICKET_BODY_2" | jq '.'
echo ""

RESPONSE_2=$(ydea_api POST "/ticket" "$TICKET_BODY_2")

TICKET_ID_2=$(echo "$RESPONSE_2" | jq -r '.id // .ticket_id // .data.id // empty')
TICKET_CODE_2=$(echo "$RESPONSE_2" | jq -r '.codice // .code // .data.codice // empty')

if [[ -n "$TICKET_ID_2" && "$TICKET_ID_2" != "null" ]]; then
  echo "Ticket 2 successfully created!"
  echo "   ID: $TICKET_ID_2"
  echo "   Codice: ${TICKET_CODE_2:-N/A}"
  echo ""
  
  # Retrieve ticket detail to verify SLA
  echo "Check assigned SLA..."
  DETAIL_2=$(ydea_api GET "/ticket/${TICKET_ID_2}")
  
  echo ""
  echo "Dettaglio ticket:"
  echo "$DETAIL_2" | jq '{id, codice, titolo, sla_id, sla_nome: .sla.nome, contratto_id, contratto_nome: .contratto.nome}'
  echo ""
  
  SLA_FOUND=$(echo "$DETAIL_2" | jq -r '.sla_id // .sla.id // empty')
  if [[ "$SLA_FOUND" == "$SLA_ID" ]]; then
    echo " SLA corretta assegnata: ID=$SLA_FOUND (atteso: $SLA_ID)"
  else
    echo "Different SLA: found ID=$SLA_FOUND, expected ID=$SLA_ID"
  fi
else
  echo "Ticket creation failed"
  echo ""
  echo "Response completa:"
  echo "$RESPONSE_2" | jq '.'
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "TEST 3: Ticket creation WITH contract_id (SLA from contract)"
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo " Aspettativa: API dovrebbe estrarre SLA dal contratto specificato"
echo ""

# First find a valid contract for the registry
echo "Search contracts by registry $ANAGRAFICA_ID..."

CONTRACTS=$(ydea_api GET "/contratti?anagrafica_id=${ANAGRAFICA_ID}&limit=10")
CONTRACT_ID=$(echo "$CONTRACTS" | jq -r '.objs[0].id // .data[0].id // empty')

if [[ -z "$CONTRACT_ID" || "$CONTRACT_ID" == "null" ]]; then
  echo "NO CONTRACT found for this registry"
  echo "   Skippo TEST 3"
  echo ""
else
  echo "Contract found: ID=$CONTRACT_ID"
  echo ""
  
  # Ticket with contract_id
  TICKET_BODY_3=$(jq -n \
    --arg titolo "[TEST] Ticket con contratto_id - $(date '+%Y-%m-%d %H:%M:%S')" \
    --arg descrizione "Test SLA automatica - caso 3: con contratto_id=$CONTRACT_ID" \
    --argjson anagrafica "$ANAGRAFICA_ID" \
    --argjson priorita "$PRIORITA_ID" \
    --arg fonte "$FONTE" \
    --arg tipo "Consulenza tecnica specialistica" \
    --argjson contratto_id "$CONTRACT_ID" \
    '{
      titolo: $titolo,
      descrizione: $descrizione,
      anagrafica_id: $anagrafica,
      priorita_id: $priorita,
      fonte: $fonte,
      tipo: $tipo,
      contratto_id: $contratto_id
    }')
  
  if [[ -n "$ASSEGNATOA_ID" ]]; then
      TICKET_BODY_3=$(echo "$TICKET_BODY_3" | jq --argjson uid "$ASSEGNATOA_ID" '. + {assegnatoa: [$uid]}')
  fi
  
  echo "Sending API request..."
  echo ""
  echo "Body JSON:"
  echo "$TICKET_BODY_3" | jq '.'
  echo ""
  
  RESPONSE_3=$(ydea_api POST "/ticket" "$TICKET_BODY_3")
  
  TICKET_ID_3=$(echo "$RESPONSE_3" | jq -r '.id // .ticket_id // .data.id // empty')
  TICKET_CODE_3=$(echo "$RESPONSE_3" | jq -r '.codice // .code // .data.codice // empty')
  
  if [[ -n "$TICKET_ID_3" && "$TICKET_ID_3" != "null" ]]; then
    echo "Ticket 3 successfully created!"
    echo "   ID: $TICKET_ID_3"
    echo "   Codice: ${TICKET_CODE_3:-N/A}"
    echo ""
    
    # Retrieve ticket detail to verify SLA and contract
    echo "Check assigned SLA and contract..."
    DETAIL_3=$(ydea_api GET "/ticket/${TICKET_ID_3}")
    
    echo ""
    echo "Dettaglio ticket:"
    echo "$DETAIL_3" | jq '{id, codice, titolo, sla_id, sla_nome: .sla.nome, contratto_id, contratto_nome: .contratto.nome}'
    echo ""
    
    CONTRACT_FOUND=$(echo "$DETAIL_3" | jq -r '.contratto_id // .contratto.id // empty')
    SLA_FOUND=$(echo "$DETAIL_3" | jq -r '.sla_id // .sla.id // empty')
    
    if [[ "$CONTRACT_FOUND" == "$CONTRACT_ID" ]]; then
      echo "Contract correctly associated: ID=$CONTRACT_FOUND"
    else
      echo "Different or missing contract: found ID=$CONTRACT_FOUND, expected ID=$CONTRACT_ID"
    fi
    
    if [[ -n "$SLA_FOUND" && "$SLA_FOUND" != "null" ]]; then
      echo " SLA estratta dal contratto: ID=$SLA_FOUND"
    else
      echo "SLA NOT extracted from the contract"
    fi
  else
    echo "Ticket creation failed"
    echo ""
    echo "Response completa:"
    echo "$RESPONSE_3" | jq '.'
  fi
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo " RIEPILOGO TEST"
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo "TEST 1 (senza sla_id):"
if [[ -n "$TICKET_ID_1" && "$TICKET_ID_1" != "null" ]]; then
  echo "Ticket created: $TICKET_CODE_1 (ID: $TICKET_ID_1)"
  echo "    https://my.ydea.cloud/ticket/${TICKET_ID_1}"
else
  echo "FAILED"
fi
echo ""

echo "TEST 2 (with explicit sla_id):"
if [[ -n "$TICKET_ID_2" && "$TICKET_ID_2" != "null" ]]; then
  echo "Ticket created: $TICKET_CODE_2 (ID: $TICKET_ID_2)"
  echo "    https://my.ydea.cloud/ticket/${TICKET_ID_2}"
else
  echo "FAILED"
fi
echo ""

if [[ -n "$CONTRACT_ID" && "$CONTRACT_ID" != "null" ]]; then
  echo "TEST 3 (with contract_id):"
  if [[ -n "$TICKET_ID_3" && "$TICKET_ID_3" != "null" ]]; then
    echo "Ticket created: $TICKET_CODE_3 (ID: $TICKET_ID_3)"
    echo "    https://my.ydea.cloud/ticket/${TICKET_ID_3}"
  else
    echo "FAILED"
  fi
  echo ""
fi

echo "════════════════════════════════════════════════════════════════════"
echo "Test completed!"
echo ""
echo "NOTE: If YDEA has not documented endpoints, these are the fields tested:"
echo "   - sla_id (esistente, dovrebbe funzionare)"
echo "- contract_id (new?, to check if supported)"
echo ""
echo "Manually verify tickets created on Ydea UI to confirm SLA:"
echo " https://my.ydea.cloud"
echo ""
