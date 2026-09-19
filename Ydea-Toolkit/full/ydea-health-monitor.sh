#!/bin/bash
# ydea-health-monitor.sh - Monitoraggio disponibilità Ydea API
# Check every 15 minutes if Ydea is reachable and notify via email if down

set -euo pipefail

# ===== CONFIG =====
# Use absolute path to support execution via remote launcher
TOOLKIT_DIR="${YDEA_TOOLKIT_DIR:-/opt/ydea-toolkit}"
YDEA_TOOLKIT="${TOOLKIT_DIR}/ydea-toolkit.sh"
YDEA_ENV="${TOOLKIT_DIR}/.env"
STATE_FILE="/tmp/ydea_health_state.json"
MAIL_SCRIPT="/omd/sites/monitoring/local/share/check_mk/notifications/mail_ydea_down"

# Email recipient for notifications
ALERT_EMAIL="${YDEA_ALERT_EMAIL:-massimo.palazzetti@nethesis.it}"

# Threshold of consecutive errors before reporting (to avoid false positives)
FAILURE_THRESHOLD="${YDEA_FAILURE_THRESHOLD:-3}"

# ===== UTILITY =====
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
}

# Initialize state if it does not exist
init_state() {
    if [[ ! -f "$STATE_FILE" ]]; then
        echo '{"status":"unknown","last_check":0,"consecutive_failures":0,"last_failure":"","notified":false}' > "$STATE_FILE"
    fi
}

# Read current status
get_state() {
    local field="$1"
    jq -r ".${field} // empty" "$STATE_FILE" 2>/dev/null || echo ""
}

# Update status
update_state() {
    local status="$1"
    local now
    now=$(date -u +%s)
    local consecutive_failures="${2:-0}"
    local notified="${3:-false}"
    
    jq -n \
        --arg status "$status" \
        --arg now "$now" \
        --arg failures "$consecutive_failures" \
        --arg notified "$notified" \
        '{status: $status, last_check: ($now|tonumber), consecutive_failures: ($failures|tonumber), notified: ($notified == "true"), last_failure: (if $status == "down" then $now else "" end)}' \
        > "$STATE_FILE"
}

# ===== NOTIFICA EMAIL =====
send_email_alert() {
    local subject="$1"
    local body="$2"
    
    log "Invio notifica email a $ALERT_EMAIL"
    
    # Use mail_ydea_down script if it exists, otherwise fallback to mail command
    if [[ -x "$MAIL_SCRIPT" ]]; then
        # Export variables for notification script
        export NOTIFY_HOSTNAME="ydea.cloud"
        export NOTIFY_HOSTADDRESS="my.ydea.cloud"
        export NOTIFY_WHAT="HOST"
        export NOTIFY_HOSTSTATE="DOWN"
        export NOTIFY_HOSTOUTPUT="Ydea API non raggiungibile - Impossibile effettuare login"
        export NOTIFY_CONTACTEMAIL="$ALERT_EMAIL"
        export NOTIFY_DATE="$(date '+%Y-%m-%d')"
        export NOTIFY_SHORTDATETIME="$(date '+%Y-%m-%d %H:%M:%S')"
        
        "$MAIL_SCRIPT" 2>&1 | log
    else
        # Fallback: usa comando mail se disponibile
        if command -v mail >/dev/null 2>&1; then
            echo "$body" | mail -s "$subject" "$ALERT_EMAIL"
        else
            log_error "Né $MAIL_SCRIPT né comando 'mail' disponibili. Impossibile inviare notifica."
            return 1
        fi
    fi
}

# ===== TEST YDEA =====
test_ydea_login() {
    # Carica ambiente
    if [[ ! -f "$YDEA_ENV" ]]; then
        log_error "File .env non trovato: $YDEA_ENV"
        return 1
    fi
    
    source "$YDEA_ENV"
    
    if [[ ! -x "$YDEA_TOOLKIT" ]]; then
        log_error "Script ydea-toolkit.sh non trovato o non eseguibile: $YDEA_TOOLKIT"
        return 1
    fi
    
    # Test login (with timeout)
    local result
    if result=$(timeout 30s "$YDEA_TOOLKIT" login 2>&1); then
        return 0
    else
        log_error "Login fallito: $result"
        return 1
    fi
}

# ===== MAIN LOGIC =====
main() {
    init_state
    
    local current_status
    current_status=$(get_state "status")
    local consecutive_failures
    consecutive_failures=$(get_state "consecutive_failures")
    consecutive_failures=${consecutive_failures:-0}
    local was_notified
    was_notified=$(get_state "notified")
    
    log "Controllo disponibilità Ydea API..."
    
    if test_ydea_login; then
        # ===== YDEA UP =====
        log " Ydea API raggiungibile"
        
        # Se era down e abbiamo notificato, invia recovery email
        if [[ "$current_status" == "down" && "$was_notified" == "true" ]]; then
            log "Ydea tornato online, invio notifica di recovery"
            
            local subject=" [RECOVERY] Ydea API - Servizio Ripristinato"
            local body="Il servizio Ydea API è tornato online.

Dettagli:
- Data/Ora recovery: $(date '+%Y-%m-%d %H:%M:%S')
- Durata down: Da controllare in logs
- Ultimo check fallito: $(date -d "@$(get_state 'last_failure')" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo 'N/A')

Il servizio di ticketing è nuovamente operativo.

---
Monitor automatico Ydea Health"
            
            send_email_alert "$subject" "$body"
        fi
        
        # Reset status
        update_state "up" 0 "false"
    else
        # ===== YDEA DOWN =====
        consecutive_failures=$((consecutive_failures + 1))
        log_error " Ydea API non raggiungibile (tentativi falliti: $consecutive_failures/$FAILURE_THRESHOLD)"
        
        # Notify only if we reach the threshold and have not already notified
        if [[ $consecutive_failures -ge $FAILURE_THRESHOLD && "$was_notified" != "true" ]]; then
            log "Soglia di errori raggiunta, invio notifica"
            
            local subject=" [ALERT] Ydea API - Servizio Non Raggiungibile"
            local body="ATTENZIONE: Il servizio Ydea API non è raggiungibile.

Dettagli:
- Data/Ora rilevazione: $(date '+%Y-%m-%d %H:%M:%S')
- Tentativi falliti consecutivi: $consecutive_failures
- URL: https://my.ydea.cloud
- Endpoint: /app_api_v2/login

Impatto:
- Sistema di ticketing non disponibile
- Alert CheckMK NON verranno convertiti in ticket Ydea
- Creazione manuale ticket non possibile

Azioni richieste:
1. Verificare status servizio Ydea (https://status.ydea.cloud se disponibile)
2. Controllare connettività di rete
3. Verificare credenziali API
4. Contattare supporto Ydea se necessario

Il sistema continuerà a monitorare e invierà notifica quando il servizio sarà ripristinato.

---
Monitor automatico Ydea Health
Check ogni 15 minuti"
            
            if send_email_alert "$subject" "$body"; then
                log " Notifica inviata con successo"
                update_state "down" "$consecutive_failures" "true"
            else
                log_error "Errore invio notifica"
                update_state "down" "$consecutive_failures" "false"
            fi
        else
            # Only update the counter
            update_state "down" "$consecutive_failures" "$was_notified"
        fi
    fi
}

# Esegui main
main
exit 0
