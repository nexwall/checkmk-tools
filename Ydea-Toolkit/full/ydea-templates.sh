#!/usr/bin/env bash
set -euo pipefail

# ydea-templates.sh - Default templates for Ydea tickets
# Generate JSON for ticket creation via Ydea API

# ===== TEMPLATE INFRASTRUTTURA =====

template_server_down() {
    local hostname="$1"
    local service="${2:-N/A}"
    
    cat <<EOF
{
    "title": "[CRITICAL] Server $hostname non raggiungibile",
    "description": " Server Down Alert\n\n**Dettagli:**\n- Hostname: $hostname\n- Servizio: $service\n- Data/Ora: $(date '+%Y-%m-%d %H:%M:%S')\n- Rilevato da: Sistema di monitoraggio automatico\n\n**Impatto:**\n- [ ] Servizio completamente offline\n- [ ] Performance degradate\n- [ ] Accesso limitato\n\n**Azioni immediate:**\n1. Verificare connettività di rete\n2. Controllare status hardware\n3. Verificare log di sistema\n4. Tentare restart se appropriato\n\n**Comandi diagnostici:**\n\`\`\`bash\nping $hostname\nssh $hostname 'uptime; systemctl status'\njournalctl -xe\n\`\`\`\n\n**Priority:** CRITICAL\n**SLA:** 15 minuti",
    "priority": "critical",
    "tags": ["infrastruttura", "downtime", "server"]
}
EOF
}

template_backup_failed() {
    local backup_job="$1"
    local error_msg="${2:-Unknown error}"
    
    cat <<EOF
{
    "title": "[HIGH] Backup fallito: $backup_job",
    "description": " Backup Failure Alert\n\n**Dettagli Job:**\n- Nome job: $backup_job\n- Data/Ora: $(date '+%Y-%m-%d %H:%M:%S')\n- Errore: $error_msg\n\n**Impatto:**\n- [ ] Dati non protetti per questo ciclo\n- [ ] RPO a rischio\n- [ ] Storage backup non aggiornato\n\n**Azioni richieste:**\n1. Verificare spazio disco disponibile\n2. Controllare permessi file/directory\n3. Verificare connettività storage remoto\n4. Controllare log backup dettagliati\n5. Tentare backup manuale se possibile\n\n**Log Path:**\n\`\`\`\n/var/log/backup/$backup_job.log\n\`\`\`\n\n**Priority:** HIGH\n**SLA:** 2 ore",
    "priority": "high",
    "tags": ["backup", "storage", "dati"]
}
EOF
}

template_disk_full() {
    local hostname="$1"
    local mount_point="$2"
    local usage="$3"
    
    cat <<EOF
{
    "title": "[HIGH] Disco quasi pieno su $hostname:$mount_point",
    "description": " Disk Space Alert\n\n**Dettagli:**\n- Hostname: $hostname\n- Mount Point: $mount_point\n- Utilizzo: $usage%\n- Data/Ora: $(date '+%Y-%m-%d %H:%M:%S')\n\n**Impatto potenziale:**\n- [ ] Applicazioni potrebbero fallire\n- [ ] Log potrebbero non essere scritti\n- [ ] Database a rischio corruzione\n- [ ] Sistema potrebbe diventare instabile\n\n**Azioni immediate:**\n1. Identificare file più grandi\n2. Pulire log vecchi\n3. Rimuovere file temporanei\n4. Verificare necessità espansione\n\n**Comandi per pulizia:**\n\`\`\`bash\n# Trova file grandi\ndu -sh $mount_point/* | sort -rh | head -20\n\n# Pulisci log vecchi\nfind /var/log -type f -name '*.log' -mtime +30 -delete\n\n# Pulisci cache apt/yum\napt-get clean  # o yum clean all\n\n# Svuota cestino\nrm -rf ~/.local/share/Trash/*\n\`\`\`\n\n**Priority:** HIGH\n**SLA:** 4 ore",
    "priority": "high",
    "tags": ["storage", "disk", "infrastruttura"]
}
EOF
}

