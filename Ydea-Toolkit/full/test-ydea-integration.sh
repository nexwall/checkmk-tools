#!/usr/bin/env bash
# test-ydea-integration.sh - Complete CheckMK integration test script → Ydea
# Run this script to verify that everything is working correctly

set -euo pipefail

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║      Test Integrazione CheckMK → Ydea Ticketing          ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Configuration
CHECKMK_SITE="${CHECKMK_SITE:-monitoring}"
NOTIFY_SCRIPT="/omd/sites/${CHECKMK_SITE}/local/share/check_mk/notifications/ydea_realip"
HEALTH_SCRIPT="/opt/ydea-toolkit/ydea-health-monitor.sh"
YDEA_TOOLKIT="/opt/ydea-toolkit/ydea-toolkit.sh"

# Contatori
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_TOTAL=0

# Funzioni
test_start() {
  TESTS_TOTAL=$((TESTS_TOTAL + 1))
  echo -e "${BLUE}[TEST $TESTS_TOTAL]${NC} $1"
}

test_pass() {
  TESTS_PASSED=$((TESTS_PASSED + 1))
  echo -e "${GREEN}   PASS${NC}: $1"
  echo ""
}

test_fail() {
  TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "${RED}   FAIL${NC}: $1"
  echo ""
}

test_warn() {
  echo -e "${YELLOW}    WARN${NC}: $1"
}

# ===== TEST 1: Check File =====
test_start "Verifica esistenza file necessari"

if [[ -f "$NOTIFY_SCRIPT" ]]; then
  test_pass "Script notifica trovato: $NOTIFY_SCRIPT"
else
  test_fail "Script notifica non trovato: $NOTIFY_SCRIPT"
fi

if [[ -f "$HEALTH_SCRIPT" ]]; then
  test_pass "Health monitor trovato: $HEALTH_SCRIPT"
else
  test_fail "Health monitor non trovato: $HEALTH_SCRIPT"
fi

if [[ -f "$YDEA_TOOLKIT" ]]; then
  test_pass "Ydea toolkit trovato: $YDEA_TOOLKIT"
else
  test_fail "Ydea toolkit non trovato: $YDEA_TOOLKIT"
fi

# ===== TEST 2: Permissions =====
test_start "Verifica permessi esecuzione"

if [[ -x "$NOTIFY_SCRIPT" ]]; then
  test_pass "ydea_realip è eseguibile"
else
  test_fail "ydea_realip NON è eseguibile (usa: chmod +x)"
fi

if [[ -x "$HEALTH_SCRIPT" ]]; then
  test_pass "ydea-health-monitor.sh è eseguibile"
else
  test_fail "ydea-health-monitor.sh NON è eseguibile"
fi

# ===== TEST 3: Configuration =====
test_start "Verifica configurazione .env"

ENV_FILE="/opt/ydea-toolkit/.env"
if [[ -f "$ENV_FILE" ]]; then
  source "$ENV_FILE"
  
  if [[ -n "${YDEA_ID:-}" && "${YDEA_ID}" != "ID" ]]; then
    test_pass "YDEA_ID configurato"
  else
    test_fail "YDEA_ID non configurato o ancora placeholder"
  fi
  
  if [[ -n "${YDEA_API_KEY:-}" && "${YDEA_API_KEY}" != "TOKEN" ]]; then
    test_pass "YDEA_API_KEY configurato"
  else
    test_fail "YDEA_API_KEY non configurato o ancora placeholder"
  fi
  
  if [[ -n "${YDEA_ALERT_EMAIL:-}" ]]; then
    test_pass "YDEA_ALERT_EMAIL configurato: ${YDEA_ALERT_EMAIL}"
  else
    test_warn "YDEA_ALERT_EMAIL non configurato (opzionale)"
  fi
else
  test_fail "File .env non trovato: $ENV_FILE"
fi

# ===== TEST 4: Ydea Connection =====
test_start "Test connessione Ydea API"

if [[ -f "$YDEA_TOOLKIT" && -f "$ENV_FILE" ]]; then
  cd "$(dirname "$YDEA_TOOLKIT")"
  if source "$ENV_FILE" && "$YDEA_TOOLKIT" login 2>&1 | grep -q "Login effettuato"; then
    test_pass "Login Ydea riuscito"
  else
    test_fail "Login Ydea fallito - verifica credenziali"
  fi
else
  test_warn "Skip test login (file mancanti)"
fi

# ===== TEST 5: Cache Files =====
test_start "Verifica file cache"

TICKET_CACHE="/tmp/ydea_checkmk_tickets.json"
FLAPPING_CACHE="/tmp/ydea_checkmk_flapping.json"
HEALTH_STATE="/tmp/ydea_health_state.json"

for cache_file in "$TICKET_CACHE" "$FLAPPING_CACHE"; do
  if [[ -f "$cache_file" ]]; then
    if jq . "$cache_file" >/dev/null 2>&1; then
      test_pass "Cache valido: $(basename $cache_file)"
    else
      test_fail "Cache corrotto: $cache_file"
    fi
  else
    test_warn "Cache non inizializzato: $cache_file (verrà creato al primo uso)"
  fi
done

# ===== TEST 6: Dipendenze =====
test_start "Verifica dipendenze sistema"

for cmd in jq curl bash date; do
  if command -v "$cmd" >/dev/null 2>&1; then
    test_pass "Comando disponibile: $cmd"
  else
    test_fail "Comando mancante: $cmd (installa con: apt install $cmd)"
  fi
done

# ===== TEST 7: Cron Job =====
test_start "Verifica cron job health monitor"

