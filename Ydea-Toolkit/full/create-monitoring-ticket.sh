#!/bin/bash
# create-monitoring-ticket.sh - Create Ydea ticket from CheckMK alarm

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ydea-toolkit.sh"

# Load Premium_Mon configuration
CONFIG_FILE="$SCRIPT_DIR/../config/premium-mon-config.json"

if [[ ! -f "$CONFIG_FILE" ]]; then
    log_error "File configurazione non trovato: $CONFIG_FILE"
    exit 1
fi

# Read parameters from CheckMK
CMK_HOST="${1:-}"
CMK_SERVICE="${2:-}"
CMK_STATE="${3:-}"
CMK_OUTPUT="${4:-}"
CMK_HOSTIP="${5:-}"

if [[ -z "$CMK_HOST" ]]; then
    echo "Usage: $0 <HOST> <SERVICE> <STATE> <OUTPUT> [HOST_IP]"
    echo ""
    echo "Esempio:"
    echo "  $0 'mail.example.com' 'HTTP' 'CRITICAL' 'Connection timeout' '1.2.3.4'"
    exit 1
fi

log_info "=== Creazione ticket da CheckMK ==="
log_info "Host: $CMK_HOST"
log_info "Service: $CMK_SERVICE"
log_info "State: $CMK_STATE"
log_info "Output: $CMK_OUTPUT"
log_info "IP: ${CMK_HOSTIP:-N/A}"

# Load configuration
ANAGRAFICA_ID=$(jq -r '.anagrafica_id' "$CONFIG_FILE")
PRIORITA_ID=$(jq -r '.priorita_id' "$CONFIG_FILE")
FONTE=$(jq -r '.fonte' "$CONFIG_FILE")
SLA_ID=$(jq -r '.sla_id // empty' "$CONFIG_FILE")
ASSEGNATOA_ID=$(jq -r '.assegnatoa_id // empty' "$CONFIG_FILE")
DEFAULT_TIPO=$(jq -r '.default_tipo' "$CONFIG_FILE")

log_debug "Config: anagrafica=$ANAGRAFICA_ID, priorita=$PRIORITA_ID, sla=$SLA_ID, assegnatoa=$ASSEGNATOA_ID"

# Determine type based on service/host
determine_tipo() {
  local service_lower=$(echo "$CMK_SERVICE $CMK_OUTPUT $CMK_HOST" | tr '[:upper:]' '[:lower:]')
    
  # Check each type
  while IFS= read -r tipologia_key; do
    # Read keywords for this type
    local keywords=$(jq -r ".tipologie.${tipologia_key}.keywords[]" "$CONFIG_FILE" 2>/dev/null || echo "")
    
    # Check if any keywords match
    while IFS= read -r keyword; do
      [[ -z "$keyword" ]] && continue
      if echo "$service_lower" | grep -qi "$keyword"; then
        jq -r ".tipologie.${tipologia_key}.tipo_ydea" "$CONFIG_FILE"
        return 0
      fi
    done <<< "$keywords"
  done < <(jq -r '.tipologie | keys[]' "$CONFIG_FILE")
    
  # Default if no match found
  echo "$DEFAULT_TIPO"
}

TIPO=$(determine_tipo)
log_info "Tipologia determinata: $TIPO"

# Costruisci titolo e descrizione
if [[ "$CMK_STATE" == "DOWN" || "$CMK_STATE" == "CRITICAL" ]]; then
    STATE_ICON=""
elif [[ "$CMK_STATE" == "WARNING" ]]; then
    STATE_ICON=""
else
    STATE_ICON="ℹ"
fi

TITOLO="[${CMK_STATE}] ${CMK_HOST}"
if [[ -n "$CMK_SERVICE" && "$CMK_SERVICE" != "Host" ]]; then
    TITOLO="${TITOLO} - ${CMK_SERVICE}"
fi

if [[ -n "$CMK_HOSTIP" ]]; then
    TITOLO="${TITOLO} [IP=${CMK_HOSTIP}]"
fi

# Descrizione generica
DESCRIZIONE="Allarme da sistema di monitoraggio CheckMK"