template_ssl_expiring() {
    local domain="$1"
    local days_left="$2"
    
    cat <<EOF
{
    "title": "[MEDIUM] Certificato SSL in scadenza per $domain",
    "description": " SSL Certificate Expiration Warning\n\n**Dettagli:**\n- Dominio: $domain\n- Giorni rimanenti: $days_left\n- Data scadenza: $(date -d "+${days_left} days" '+%Y-%m-%d' 2>/dev/null || echo 'N/A')\n- Data/Ora controllo: $(date '+%Y-%m-%d %H:%M:%S')\n\n**Impatto se scade:**\n- [ ] Sito web inaccessibile\n- [ ] Errori browser per utenti\n- [ ] API potrebbero fallire\n- [ ] Email potrebbero non funzionare\n\n**Azioni richieste:**\n1. Rinnovare certificato tramite CA\n2. Aggiornare configurazione web server\n3. Testare nuovo certificato\n4. Aggiornare monitoring\n\n**Rinnovo Let's Encrypt:**\n\`\`\`bash\ncertbot renew --dry-run  # test\ncertbot renew            # rinnovo effettivo\nsudo systemctl reload nginx\n\`\`\`\n\n**Verifica certificato:**\n\`\`\`bash\necho | openssl s_client -servername $domain -connect $domain:443 2>/dev/null | openssl x509 -noout -dates\n\`\`\`\n\n**Priority:** MEDIUM\n**SLA:** Prima della scadenza",
    "priority": "normal",
    "tags": ["ssl", "sicurezza", "certificati"]
}
EOF
}

# ===== TEMPLATE APPLICAZIONI =====

template_app_error_rate() {
    local app_name="$1"
    local error_rate="$2"
    local threshold="${3:-5}"
    
    cat <<EOF
{
    "title": "[HIGH] Error rate elevato per $app_name",
    "description": " Application Error Rate Alert\n\n**Dettagli:**\n- Applicazione: $app_name\n- Error rate: $error_rate%\n- Soglia: $threshold%\n- Data/Ora: $(date '+%Y-%m-%d %H:%M:%S')\n\n**Metriche:**\n- Richieste totali: [DA VERIFICARE]\n- Errori: [DA VERIFICARE]\n- Endpoint più colpiti: [DA VERIFICARE]\n\n**Azioni immediate:**\n1. Verificare log applicazione\n2. Controllare dipendenze (DB, cache, API esterne)\n3. Verificare recenti deployment\n4. Controllare risorse sistema\n5. Valutare rollback se necessario\n\n**Log da controllare:**\n\`\`\`bash\ntail -f /var/log/$app_name/error.log\ngrep -i 'error\\|exception' /var/log/$app_name/*.log | tail -50\n\`\`\`\n\n**Priority:** HIGH\n**SLA:** 1 ora",
    "priority": "high",
    "tags": ["applicazione", "errori", "performance"]
}
EOF
}

template_db_slow_queries() {
    local db_name="$1"
    local slow_count="$2"
    
    cat <<EOF
{
    "title": "[MEDIUM] Query lente rilevate su database $db_name",
    "description": " Database Performance Alert\n\n**Dettagli:**\n- Database: $db_name\n- Query lente: $slow_count\n- Periodo: ultima ora\n- Data/Ora: $(date '+%Y-%m-%d %H:%M:%S')\n\n**Impatto:**\n- [ ] Performance applicazione degradate\n- [ ] Timeout per utenti\n- [ ] Carico DB elevato\n\n**Azioni richieste:**\n1. Identificare query problematiche\n2. Verificare indici mancanti\n3. Analizzare execution plan\n4. Controllare statistiche tabelle\n5. Valutare ottimizzazioni\n\n**Diagnostica MySQL/MariaDB:**\n\`\`\`sql\n-- Query più lente\nSELECT * FROM mysql.slow_log ORDER BY query_time DESC LIMIT 10;\n\n-- Query attive\nSHOW FULL PROCESSLIST;\n\n-- Indici non usati\nSELECT * FROM sys.schema_unused_indexes;\n\`\`\`\n\n**Diagnostica PostgreSQL:**\n\`\`\`sql\n-- Query lente\nSELECT * FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10;\n\n-- Sessioni attive\nSELECT * FROM pg_stat_activity WHERE state = 'active';\n\`\`\`\n\n**Priority:** MEDIUM\n**SLA:** 4 ore",
    "priority": "normal",
    "tags": ["database", "performance", "ottimizzazione"]
}
EOF
}

