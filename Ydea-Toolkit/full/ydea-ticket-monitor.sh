#!/bin/bash
# ydea-ticket-monitor.sh - Automatic tracking ticket status monitoring
# Periodically updates the status of tickets and removes old resolved ones

set -euo pipefail

# ===== CONFIG =====
# Use absolute path to support execution via remote launcher
TOOLKIT_DIR="${YDEA_TOOLKIT_DIR:-/opt/ydea-toolkit}"
YDEA_TOOLKIT="${TOOLKIT_DIR}/ydea-toolkit.sh"
YDEA_ENV="${TOOLKIT_DIR}/.env"
TRACKING_FILE="${YDEA_TRACKING_FILE:-/var/log/ydea-tickets-tracking.json}"

# Carica variabili ambiente se disponibili
if [[ -f "$YDEA_ENV" ]]; then
    # shellcheck disable=SC1090
    source "$YDEA_ENV"
fi

# Verify that the toolkit exists
if [[ ! -x "$YDEA_TOOLKIT" ]]; then
    echo "ERROR: ydea-toolkit.sh not found or not executable: $YDEA_TOOLKIT"
    exit 1
fi

# ===== LOGGING HELPER =====
log_ticket_event() {
    local event_type="$1"
    local ticket_id="$2"
    local details="${3:-}"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [TICKET-EVENT] [$event_type] #$ticket_id $details"
}

# ===== MAIN =====
main() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ========================================"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Start tracking ticket tracking"
    
    # Mostra statistiche iniziali
    if [[ -f "$TRACKING_FILE" ]]; then
        local total_tickets open_tickets resolved_tickets
        total_tickets=$(jq '.tickets | length' "$TRACKING_FILE" 2>/dev/null || echo "0")
        open_tickets=$(jq '[.tickets[] | select(.resolved_at == null)] | length' "$TRACKING_FILE" 2>/dev/null || echo "0")
        resolved_tickets=$(jq '[.tickets[] | select(.resolved_at != null)] | length' "$TRACKING_FILE" 2>/dev/null || echo "0")
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Status: total $total_tickets ($open_tickets opened, $resolved_tickets resolved)"
    fi
    
    # Save previous state to detect changes
    declare -A previous_states
    declare -A previous_descrizioni
    declare -A previous_priorita
    declare -A previous_assegnato
    
    if [[ -f "$TRACKING_FILE" ]]; then
        while IFS='|' read -r tid stato host service codice desc prio assegnato _extra; do
            if [[ -n "$tid" ]]; then
                previous_states["$tid"]="$stato"
                previous_descrizioni["$tid"]="${desc:-}"
                previous_priorita["$tid"]="${prio:-Normale}"
                previous_assegnato["$tid"]="${assegnato:-Non assegnato}"
            fi
        done < <(jq -r '.tickets[] | select(.resolved_at == null) | "\(.ticket_id)|\(.stato)|\(.host)|\(.service)|\(.codice)|\(.descrizione_ticket // "")|\(.priorita // "Normale")|\(.assegnatoA // "Non assegnato")"' "$TRACKING_FILE" 2>/dev/null || true)
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Updating ticket statuses..."
    
    # Update ticket statuses
    "$YDEA_TOOLKIT" update-tracking
    
    # Detect and log changes by reading CURRENT from the API instead of tracking
    # Ottieni dati aggiornati dall'API
    local api_data
    api_data=$("$YDEA_TOOLKIT" api GET "/tickets?limit=100" 2>/dev/null || echo '{"objs":[]}')
    
    if [[ -f "$TRACKING_FILE" ]]; then
        # For each ticket tracked, compare to the API data
        while IFS='|' read -r tid stato host service codice; do
            if [[ -z "$tid" ]]; then continue; fi
            
            # Ottieni prev values dagli array
            prev_stato="${previous_states[$tid]:-NUOVO}"
            prev_desc="${previous_descrizioni[$tid]:-}"
            prev_prio="${previous_priorita[$tid]:-Normale}"
            prev_assegnato="${previous_assegnato[$tid]:-Non assegnato}"
            
            # Ottieni current values dall'API
            local ticket_api_data
            ticket_api_data=$(echo "$api_data" | jq --arg tid "$tid" '.objs[] | select(.id == ($tid|tonumber))')
            
            if [[ -z "$ticket_api_data" ]]; then
                # Ticket not found in API, use values ​​from tracking
                continue
            fi
            
            current_stato=$(echo "$ticket_api_data" | jq -r '.stato // "Sconosciuto"')
            current_desc=$(echo "$ticket_api_data" | jq -r '.descrizione // ""')
            current_prio=$(echo "$ticket_api_data" | jq -r '.priorita // "Normale"')
            current_assegnato=$(echo "$ticket_api_data" | jq -r 'if .assegnatoA | type == "object" then (if (.assegnatoA | length) > 0 then [.assegnatoA | to_entries[].value] | join(", ") else "Non assegnato" end) elif .assegnatoA then .assegnatoA else "Non assegnato" end')
            
            # Rileva modifica descrizione
            if [[ -n "$prev_desc" && "$current_desc" != "$prev_desc" ]]; then
                log_ticket_event "DESCRIZIONE-MODIFICATA" "$tid" "[$codice] Host: $host, Service: $service"
            fi
            
            # Rileva modifica priorita
            if [[ "$current_prio" != "$prev_prio" ]]; then
                log_ticket_event "PRIORITA-MODIFICATA" "$tid" "[$codice] $prev_prio → $current_prio - Host: $host, Service: $service"
            fi
            
            # Rileva cambio assegnazione
            if [[ "$current_assegnato" != "$prev_assegnato" ]]; then
                log_ticket_event "ASSEGNAZIONE-MODIFICATA" "$tid" "[$codice] $prev_assegnato → $current_assegnato - Host: $host, Service: $service"
            fi
            
            # Se ticket è diventato risolto
            if [[ "$current_stato" =~ ^(Effettuato|Chiuso|Completato|Risolto)$ ]] && [[ "$prev_stato" != "$current_stato" ]]; then
                log_ticket_event "RISOLTO" "$tid" "[$codice] Host: $host, Service: $service, Stato: $prev_stato → $current_stato"
            # If the state has changed but is not resolved
            elif [[ -n "$prev_stato" && "$prev_stato" != "NUOVO" && "$prev_stato" != "$current_stato" ]]; then
                log_ticket_event "STATO-CAMBIATO" "$tid" "[$codice] $prev_stato → $current_stato (Host: $host, Service: $service)"
            fi
        done < <(jq -r '.tickets[] | select(.resolved_at == null) | "\(.ticket_id)|\(.stato)|\(.host)|\(.service)|\(.codice)"' "$TRACKING_FILE" 2>/dev/null || true)
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Status update complete"
    
    # Clean old resolved tickets (every 6 hours, check if last clean > 6h ago)
    local cleanup_marker="/tmp/ydea_last_cleanup"
    local now
    now=$(date +%s)
    local last_cleanup=0
    
    if [[ -f "$cleanup_marker" ]]; then
        last_cleanup=$(cat "$cleanup_marker")
    fi
    
    local hours_since_cleanup=$(( (now - last_cleanup) / 3600 ))
    
    if [[ $hours_since_cleanup -ge 6 ]]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')]  Eseguo pulizia ticket risolti vecchi..."
        "$YDEA_TOOLKIT" cleanup-tracking
        echo "$now" > "$cleanup_marker"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleanup not needed (next between $((6 - hours_since_cleanup))h)"
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Tracking completed"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ========================================"
}

# Esegui main
main
exit 0