# Alarm details for private note
NOTA_PRIVATA="<p><strong>${STATE_ICON} Allarme da CheckMK Monitoring</strong></p><ul><li><strong>Host:</strong> ${CMK_HOST}</li><li><strong>Service:</strong> ${CMK_SERVICE:-Host Check}</li><li><strong>Stato:</strong> ${CMK_STATE}</li><li><strong>IP:</strong> ${CMK_HOSTIP:-N/A}</li><li><strong>Data/Ora:</strong> $(date '+%Y-%m-%d %H:%M:%S')</li></ul><p><strong>Output:</strong></p><pre>${CMK_OUTPUT}</pre><p><em>Ticket creato automaticamente dal sistema di monitoraggio CheckMK</em></p>"

log_info "Titolo: $TITOLO"

# Crea ticket tramite API
log_info "Creazione ticket in corso..."

# Costruisci corpo ticket base
TICKET_BODY_BASE=$(jq -n \
  --arg titolo "$TITOLO" \
  --arg descrizione "$DESCRIZIONE" \
  --argjson anagrafica "$ANAGRAFICA_ID" \
  --argjson priorita "$PRIORITA_ID" \
  --arg fonte "$FONTE" \
  --arg tipo "$TIPO" \
  '{
    titolo: $titolo,
    descrizione: $descrizione,
    anagrafica_id: $anagrafica,
    priorita_id: $priorita,
    fonte: $fonte,
    tipo: $tipo
  }')

# Aggiungi campi opzionali se presenti
TICKET_BODY="$TICKET_BODY_BASE"

if [[ -n "$ASSEGNATOA_ID" ]]; then
    TICKET_BODY=$(echo "$TICKET_BODY" | jq --argjson uid "$ASSEGNATOA_ID" '. + {assegnatoa: [$uid]}')
fi

if [[ -n "$SLA_ID" ]]; then
    TICKET_BODY=$(echo "$TICKET_BODY" | jq --argjson sid "$SLA_ID" '. + {sla_id: $sid}')
fi

log_debug "Body: $TICKET_BODY"

# API call to create tickets
ensure_token

RESPONSE=$(ydea_api POST "/ticket" "$TICKET_BODY")

# Extract created ticket ID
TICKET_ID=$(echo "$RESPONSE" | jq -r '.id // .ticket_id // .data.id // empty')
TICKET_CODE=$(echo "$RESPONSE" | jq -r '.codice // .code // .data.codice // empty')

if [[ -n "$TICKET_ID" && "$TICKET_ID" != "null" ]]; then
  log_success " Ticket creato con successo!"
  log_success "   ID: $TICKET_ID"
  log_success "   Codice: ${TICKET_CODE:-N/A}"
  log_success "   Link: https://my.ydea.cloud/ticket/${TICKET_ID}"
    
  # Add private note with alarm details
  log_info "Aggiunta nota privata con dettagli allarme..."
  
  NOTE_USER_ID="${ASSEGNATOA_ID:-12336}"
  NOTE_BODY=$(jq -n \
    --argjson tid "$TICKET_ID" \
    --arg desc "$NOTA_PRIVATA" \
    --argjson uid "$NOTE_USER_ID" \
    '{ticket_id: $tid, atk: {descrizione: $desc, pubblico: false, creatoda: $uid}}')
    
  if ydea_api POST "/ticket/atk" "$NOTE_BODY" >/dev/null 2>&1; then
    log_success " Nota privata aggiunta"
  else
    log_warn "  Nota privata non aggiunta (ticket comunque creato)"
  fi
    
  # Track the ticket
  track_ticket "$TICKET_ID" "${TICKET_CODE:-TK-${TICKET_ID}}" "$CMK_HOST" "$CMK_SERVICE" "$CMK_OUTPUT"
    
  # Output for CheckMK
  echo "TICKET_ID=$TICKET_ID"
  echo "TICKET_CODE=$TICKET_CODE"
  
  exit 0
else
  log_error " Errore nella creazione del ticket"
  echo "$RESPONSE" | jq '.' 2>/dev/null || echo "$RESPONSE"
  exit 1
fi