# ===== TEMPLATE SICUREZZA =====

template_security_breach() {
    local incident_type="$1"
    local affected_system="$2"
    
    cat <<EOF
{
    "title": "[CRITICAL] Potenziale incidente di sicurezza: $incident_type",
    "description": " SECURITY INCIDENT ALERT\n\n**ATTENZIONE: INCIDENT RESPONSE IMMEDIATA RICHIESTA**\n\n**Dettagli:**\n- Tipo incidente: $incident_type\n- Sistema interessato: $affected_system\n- Data/Ora rilevamento: $(date '+%Y-%m-%d %H:%M:%S')\n- Severità: CRITICAL\n\n**Azioni immediate (NON MODIFICARE IL SISTEMA):**\n1.  Isolare sistema compromesso dalla rete\n2.  Preservare log e evidenze\n3.  Notificare team security\n4.  Attivare piano incident response\n5.  Documentare ogni azione\n\n**NON FARE:**\n-  Non riavviare il sistema\n-  Non modificare file\n-  Non cancellare log\n-  Non informare pubblicamente\n\n**Contatti emergenza:**\n- Security Team: [INSERIRE CONTATTO]\n- Manager: [INSERIRE CONTATTO]\n- Legal: [INSERIRE CONTATTO]\n\n**Preservazione evidenze:**\n\`\`\`bash\n# Backup log\ntar czf /tmp/incident-logs-\$(date +%s).tar.gz /var/log/\n\n# Cattura stato sistema\nps auxf > /tmp/processes.txt\nnetstat -tulpn > /tmp/connections.txt\nlsof > /tmp/openfiles.txt\n\`\`\`\n\n**Priority:** CRITICAL\n**SLA:** IMMEDIATO",
    "priority": "critical",
    "tags": ["sicurezza", "incident", "emergenza"]
}
EOF
}

template_failed_login() {
    local username="$1"
    local ip_address="$2"
    local attempts="$3"
    
    cat <<EOF
{
    "title": "[HIGH] Tentativi di login falliti per $username",
    "description": " Failed Login Attempts Alert\n\n**Dettagli:**\n- Username: $username\n- IP Address: $ip_address\n- Tentativi: $attempts\n- Periodo: ultima ora\n- Data/Ora: $(date '+%Y-%m-%d %H:%M:%S')\n\n**Azioni immediate:**\n1. Verificare se attacco brute force\n2. Controllare altri account compromessi\n3. Verificare se IP già noto\n4. Valutare blocco temporaneo IP\n5. Notificare utente se legittimo\n\n**Analisi log:**\n\`\`\`bash\n# Login falliti SSH\ngrep 'Failed password' /var/log/auth.log | tail -50\n\n# IP più attivi\ngrep 'Failed password' /var/log/auth.log | awk '{print \$(NF-3)}' | sort | uniq -c | sort -rn\n\n# Blocco IP con fail2ban\nfail2ban-client status sshd\nfail2ban-client set sshd banip $ip_address\n\`\`\`\n\n**Geolocalizzazione IP:**\n\`\`\`bash\nwhois $ip_address | grep -i country\ncurl -s ipinfo.io/$ip_address\n\`\`\`\n\n**Priority:** HIGH\n**SLA:** 2 ore",
    "priority": "high",
    "tags": ["sicurezza", "autenticazione", "brute-force"]
}
EOF
}

# ===== TEMPLATE MANUTENZIONE =====

