#!/bin/bash

###############################################################################
# Script: setup-auto-updates.sh
# Description: Configure automatic system updates via crontab
# Author: Generated for checkmk-tools
# Data: 2026-01-12
###############################################################################

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colorful messages
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check root permissions
if [ "$EUID" -ne 0 ]; then
    print_error "Questo script deve essere eseguito come root o con sudo"
    exit 1
fi

# Banner
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║    Configurazione Aggiornamenti Automatici Sistema            ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Command to execute
UPDATE_COMMAND="sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove -y"
LOG_FILE="/var/log/auto-updates.log"

print_info "Comando che verrà eseguito:"
echo -e "${GREEN}${UPDATE_COMMAND}${NC}"
echo ""

# Interactive menu for frequency
echo -e "${YELLOW}Seleziona la frequenza degli aggiornamenti automatici:${NC}"
echo ""
echo "1) Daily - Every day at 03:00"
echo "2) Weekly - Every Sunday at 03:00"
echo "3) Monthly - The first day of the month at 03:00"
echo "  4) Personalizzato - Specifica orario e frequenza custom"
echo "  5) Annulla"
echo ""

read -p "Scelta [1-5]: " choice

case $choice in
    1)
        CRON_SCHEDULE="0 3 * * *"
        DESCRIPTION="Giornaliero alle 03:00"
        ;;
    2)
        CRON_SCHEDULE="0 3 * * 0"
        DESCRIPTION="Settimanale (domenica) alle 03:00"
        ;;
    3)
        CRON_SCHEDULE="0 3 1 * *"
        DESCRIPTION="Mensile (1° del mese) alle 03:00"
        ;;
    4)
        echo ""
        print_info "Inserisci la pianificazione cron personalizzata"
        echo "Format: minute hour day month dayweek"
        echo "Example: 0 3 * * * (every day at 3:00)"
        echo "Example: 30 2 * * 1 (every Monday at 2.30am)"
        echo ""
        read -p "Inserisci la pianificazione cron: " CRON_SCHEDULE
        DESCRIPTION="Personalizzato: $CRON_SCHEDULE"
        
        # Basic validation of cron syntax
        if ! [[ $CRON_SCHEDULE =~ ^[0-9\*\,\-\/]+[[:space:]]+[0-9\*\,\-\/]+[[:space:]]+[0-9\*\,\-\/]+[[:space:]]+[0-9\*\,\-\/]+[[:space:]]+[0-9\*\,\-\/]+$ ]]; then
            print_error "Formato cron non valido"
            exit 1
        fi
        ;;
    5)
        print_warning "Operazione annullata"
        exit 0
        ;;
    *)
        print_error "Scelta non valida"
        exit 1
        ;;
esac

echo ""
print_info "Configurazione selezionata: ${DESCRIPTION}"

# Chiedi conferma sull'orario
read -p "Vuoi modificare l'orario? [s/N]: " modify_time
if [[ $modify_time =~ ^[Ss]$ ]]; then
    echo ""
    read -p "Inserisci l'ora (0-23): " hour
    read -p "Inserisci i minuti (0-59): " minute
    
    # Validazione
    if ! [[ $hour =~ ^[0-9]+$ ]] || [ "$hour" -lt 0 ] || [ "$hour" -gt 23 ]; then
        print_error "Ora non valida"
        exit 1
    fi
    
    if ! [[ $minute =~ ^[0-9]+$ ]] || [ "$minute" -lt 0 ] || [ "$minute" -gt 59 ]; then
        print_error "Minuti non validi"
        exit 1
    fi
    
    # Replace minute and hour in the schedule
    CRON_SCHEDULE="$minute $hour $(echo $CRON_SCHEDULE | cut -d' ' -f3-)"
    print_info "Nuova pianificazione: $CRON_SCHEDULE"
fi

# Create the complete command with logging
CRON_COMMAND="$CRON_SCHEDULE $UPDATE_COMMAND >> $LOG_FILE 2>&1"
CRON_ENTRY="$CRON_SCHEDULE (echo \"[\$(date)] Starting system updates\" && $UPDATE_COMMAND && echo \"[\$(date)] Updates completed successfully\") >> $LOG_FILE 2>&1"

echo ""
print_info "Entry crontab che verrà aggiunta:"
echo -e "${GREEN}${CRON_ENTRY}${NC}"
echo ""

# Conferma finale
read -p "Confermi l'aggiunta al crontab? [s/N]: " confirm
if [[ ! $confirm =~ ^[Ss]$ ]]; then
    print_warning "Operazione annullata"
    exit 0
fi

# Backup the current crontab
print_info "Creazione backup del crontab corrente..."
BACKUP_DIR="/root/crontab_backups"
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/crontab_backup_$(date +%Y%m%d_%H%M%S).txt"
crontab -l > "$BACKUP_FILE" 2>/dev/null || echo "# New chrontab" > "$BACKUP_FILE"
print_success "Backup salvato in: $BACKUP_FILE"

# Check if the entry already exists
if crontab -l 2>/dev/null | grep -q "apt update.*apt full-upgrade.*apt autoremove"; then
    print_warning "Trovata entry simile già presente nel crontab"
    read -p "Vuoi rimuovere le entry esistenti e aggiungerne una nuova? [s/N]: " remove_old
    
    if [[ $remove_old =~ ^[Ss]$ ]]; then
        # Remove old entries
        crontab -l 2>/dev/null | grep -v "apt update.*apt full-upgrade.*apt autoremove" | crontab -
        print_success "Vecchie entry rimosse"
    else
        print_warning "Le vecchie entry sono state mantenute. L'aggiornamento verrà eseguito più volte."
    fi
fi

# Add the new entry to the crontab
print_info "Aggiunta nuova entry al crontab..."
(crontab -l 2>/dev/null; echo "# Auto-updates: $DESCRIPTION"; echo "$CRON_ENTRY") | crontab -
print_success "Entry aggiunta con successo!"

# Create log file if it does not exist
touch "$LOG_FILE"
chmod 644 "$LOG_FILE"
print_info "File di log creato: $LOG_FILE"

# Show the current crontab
echo ""
print_info "Crontab corrente:"
echo -e "${BLUE}----------------------------------------${NC}"
crontab -l
echo -e "${BLUE}----------------------------------------${NC}"

# Riepilogo finale
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                  Configurazione Completata                     ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
print_success "Frequenza: $DESCRIPTION"
print_success "Log file: $LOG_FILE"
print_success "Backup crontab: $BACKUP_FILE"
echo ""
print_info "Per monitorare gli aggiornamenti eseguiti:"
echo -e "  ${YELLOW}tail -f $LOG_FILE${NC}"
echo ""
print_info "Per rimuovere gli aggiornamenti automatici:"
echo -e "  ${YELLOW}crontab -e${NC}  # e rimuovi la riga corrispondente"
echo ""
print_info "Per testare subito l'aggiornamento (senza aspettare la schedulazione):"
echo -e "  ${YELLOW}$UPDATE_COMMAND${NC}"
echo ""

exit 0
