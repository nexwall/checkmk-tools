#!/usr/bin/env bash
set -euo pipefail

# ydea-monitoring-integration.sh
# Integration between monitoring systems and Ydea for automatic ticket creation

TOOLKIT="./ydea-toolkit.sh"

# Configuration
ALERT_THRESHOLD_CPU=90
ALERT_THRESHOLD_MEM=85
ALERT_THRESHOLD_DISK=90

# Files to track tickets already created (avoids duplicates)
TICKET_CACHE="/tmp/ydea_tickets_cache.json"

# ===== UTILITY =====

log_info() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ℹ  $*"
}

log_warn() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')]   $*"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')]  $*" >&2
}

log_success() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')]  $*"
}

# Inizializza cache
init_cache() {
    [[ -f "$TICKET_CACHE" ]] || echo '{}' > "$TICKET_CACHE"
}

# Check if there is already an open ticket for this alert
ticket_exists() {
    local alert_key="$1"
    init_cache
    jq -e --arg key "$alert_key" '.[$key] != null' "$TICKET_CACHE" >/dev/null 2>&1
}

# Save tickets in cache
save_ticket_cache() {
    local alert_key="$1"
    local ticket_id="$2"
    init_cache
    jq --arg key "$alert_key" --arg id "$ticket_id" --arg ts "$(date -u +%s)" \
        '.[$key] = {ticket_id: $id, created_at: $ts}' \
        "$TICKET_CACHE" > "${TICKET_CACHE}.tmp" && mv "${TICKET_CACHE}.tmp" "$TICKET_CACHE"
}

# Remove ticket from cache (when closed)
remove_ticket_cache() {
    local alert_key="$1"
    init_cache
    jq --arg key "$alert_key" 'del(.[$key])' \
        "$TICKET_CACHE" > "${TICKET_CACHE}.tmp" && mv "${TICKET_CACHE}.tmp" "$TICKET_CACHE"
}

# Clear cache from old tickets (>24h)
cleanup_cache() {
    init_cache
    local now
    now=$(date -u +%s)
    local max_age=$((24 * 3600))
    
    jq --arg now "$now" --arg max "$max_age" '
        to_entries | 
        map(select(($now | tonumber) - (.value.created_at | tonumber) < ($max | tonumber))) | 
        from_entries
    ' "$TICKET_CACHE" > "${TICKET_CACHE}.tmp" && mv "${TICKET_CACHE}.tmp" "$TICKET_CACHE"
}

# ===== MONITORING FUNCTIONS =====

# Monitora CPU
check_cpu_usage() {
    local hostname="${1:-$(hostname)}"
    local cpu_usage
    
    # Get CPU Usage (1 minute average)
    cpu_usage=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
    cpu_usage=${cpu_usage%.*}  # Rimuovi decimali
    
    if [[ $cpu_usage -gt $ALERT_THRESHOLD_CPU ]]; then
        local alert_key="cpu_${hostname}"
        
        if ! ticket_exists "$alert_key"; then
            log_warn "CPU usage elevato: ${cpu_usage}%"
            
            local template
            template=$(cat <<EOF
{
    "title": "[HIGH] CPU usage elevato su $hostname",
    "description": " CPU Alert\n\n**Dettagli:**\n- Hostname: $hostname\n- CPU Usage: ${cpu_usage}%\n- Soglia: ${ALERT_THRESHOLD_CPU}%\n- Data/Ora: $(date '+%Y-%m-%d %H:%M:%S')\n\n**Azioni immediate:**\n1. Identificare processi che consumano più CPU\n2. Verificare se è un picco temporaneo o persistente\n3. Controllare se ci sono processi zombie\n4. Valutare scaling verticale\n\n**Diagnostica:**\n\`\`\`bash\ntop -bn1 | head -20\nps auxf --sort=-%cpu | head -10\n\`\`\`",
    "priority": "high",
    "tags": ["cpu", "performance", "infrastruttura"]
}
EOF
)
            
            local ticket_id
            ticket_id=$("$TOOLKIT" api POST /tickets "$template" | jq -r '.id')
            
            if [[ -n "$ticket_id" && "$ticket_id" != "null" ]]; then
                save_ticket_cache "$alert_key" "$ticket_id"
                log_success "Ticket creato: #$ticket_id"
            else
                log_error "Creazione ticket fallita"
            fi
        fi
    else
        # CPU OK - rimuovi ticket se esistente
        local alert_key="cpu_${hostname}"
        if ticket_exists "$alert_key"; then
            log_info "CPU tornata normale (${cpu_usage}%), rimuovo ticket dalla cache"
            remove_ticket_cache "$alert_key"
        fi
    fi
}

