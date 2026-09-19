#!/usr/bin/env bash
# install-ydea-checkmk-integration.sh
# Quick installation script CheckMK integration → Ydea
set -euo pipefail

# Output colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
CHECKMK_SITE="${CHECKMK_SITE:-monitoring}"
CHECKMK_NOTIFY_DIR="/omd/sites/${CHECKMK_SITE}/local/share/check_mk/notifications"
YDEA_TOOLKIT_DIR="${YDEA_TOOLKIT_DIR:-/opt/ydea-toolkit}"
NOTIFY_BIN_DIR="/usr/local/bin/notify-checkmk"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║      Installazione Integrazione CheckMK → Ydea           ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Funzioni utility
info() { echo -e "${BLUE}ℹ  $*${NC}"; }
success() { echo -e "${GREEN} $*${NC}"; }
warn() { echo -e "${YELLOW}  $*${NC}"; }
error() { echo -e "${RED} $*${NC}" >&2; }

check_root() {
  if [[ $EUID -ne 0 ]]; then
    error "Questo script deve essere eseguito come root"
    echo "  Usa: sudo $0"
    exit 1
  fi
}

check_checkmk() {
  if [[ ! -d "/omd/sites/${CHECKMK_SITE}" ]]; then
    error "Sito CheckMK '${CHECKMK_SITE}' non trovato"
    echo "Check site name or use: export CHECKMK_SITE='site_name'"
    exit 1
  fi
  success "CheckMK sito '${CHECKMK_SITE}' trovato"
}

check_ydea_toolkit() {
  if [[ ! -d "$YDEA_TOOLKIT_DIR" ]]; then
    warn "Directory Ydea Toolkit non trovata: $YDEA_TOOLKIT_DIR"
    read -p "Vuoi crearla? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
      mkdir -p "$YDEA_TOOLKIT_DIR"
      success "Directory creata: $YDEA_TOOLKIT_DIR"
    else
      error "Impossibile continuare senza Ydea Toolkit"
      exit 1
    fi
  else
    success "Ydea Toolkit trovato: $YDEA_TOOLKIT_DIR"
  fi
}

install_scripts() {
  info "Installazione script di notifica CheckMK..."
  
  # Determine script-notify-checkmk path (supports both normal and sparse-checkout structure)
  local NOTIFY_SCRIPT_DIR
  if [[ -d "${SCRIPT_DIR}/script-notify-checkmk" ]]; then
    NOTIFY_SCRIPT_DIR="${SCRIPT_DIR}/script-notify-checkmk"
  elif [[ -d "$(dirname "${SCRIPT_DIR}")/script-notify-checkmk" ]]; then
    NOTIFY_SCRIPT_DIR="$(dirname "${SCRIPT_DIR}")/script-notify-checkmk"
  else
    error "Cartella script-notify-checkmk non trovata"
    echo "  Provato: ${SCRIPT_DIR}/script-notify-checkmk"
    echo "  Provato: $(dirname "${SCRIPT_DIR}")/script-notify-checkmk"
    exit 1
  fi
  
  info "Usando script da: ${NOTIFY_SCRIPT_DIR}"
  
  # Copy of main Ydea notifiers (with dedicated person ID)
  for notifier in ydea_la ydea_ag; do
    if [[ -f "${NOTIFY_SCRIPT_DIR}/${notifier}" ]]; then
      cp "${NOTIFY_SCRIPT_DIR}/${notifier}" "$CHECKMK_NOTIFY_DIR/"
      chmod +x "${CHECKMK_NOTIFY_DIR}/${notifier}"
      success "${notifier} installato"
    else
      error "File ${notifier} non trovato in ${NOTIFY_SCRIPT_DIR}/"
      exit 1
    fi
  done

  # Copia eventuale notifier legacy (opzionale)
  if [[ -f "${NOTIFY_SCRIPT_DIR}/ydea_realip" ]]; then
    cp "${NOTIFY_SCRIPT_DIR}/ydea_realip" "$CHECKMK_NOTIFY_DIR/"
    chmod +x "${CHECKMK_NOTIFY_DIR}/ydea_realip"
    warn "ydea_realip installato (legacy opzionale)"
  fi
  
  # Copia mail_ydea_down
  if [[ -f "${NOTIFY_SCRIPT_DIR}/mail_ydea_down" ]]; then
    cp "${NOTIFY_SCRIPT_DIR}/mail_ydea_down" "$CHECKMK_NOTIFY_DIR/"
    chmod +x "${CHECKMK_NOTIFY_DIR}/mail_ydea_down"
    success "mail_ydea_down installato"
  else
    warn "File mail_ydea_down non trovato (opzionale)"
  fi

  # Copia cache validator (obbligatorio)
  local CACHE_VALIDATOR_SRC=""
  if [[ -f "${NOTIFY_SCRIPT_DIR}/ydea_cache_validator.py" ]]; then
    CACHE_VALIDATOR_SRC="${NOTIFY_SCRIPT_DIR}/ydea_cache_validator.py"
  elif [[ -f "${NOTIFY_SCRIPT_DIR}/ydea_cache_validator" ]]; then
    CACHE_VALIDATOR_SRC="${NOTIFY_SCRIPT_DIR}/ydea_cache_validator"
  else
    error "File richiesto ydea_cache_validator.py non trovato in ${NOTIFY_SCRIPT_DIR}/"
    exit 1
  fi

  mkdir -p "$NOTIFY_BIN_DIR"
  cp "$CACHE_VALIDATOR_SRC" "${NOTIFY_BIN_DIR}/ydea_cache_validator.py"
  chmod +x "${NOTIFY_BIN_DIR}/ydea_cache_validator.py"
  success "ydea_cache_validator.py installato in ${NOTIFY_BIN_DIR}"
  
  # Copy health monitor (supports both relative and absolute path)
  info "Installazione health monitor..."
  local HEALTH_MONITOR
  if [[ -f "${SCRIPT_DIR}/ydea-health-monitor.sh" ]]; then
    HEALTH_MONITOR="${SCRIPT_DIR}/ydea-health-monitor.sh"
  elif [[ -f "${SCRIPT_DIR}/Ydea-Toolkit/ydea-health-monitor.sh" ]]; then
    HEALTH_MONITOR="${SCRIPT_DIR}/Ydea-Toolkit/ydea-health-monitor.sh"
  else
    error "File ydea-health-monitor.sh non trovato"
    exit 1
  fi
  
  cp "$HEALTH_MONITOR" "$YDEA_TOOLKIT_DIR/"
  chmod +x "${YDEA_TOOLKIT_DIR}/ydea-health-monitor.sh"
  success "ydea-health-monitor.sh installato"
}