if crontab -l 2>/dev/null | grep -q "ydea-health-monitor"; then
  CRON_LINE=$(crontab -l | grep "ydea-health-monitor" | head -1)
  test_pass "Cron job configurato"
  echo "  Schedule: $CRON_LINE"
else
  test_warn "Cron job non trovato (configura con: crontab -e)"
  echo "  Aggiungi: */15 * * * * $HEALTH_SCRIPT >> /var/log/ydea_health.log 2>&1"
fi
echo ""

# ===== TEST 8: Log Files =====
test_start "Verifica accessibilità log"

LOG_NOTIFY="/omd/sites/${CHECKMK_SITE}/var/log/notify.log"
LOG_HEALTH="/var/log/ydea_health.log"

if [[ -r "$LOG_NOTIFY" ]]; then
  test_pass "Log notifiche leggibile: $LOG_NOTIFY"
else
  test_warn "Log notifiche non accessibile: $LOG_NOTIFY"
fi

if [[ -f "$LOG_HEALTH" ]]; then
  test_pass "Log health esistente: $LOG_HEALTH"
else
  test_warn "Log health non trovato (verrà creato al primo run)"
fi

# ===== TEST 9: Simulazione Notifica =====
test_start "Test simulazione notifica (opzionale)"

echo -e "${YELLOW}Vuoi eseguire un test di notifica simulata? (y/n)${NC}"
read -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
  export NOTIFY_WHAT="SERVICE"
  export NOTIFY_HOSTNAME="test-server"
  export NOTIFY_HOSTADDRESS="192.168.99.99"
  export NOTIFY_SERVICEDESC="Test Alert"
  export NOTIFY_SERVICESTATE="CRIT"
  export NOTIFY_LASTSERVICESTATE="OK"
  export NOTIFY_SERVICEOUTPUT="This is a test alert"
  export NOTIFY_SERVICESTATETYPE="HARD"
  
  echo "Esecuzione: $NOTIFY_SCRIPT"
  if "$NOTIFY_SCRIPT" 2>&1 | tee /tmp/ydea_test_output.log; then
    echo ""
    test_pass "Script eseguito senza errori"
    echo "Output saved in: /tmp/ydea_test_output.log"
    
    # Check if ticket created
    if [[ -f "$TICKET_CACHE" ]]; then
      TICKET_ID=$(jq -r '.["192.168.99.99:Test Alert"].ticket_id // empty' "$TICKET_CACHE" 2>/dev/null)
      if [[ -n "$TICKET_ID" ]]; then
        test_pass "Ticket creato: #$TICKET_ID"
      else
        test_warn "Nessun ticket trovato in cache (verifica output sopra)"
      fi
    fi
  else
    test_fail "Script terminato con errore"
  fi
else
  test_warn "Test simulazione saltato"
fi
echo ""

# ===== TEST 10: Health Monitor =====
test_start "Test health monitor (opzionale)"

echo -e "${YELLOW}Vuoi testare il health monitor? (y/n)${NC}"
read -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
  if "$HEALTH_SCRIPT" 2>&1 | tee /tmp/ydea_health_test.log; then
    test_pass "Health monitor eseguito"
    echo "Output saved in: /tmp/ydea_health_test.log"
  else
    test_fail "Health monitor fallito"
  fi
else
  test_warn "Test health monitor saltato"
fi
echo ""

# ===== RIEPILOGO =====
echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                     RIEPILOGO TEST                        ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Test totali:  ${BLUE}$TESTS_TOTAL${NC}"
echo -e "Test passati: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Test falliti: ${RED}$TESTS_FAILED${NC}"
echo ""

if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "${GREEN} TUTTI I TEST PASSATI!${NC}"
  echo ""
  echo -e "${GREEN} Sistema pronto per la produzione!${NC}"
  echo ""
  echo "Prossimi passi:"
  echo "1. Configure notification rule in CheckMK"
  echo "2. Monitora i log durante i primi alert"
  echo "3. Check ticket creation on Ydea"
else
  echo -e "${RED} ALCUNI TEST FALLITI${NC}"
  echo ""
  echo "Fix errors before using in production:"
  echo "1. Check above error messages"
  echo "2. Consulta: README-CHECKMK-INTEGRATION.md → Troubleshooting"
  echo "3. Re-run this script after corrections"
fi
echo ""

# Report files
REPORT_FILE="/tmp/ydea_integration_test_report_$(date +%Y%m%d_%H%M%S).txt"
{
  echo "=== REPORT TEST INTEGRAZIONE YDEA-CHECKMK ==="
  echo "Data: $(date)"
  echo "Host: $(hostname)"
  echo ""
  echo "Test totali: $TESTS_TOTAL"
  echo "Passati: $TESTS_PASSED"
  echo "Falliti: $TESTS_FAILED"
  echo ""
  echo "=== CONFIGURATION ==="
  echo "CheckMK site: $CHECKMK_SITE"
  echo "Script notifica: $NOTIFY_SCRIPT"
  echo "Health monitor: $HEALTH_SCRIPT"
  echo "Ydea toolkit: $YDEA_TOOLKIT"
  echo ""
  echo "=== CACHE FILES ==="
  ls -lh /tmp/ydea_*.json 2>/dev/null || echo "No cache found"
  echo ""
  echo "=== CRON JOB ==="
  crontab -l 2>/dev/null | grep ydea || echo "No cron jobs found"
} > "$REPORT_FILE"

echo "Complete report saved in: $REPORT_FILE"
echo ""

exit $TESTS_FAILED