# Monitor memory
check_memory_usage() {
    local hostname="${1:-$(hostname)}"
    local mem_usage
    
    # Get memory usage
    mem_usage=$(free | grep Mem | awk '{printf "%.0f", $3/$2 * 100.0}')
    
    if [[ $mem_usage -gt $ALERT_THRESHOLD_MEM ]]; then
        local alert_key="mem_${hostname}"
        
        if ! ticket_exists "$alert_key"; then
            log_warn "Memory usage elevato: ${mem_usage}%"
            
            local template
            template=$(cat <<EOF
{
    "title": "[HIGH] Memory usage elevato su $hostname",
    "description": " Memory Alert\n\n**Dettagli:**\n- Hostname: $hostname\n- Memory Usage: ${mem_usage}%\n- Soglia: ${ALERT_THRESHOLD_MEM}%\n- Data/Ora: $(date '+%Y-%m-%d %H:%M:%S')\n\n**Azioni immediate:**\n1. Identificare processi che consumano più memoria\n2. Verificare memory leaks\n3. Controllare cache e buffer\n4. Valutare se aumentare RAM\n\n**Diagnostica:**\n\`\`\`bash\nfree -h\nps auxf --sort=-%mem | head -10\nsudo slabtop\n\`\`\`",
    "priority": "high",
    "tags": ["memoria", "performance", "infrastruttura"]
}
EOF
)
            
            local ticket_id
            ticket_id=$("$TOOLKIT" api POST /tickets "$template" | jq -r '.id')
            
            if [[ -n "$ticket_id" && "$ticket_id" != "null" ]]; then
                save_ticket_cache "$alert_key" "$ticket_id"
                log_success "Ticket creato: #$ticket_id"
            else
                log_error "Creazione ticket fallita"
            fi
        fi
    else
        # Memory OK
        local alert_key="mem_${hostname}"
        if ticket_exists "$alert_key"; then
            log_info "Memoria tornata normale (${mem_usage}%), rimuovo ticket dalla cache"
            remove_ticket_cache "$alert_key"
        fi
    fi
}

# Monitor disk
check_disk_usage() {
    local hostname="${1:-$(hostname)}"
    local mount_point="${2:-/}"
    
    local disk_usage
    disk_usage=$(df "$mount_point" | tail -1 | awk '{print $5}' | sed 's/%//')
    
    if [[ $disk_usage -gt $ALERT_THRESHOLD_DISK ]]; then
        local alert_key="disk_${hostname}_${mount_point//\//_}"
        
        if ! ticket_exists "$alert_key"; then
            log_warn "Disk usage elevato su ${mount_point}: ${disk_usage}%"
            
            local template
            template=$(./ydea-templates.sh disk-full "$hostname" "$mount_point" "$disk_usage")
            
            local ticket_id
            ticket_id=$("$TOOLKIT" api POST /tickets "$template" | jq -r '.id')
            
            if [[ -n "$ticket_id" && "$ticket_id" != "null" ]]; then
                save_ticket_cache "$alert_key" "$ticket_id"
                log_success "Ticket creato: #$ticket_id"
            else
                log_error "Creazione ticket fallita"
            fi
        fi
    else
        # Disk OK
        local alert_key="disk_${hostname}_${mount_point//\//_}"
        if ticket_exists "$alert_key"; then
            log_info "Disco ${mount_point} tornato normale (${disk_usage}%), rimuovo ticket dalla cache"
            remove_ticket_cache "$alert_key"
        fi
    fi
}

# Monitor systemd service
check_service_status() {
    local service_name="$1"
    local hostname="${2:-$(hostname)}"
    
    if ! systemctl is-active --quiet "$service_name"; then
        local alert_key="service_${hostname}_${service_name}"
        
        if ! ticket_exists "$alert_key"; then
            log_error "Servizio $service_name non attivo"
            
            local template
            template=$(cat <<EOF
{
    "title": "[CRITICAL] Servizio $service_name non attivo su $hostname",
    "description": " Service Down Alert\n\n**Dettagli:**\n- Hostname: $hostname\n- Servizio: $service_name\n- Stato: $(systemctl is-active "$service_name" 2>&1)\n- Data/Ora: $(date '+%Y-%m-%d %H:%M:%S')\n\n**Azioni immediate:**\n1. Tentare restart servizio\n2. Controllare log servizio\n3. Verificare dipendenze\n4. Controllare configurazione\n\n**Diagnostica:**\n\`\`\`bash\nsystemctl status $service_name\njournalctl -xeu $service_name --since '10 minutes ago'\nsudo systemctl restart $service_name\n\`\`\`",
    "priority": "critical",
    "tags": ["servizio", "downtime", "infrastruttura"]
}
EOF
)
            
            local ticket_id
            ticket_id=$("$TOOLKIT" api POST /tickets "$template" | jq -r '.id')
            
            if [[ -n "$ticket_id" && "$ticket_id" != "null" ]]; then
                save_ticket_cache "$alert_key" "$ticket_id"
                log_success "Ticket creato: #$ticket_id"
            else
                log_error "Creazione ticket fallita"
            fi
        fi
    else
        # Service OK
        local alert_key="service_${hostname}_${service_name}"
        if ticket_exists "$alert_key"; then
            log_info "Servizio $service_name tornato attivo, rimuovo ticket dalla cache"
            remove_ticket_cache "$alert_key"
        fi
    fi
}

# ===== MAIN =====

main() {
    log_info "Inizio controlli monitoraggio"
    
    # Pulizia cache
    cleanup_cache
    
    # Default controls
    check_cpu_usage
    check_memory_usage
    check_disk_usage
    
    # Critical service checks (optional)
    # check_service_status "nginx"
    # check_service_status "mysql"
    # check_service_status "postgresql"
    
    log_success "Controlli completati"
}

# CLI
case "${1:-main}" in
    cpu)
        shift
        check_cpu_usage "$@"
        ;;
    memory|mem)
        shift
        check_memory_usage "$@"
        ;;
    disk)
        shift
        check_disk_usage "$@"
        ;;
    service)
        shift
        check_service_status "$@"
        ;;
    cleanup)
        cleanup_cache
        log_success "Cache pulita"
        ;;
    main|*)
        main
        ;;
esac