setup_env() {
  info "Configurazione file .env..."
  
  local env_file="${YDEA_TOOLKIT_DIR}/.env"
  
  if [[ -f "$env_file" ]]; then
    warn "File .env già esistente, salvo backup"
    cp "$env_file" "${env_file}.backup.$(date +%Y%m%d_%H%M%S)"
  fi
  
  # Copia .env template se esiste (supporta più path)
  local env_template=""
  local env_candidates=(
    "${SCRIPT_DIR}/.env"
    "${SCRIPT_DIR}/.env.la"
    "${SCRIPT_DIR}/.env.ag"
    "${SCRIPT_DIR}/../.env"
    "${SCRIPT_DIR}/../.env.la"
    "${SCRIPT_DIR}/../.env.ag"
    "${SCRIPT_DIR}/Ydea-Toolkit/.env"
  )

  for candidate in "${env_candidates[@]}"; do
    if [[ -f "$candidate" ]]; then
      env_template="$candidate"
      break
    fi
  done

  if [[ -n "$env_template" ]]; then
    cp "$env_template" "$env_file"
    success "Template .env copiato da: $env_template"
  else
    warn "Nessun template .env trovato, creo file vuoto: $env_file"
    : > "$env_file"
  fi

  # Correct permissions and ownership for all .env files
  # The CheckMK site (user monitoring) must be able to read them
  for env_f in "${YDEA_TOOLKIT_DIR}/.env" "${YDEA_TOOLKIT_DIR}/.env.la" "${YDEA_TOOLKIT_DIR}/.env.ag"; do
    if [[ -f "$env_f" ]]; then
      chmod 640 "$env_f"
      chown "${CHECKMK_SITE}:${CHECKMK_SITE}" "$env_f" 2>/dev/null || \
        chown root:root "$env_f" 2>/dev/null || true
      success "Permessi corretti su $(basename $env_f)"
    fi
  done
  
  echo ""
  warn "  IMPORTANTE: Configura le credenziali Ydea in:"
  echo "  $env_file"
  echo ""
  echo "Edit lines:"
  echo "  export YDEA_ID=\"il_tuo_id\""
  echo "  export YDEA_API_KEY=\"la_tua_api_key\""
  echo "  export YDEA_ALERT_EMAIL=\"massimo.palazzetti@nethesis.it\""
  echo ""
  
  read -p "Vuoi modificarlo ora? (y/n) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    ${EDITOR:-nano} "$env_file"
  fi
}

