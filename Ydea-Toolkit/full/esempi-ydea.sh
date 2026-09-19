#!/usr/bin/env bash
# examples-ydea.sh - Example script for common operations

TOOLKIT="./ydea-toolkit.sh"

# Upload credentials
if [[ -f .env ]]; then
  source .env
else
  echo ".env file not found. Copy .env.example to .env and fill in the credentials."
  exit 1
fi

echo "=== EXAMPLES OF USE YDEA TOOLKIT ==="
echo

# === ESEMPIO 1: Report giornaliero ticket ===
esempio_report_giornaliero() {
  echo " REPORT TICKET GIORNALIERO"
  echo "================================"
  
  # Ticket aperti
  echo " Ticket APERTI:"
  $TOOLKIT list 100 open | jq -r '.data[] | "  #\(.id) - \(.title) [prio: \(.priority)]"' 2>/dev/null || echo "Mistake"
  
  echo
  
  # Ticket in progress
  echo "Ticket IN PROCESSING:"
  $TOOLKIT list 100 in_progress | jq -r '.data[] | "  #\(.id) - \(.title) [assegnato a: \(.assigned_to.name // "nessuno")]"' 2>/dev/null || echo "Mistake"
  
  echo
  
  # Statistiche
  echo " STATISTICHE:"
  local total_open=$($TOOLKIT list 1000 open | jq '.total // 0' 2>/dev/null)
  local total_closed=$($TOOLKIT list 1000 closed | jq '.total // 0' 2>/dev/null)
  echo "  Aperti: $total_open"
  echo "  Chiusi: $total_closed"
}

# === EXAMPLE 2: Create ticket from monitoring ===
esempio_ticket_monitoraggio() {
  echo "TICKET CREATION FROM ALERT"
  echo "================================"
  
  # Simulate a system alert
  local hostname="server-prod-01"
  local alert_type="CPU usage high"
  local current_value="95%"
  
  local title="[ALERT] $alert_type su $hostname"
  local description="Alert automatico dal sistema di monitoraggio:
  
Hostname: $hostname
Tipo alert: $alert_type
Valore corrente: $current_value
Data/ora: $(date '+%Y-%m-%d %H:%M:%S')

Azione richiesta: Verificare carico CPU e processi in esecuzione."

  echo "Creo ticket: $title"
  
  local result=$($TOOLKIT create "$title" "$description" "high")
  local ticket_id=$(echo "$result" | jq -r '.id // empty')
  
  if [[ -n "$ticket_id" ]]; then
    echo "Ticket created: #$ticket_id"
    echo "$result" | jq '.'
  else
    echo "Error in creation"
    echo "$result"
  fi
}

# === EXAMPLE 3: Search and update tickets ===
esempio_cerca_e_aggiorna() {
  echo "SEARCH AND UPDATE TICKETS"
  echo "================================"
  
  local query="database"
  
  echo "Cerco ticket contenenti: '$query'"
  local tickets=$($TOOLKIT search "$query" 5)
  
  echo "$tickets" | jq -r '.data[]? | "  #\(.id) - \(.title) [\(.status)]"'
  
  # Get the first ticket (example)
  local first_id=$(echo "$tickets" | jq -r '.data[0].id // empty')
  
  if [[ -n "$first_id" ]]; then
    echo
    echo "Aggiungo commento al ticket #$first_id"
    $TOOLKIT comment "$first_id" "Ticket rivisto durante manutenzione programmata"
  fi
}

# === ESEMPIO 4: Workflow completo ===
esempio_workflow_completo() {
  echo " WORKFLOW COMPLETO"
  echo "================================"
  
  # 1. Crea ticket
  echo "1⃣ Creazione ticket..."
  local result=$($TOOLKIT create "Test workflow" "Ticket di test per workflow automatico" "normal")
  local ticket_id=$(echo "$result" | jq -r '.id // empty')
  
  if [[ -z "$ticket_id" ]]; then
    echo "Error in creation"
    return 1
  fi
  
  echo "Ticket #$ticket_id created"
  
  # 2. Recupera dettagli
  echo "2⃣ Recupero dettagli..."
  $TOOLKIT get "$ticket_id" | jq '{id, title, status, priority, created_at}'
  
  # 3. Aggiungi commento
  echo "3⃣ Added comment..."
  $TOOLKIT comment "$ticket_id" "Inizio lavorazione ticket"
  
  # 4. Update status
  echo "4⃣ Status update to 'in progress'..."
  $TOOLKIT update "$ticket_id" '{"status":"in_progress"}'
  
  # 5. Aggiungi nota finale e chiudi
  echo "5⃣ Added final note..."
  $TOOLKIT comment "$ticket_id" "Lavorazione completata con successo"
  
  echo "6⃣ Chiusura ticket..."
  $TOOLKIT close "$ticket_id" "Test workflow completato"
  
  echo
  echo "Workflow completed for ticket #$ticket_id"
}

# === EXAMPLE 5: Export tickets to CSV ===
esempio_export_csv() {
  echo "EXPORT TICKET IN CSV"
  echo "================================"
  
  local output_file="tickets_$(date +%Y%m%d_%H%M%S).csv"
  
  echo "Export ticket to $output_file..."
  
  $TOOLKIT list 1000 | jq -r '
    ["ID","Titolo","Status","Priorità","Creato il","Assegnato a"] as $headers |
    .data[] as $row |
    [$row.id, $row.title, $row.status, $row.priority, $row.created_at, ($row.assigned_to.name // "N/A")] |
    @csv
  ' > "$output_file"
  
  echo "Export completed: $output_file"
  echo "Prime 5 righe:"
  head -5 "$output_file"
}

# === MENU INTERATTIVO ===
show_menu() {
  echo
  echo "Choose an example to run:"
  echo "  1) Report giornaliero ticket"
  echo "2) Create tickets from monitoring alerts"
  echo "3) Search and update tickets"
  echo "4) Complete workflow (create → update → close)"
  echo "5) Export tickets to CSV"
  echo "  0) Esci"
  echo
  read -p "Scelta [0-5]: " choice
  
  case $choice in
    1) esempio_report_giornaliero ;;
    2) esempio_ticket_monitoraggio ;;
    3) esempio_cerca_e_aggiorna ;;
    4) esempio_workflow_completo ;;
    5) esempio_export_csv ;;
    0) echo "Ciao!"; exit 0 ;;
    *) echo "Invalid choice"; show_menu ;;
  esac
  
  echo
  read -p "Premi INVIO per continuare..."
  show_menu
}

# Startup
if [[ "${1:-}" == "--menu" ]]; then
  show_menu
else
  echo "Run with --menu for interactive menu"
  echo "Oppure esegui singole funzioni:"
  echo "  source $0 && esempio_report_giornaliero"
  echo "  source $0 && esempio_workflow_completo"
fi