template_planned_maintenance() {
    local system="$1"
    local date_time="$2"
    local duration="$3"
    
    cat <<EOF
{
    "title": "[PLANNED] Manutenzione programmata: $system",
    "description": " Scheduled Maintenance\n\n**Dettagli:**\n- Sistema: $system\n- Data/Ora: $date_time\n- Durata stimata: $duration\n- Creato: $(date '+%Y-%m-%d %H:%M:%S')\n\n**Lavori pianificati:**\n- [ ] Backup sistema completo\n- [ ] Update sistema operativo\n- [ ] Update applicazioni\n- [ ] Riavvio servizi\n- [ ] Testing post-manutenzione\n\n**Impatto atteso:**\n- [ ] Downtime totale\n- [ ] Performance ridotte\n- [ ] Accesso limitato\n- [ ] Nessun impatto\n\n**Checklist pre-manutenzione:**\n- [ ] Backup verificato\n- [ ] Utenti notificati\n- [ ] Change request approvato\n- [ ] Rollback plan pronto\n- [ ] Team di supporto allertato\n\n**Checklist post-manutenzione:**\n- [ ] Servizi riavviati\n- [ ] Smoke test completato\n- [ ] Monitoring verificato\n- [ ] Performance baseline ristabilita\n- [ ] Utenti notificati (completamento)\n\n**Rollback procedure:**\n\`\`\`bash\n# [INSERIRE COMANDI ROLLBACK]\n\`\`\`\n\n**Priority:** NORMAL\n**Deadline:** $date_time",
    "priority": "normal",
    "tags": ["manutenzione", "programmato", "change"]
}
EOF
}

# ===== CLI =====

case "${1:-}" in
    server-down)
        shift
        template_server_down "$@"
        ;;
    backup-failed)
        shift
        template_backup_failed "$@"
        ;;
    disk-full)
        shift
        template_disk_full "$@"
        ;;
    ssl-expiring)
        shift
        template_ssl_expiring "$@"
        ;;
    app-errors)
        shift
        template_app_error_rate "$@"
        ;;
    db-slow)
        shift
        template_db_slow_queries "$@"
        ;;
    security-breach)
        shift
        template_security_breach "$@"
        ;;
    failed-login)
        shift
        template_failed_login "$@"
        ;;
    maintenance)
        shift
        template_planned_maintenance "$@"
        ;;
    *)
        cat >&2 <<'USAGE'
 Ydea Ticket Templates

USO:
  # Template infrastruttura
  ./ydea-templates.sh server-down <hostname> [service]
  ./ydea-templates.sh backup-failed <job_name> [error_msg]
  ./ydea-templates.sh disk-full <hostname> <mount_point> <usage_%>
  ./ydea-templates.sh ssl-expiring <domain> <days_left>
  
  # Template applicazioni
  ./ydea-templates.sh app-errors <app_name> <error_rate_%> [threshold]
  ./ydea-templates.sh db-slow <db_name> <slow_query_count>
  
  # Template sicurezza
  ./ydea-templates.sh security-breach <incident_type> <affected_system>
  ./ydea-templates.sh failed-login <username> <ip_address> <attempts>
  
  # Template manutenzione
  ./ydea-templates.sh maintenance <system> <date_time> <duration>

ESEMPI:
  # Create tickets from template
  TEMPLATE=$(./ydea-templates.sh server-down "web-prod-01" "nginx")
  echo "$TEMPLATE" | jq -r '.title, .description, .priority'
  
  # Crea ticket direttamente
  ./ydea-toolkit.sh api POST /tickets "$(./ydea-templates.sh disk-full server-01 /var 92)"
  
  # Use in script
  if [[ $(df / | tail -1 | awk '{print $5}' | sed 's/%//') -gt 90 ]]; then
    TICKET=$(./ydea-templates.sh disk-full $(hostname) / 92)
    ./ydea-toolkit.sh api POST /tickets "$TICKET"
  fi
USAGE
        exit 1
        ;;
esac