test_connection() {
  info "Test connessione Ydea API..."
  
  if [[ ! -f "${YDEA_TOOLKIT_DIR}/ydea-toolkit.sh" ]]; then
    warn "ydea-toolkit.sh non trovato, skip test"
    return
  fi
  
  cd "$YDEA_TOOLKIT_DIR"
  if source .env && ./ydea-toolkit.sh login 2>&1 | grep -q "Login effettuato"; then
    success "Connessione Ydea OK"
  else
    warn "Test connessione fallito - verifica credenziali in .env"
  fi
}

setup_cron() {
  info "Configurazione cron job per health monitor e cache validator..."
  
  local health_cron_line="*/15 * * * * ${YDEA_TOOLKIT_DIR}/ydea-health-monitor.sh >> /var/log/ydea_health.log 2>&1"
  local validator_cron_line="* * * * * ${NOTIFY_BIN_DIR}/ydea_cache_validator.py >> /var/log/ydea_cache_validator.log 2>&1"
  local current_crontab
  current_crontab="$(crontab -l 2>/dev/null || true)"
  local new_crontab="$current_crontab"
  
  # Health monitor cron
  if echo "$current_crontab" | grep -q "ydea-health-monitor"; then
    warn "Cron job health monitor già configurato"
  else
    new_crontab+=$'\n# Ydea Health Monitor - ogni 15 minuti\n'
    new_crontab+="$health_cron_line"
    new_crontab+=$'\n'
    success "Cron job health monitor configurato (ogni 15 minuti)"
  fi

  # Cache validator cron
  if [[ -x "${NOTIFY_BIN_DIR}/ydea_cache_validator.py" ]]; then
    if echo "$current_crontab" | grep -q "ydea_cache_validator"; then
      warn "Cron job cache validator già configurato"
    else
      new_crontab+=$'\n# Ydea Cache Validator - ogni 1 minuto\n'
      new_crontab+="$validator_cron_line"
      new_crontab+=$'\n'
      success "Cron job cache validator configurato (ogni 1 minuto)"
    fi
  else
    warn "Cache validator non trovato in ${NOTIFY_BIN_DIR}, skip cron dedicato"
  fi

  if [[ "$new_crontab" != "$current_crontab" ]]; then
    printf "%s\n" "$new_crontab" | crontab -
  fi
  
  # Create log files
  touch /var/log/ydea_health.log
  chmod 666 /var/log/ydea_health.log
  success "Log file creato: /var/log/ydea_health.log"

  touch /var/log/ydea_cache_validator.log
  chmod 666 /var/log/ydea_cache_validator.log
  success "Log file creato: /var/log/ydea_cache_validator.log"
}

create_cache_files() {
  info "Inizializzazione file cache..."

  local cache_dir="${YDEA_TOOLKIT_DIR}/cache"
  mkdir -p "$cache_dir"
  chmod 777 "$cache_dir"

  echo '{}' > "${cache_dir}/ydea_checkmk_tickets.json"
  chmod 666 "${cache_dir}/ydea_checkmk_tickets.json"

  echo '{}' > "${cache_dir}/ydea_checkmk_flapping.json"
  chmod 666 "${cache_dir}/ydea_checkmk_flapping.json"

  touch "${cache_dir}/ydea_cache.lock"
  chmod 666 "${cache_dir}/ydea_cache.lock"

  success "File cache inizializzati in ${cache_dir}"
}

show_next_steps() {
  echo ""
  echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${GREEN}║               Installazione Completata!                   ║${NC}"
  echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "${BLUE} PROSSIMI PASSI:${NC}"
  echo ""
  echo "1⃣ Configure notification rule in CheckMK:"
  echo "   → Setup → Notifications → Add rule"
  echo "   → Script: ydea_la / ydea_ag"
  echo ""
  echo "2⃣ Check Ydea credentials:"
  echo "   → ${YDEA_TOOLKIT_DIR}/.env"
  echo ""
  echo "3⃣  Test manuale:"
  echo "   → cd ${YDEA_TOOLKIT_DIR}"
  echo "   → source .env"
  echo "   → ./ydea-toolkit.sh login"
  echo ""
  echo "4⃣  Monitora log:"
  echo "   → tail -f /var/log/ydea_health.log"
  echo "   → tail -f /var/log/ydea_cache_validator.log"
  echo "   → tail -f /omd/sites/${CHECKMK_SITE}/var/log/notify.log"
  echo ""
  echo "5⃣  Documentazione completa:"
  echo "   → ${YDEA_TOOLKIT_DIR}/README-CHECKMK-INTEGRATION.md"
  echo ""
  echo -e "${YELLOW}  RICORDA: Configura le credenziali in .env prima dell'uso!${NC}"
  echo ""
}

# Main installation
main() {
  check_root
  check_checkmk
  check_ydea_toolkit
  install_scripts
  setup_env
  create_cache_files
  setup_cron
  test_connection
  show_next_steps
}

main

exit 0
