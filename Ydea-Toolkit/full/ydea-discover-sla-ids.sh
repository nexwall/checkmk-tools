#!/bin/bash
# ydea-discover-sla-ids.sh — Discover IDs by categories, subcategories and custom SLA
# Used to find IDs needed for ticket management with Premium_Mon SLA

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YDEA_TOOLKIT="${SCRIPT_DIR}/ydea-toolkit.sh"

# Verify that ydea-toolkit exists
if [[ ! -f "$YDEA_TOOLKIT" ]]; then
    echo "Error: ydea-toolkit.sh not found in $SCRIPT_DIR"
    exit 1
fi

# Load functions from ydea-toolkit
# shellcheck disable=SC1090
source "$YDEA_TOOLKIT"

# ===== Configuration =====
OUTPUT_FILE="${SCRIPT_DIR}/sla-premium-mon-ids.json"

# Categories to search
MACRO_CATEGORY="Premium_Mon"
declare -a SUBCATEGORIES=(
  "Centrale telefonica NethVoice"
  "Firewall UTM NethSecurity"
  "Collaboration Suite NethService"
  "Computer client"
  "Server"
  "Apparati di rete - Networking"
  "Hypervisor"
  "Consulenza tecnica specialistica"
)

SLA_NAME="TK25/003209 SLA Personalizzata"

# ===== Funzioni Helper =====
print_header() {
  echo ""
  echo "════════════════════════════════════════════════════════════════"
  echo "  $1"
  echo "════════════════════════════════════════════════════════════════"
  echo ""
}

# ===== Discovery Categorie =====
discover_categories() {
  print_header " DISCOVERY CATEGORIE E SOTTOCATEGORIE"
  
  log_info "Recupero lista categorie da Ydea API..."
  
  # Call API to get all categories
  local categories_data
  categories_data=$(ydea_api GET "/categories" 2>/dev/null || echo '{"objs":[]}')
  
  if [[ -z "$categories_data" || "$categories_data" == '{"objs":[]}' ]]; then
    log_error "Nessuna categoria trovata o errore nella chiamata API"
    return 1
  fi
  
  # Save complete data for debugging
  echo "$categories_data" > "${SCRIPT_DIR}/categories-full-dump.json"
  log_debug "Dump completo categorie salvato in categories-full-dump.json"
  
  # Search for the Premium_Mon macro category
  local macro_cat_id
  macro_cat_id=$(echo "$categories_data" | jq -r --arg name "$MACRO_CATEGORY" '
    .objs[]? | select(.nome == $name) | .id
  ' | head -1)
  
  if [[ -z "$macro_cat_id" || "$macro_cat_id" == "null" ]]; then
    log_warn "Macro categoria '$MACRO_CATEGORY' non trovata direttamente"
    log_info "Elenco tutte le categorie disponibili:"
    echo "$categories_data" | jq -r '.objs[]? | "\(.id) → \(.nome)"'
    macro_cat_id=""
  else
    log_success "Macro categoria '$MACRO_CATEGORY' trovata → ID: $macro_cat_id"
  fi
  
  # Look for subcategories
  declare -A subcategory_ids
  local found_count=0
  
  echo ""
  log_info "Ricerca sottocategorie..."
  echo ""
  
  for subcat in "${SUBCATEGORIES[@]}"; do
    local subcat_id
    subcat_id=$(echo "$categories_data" | jq -r --arg name "$subcat" '
      .objs[]? | select(.nome == $name) | .id
    ' | head -1)
    
    if [[ -n "$subcat_id" && "$subcat_id" != "null" ]]; then
      subcategory_ids["$subcat"]="$subcat_id"
      echo "   '$subcat' → ID: $subcat_id"
      ((found_count++))
    else
      echo "'$subcat' → NOT FOUND"
    fi
  done
  
  echo ""
  log_info "Sottocategorie trovate: $found_count/${#SUBCATEGORIES[@]}"
  
  # Build JSON output by categories
  local json_output="{}"
  
  if [[ -n "$macro_cat_id" ]]; then
    json_output=$(echo "$json_output" | jq --arg id "$macro_cat_id" --arg name "$MACRO_CATEGORY" '
      .macro_category = {id: ($id|tonumber), name: $name}
    ')
  fi
  
  # Aggiungi sottocategorie
  local subcats_json="[]"
  for subcat in "${!subcategory_ids[@]}"; do
    local subcat_id="${subcategory_ids[$subcat]}"
    subcats_json=$(echo "$subcats_json" | jq --arg name "$subcat" --arg id "$subcat_id" '
      . += [{name: $name, id: ($id|tonumber)}]
    ')
  done
  
  json_output=$(echo "$json_output" | jq --argjson subcats "$subcats_json" '
    .subcategories = $subcats
  ')
  
  echo "$json_output"
}

# ===== Discovery SLA =====
discover_sla() {
  print_header " DISCOVERY SLA PERSONALIZZATA"
  
  log_info "Recupero lista SLA da Ydea API..."
  
  # Call API to get all SLAs
  local sla_data
  sla_data=$(ydea_api GET "/sla" 2>/dev/null || echo '{"objs":[]}')
  
  if [[ -z "$sla_data" || "$sla_data" == '{"objs":[]}' ]]; then
    log_warn "Nessuna SLA trovata o endpoint non disponibile"
    # Prova endpoint alternativo
    sla_data=$(ydea_api GET "/slas" 2>/dev/null || echo '{"objs":[]}')
  fi
  
  # Save complete data for debugging
  echo "$sla_data" > "${SCRIPT_DIR}/sla-full-dump.json"
  log_debug "Dump completo SLA salvato in sla-full-dump.json"
  
  # Search for the specific ALS
  local sla_id
  sla_id=$(echo "$sla_data" | jq -r --arg name "$SLA_NAME" '
    .objs[]? | select(.nome == $name or .name == $name or .title == $name) | .id
  ' | head -1)
  
  if [[ -z "$sla_id" || "$sla_id" == "null" ]]; then
    log_warn "SLA '$SLA_NAME' non trovata direttamente"
    log_info "Elenco tutte le SLA disponibili:"
    echo "$sla_data" | jq -r '.objs[]? | "\(.id) → \(.nome // .name // .title)"'
    
    # Try partial search on TK25/003209
    log_info "Tentativo ricerca per codice 'TK25/003209'..."
    sla_id=$(echo "$sla_data" | jq -r '
      .objs[]? | select(.nome // .name // .title | test("TK25/003209")) | .id
    ' | head -1)
    
    if [[ -z "$sla_id" || "$sla_id" == "null" ]]; then
      sla_id=""
    else
      log_success "SLA trovata tramite ricerca parziale → ID: $sla_id"
    fi
  else
    log_success "SLA '$SLA_NAME' trovata → ID: $sla_id"
  fi
  
  # Build JSON output for SLA
  local json_output="{}"
  
  if [[ -n "$sla_id" ]]; then
    json_output=$(echo "$json_output" | jq --arg id "$sla_id" --arg name "$SLA_NAME" '
      .sla = {id: ($id|tonumber), name: $name}
    ')
  fi
  
  echo "$json_output"
}

# ===== Discovery Priorità =====
discover_priorities() {
  print_header " DISCOVERY PRIORITÀ"
  
  log_info "Recupero lista priorità da Ydea API..."
  
  # Call API to get all priorities
  local priorities_data
  priorities_data=$(ydea_api GET "/priorities" 2>/dev/null || echo '{"objs":[]}')
  
  if [[ -z "$priorities_data" || "$priorities_data" == '{"objs":[]}' ]]; then
    log_warn "Nessuna priorità trovata o endpoint non disponibile"
    return 0
  fi
  
  # Save complete data for debugging
  echo "$priorities_data" > "${SCRIPT_DIR}/priorities-full-dump.json"
  log_debug "Dump completo priorità salvato in priorities-full-dump.json"
  
  # Cerca priorità "Bassa"
  local low_priority_id
  low_priority_id=$(echo "$priorities_data" | jq -r '
    .objs[]? | select(.nome == "Bassa" or .name == "Bassa" or .nome == "Low" or .name == "Low") | .id
  ' | head -1)
  
  if [[ -z "$low_priority_id" || "$low_priority_id" == "null" ]]; then
    log_warn "Priorità 'Bassa' non trovata"
    log_info "Elenco tutte le priorità disponibili:"
    echo "$priorities_data" | jq -r '.objs[]? | "\(.id) → \(.nome // .name)"'
    low_priority_id=""
  else
    log_success "Priorità 'Bassa' trovata → ID: $low_priority_id"
  fi
  
  # Build JSON output by priority
  local json_output="{}"
  
  if [[ -n "$low_priority_id" ]]; then
    json_output=$(echo "$json_output" | jq --arg id "$low_priority_id" '
      .low_priority = {id: ($id|tonumber), name: "Bassa"}
    ')
  fi
  
  echo "$json_output"
}

# ===== Main =====
main() {
  print_header " YDEA SLA DISCOVERY TOOL"
  
  log_info "Inizio discovery per SLA Premium_Mon..."
  log_info "Output verrà salvato in: $OUTPUT_FILE"
  
  # Verify authentication
  if ! ensure_token 2>&1; then
    log_error "Impossibile autenticarsi a Ydea API"
    log_error "Verifica YDEA_ID e YDEA_API_KEY nel file .env"
    exit 1
  fi
  
  log_success "Autenticazione completata"
  
  # Discovery categorie
  local categories_json
  categories_json=$(discover_categories)
  
  # Discovery SLA
  local sla_json
  sla_json=$(discover_sla)
  
  # Discovery priorità
  local priorities_json
  priorities_json=$(discover_priorities)
  
  # Combine all results
  print_header " GENERAZIONE FILE CONFIGURAZIONE"
  
  local final_json
  final_json=$(jq -n \
    --argjson cats "$categories_json" \
    --argjson sla "$sla_json" \
    --argjson priorities "$priorities_json" \
    '{
      discovery_date: (now | strftime("%Y-%m-%d %H:%M:%S")),
      description: "ID per gestione ticket con SLA Premium_Mon",
      macro_category: $cats.macro_category,
      subcategories: $cats.subcategories,
      sla: $sla.sla,
      low_priority: $priorities.low_priority
    }')
  
  # Save the file
  echo "$final_json" > "$OUTPUT_FILE"
  
  print_header " DISCOVERY COMPLETATO"
  
  log_success "File di configurazione creato: $OUTPUT_FILE"
  echo ""
  echo "Contenuto:"
  jq -C '.' "$OUTPUT_FILE" || cat "$OUTPUT_FILE"
  echo ""
  
  # Check completeness
  local missing_items=()
  
  if ! echo "$final_json" | jq -e '.macro_category.id' >/dev/null 2>&1; then
    missing_items+=("Macro categoria Premium_Mon")
  fi
  
  local subcat_count
  subcat_count=$(echo "$final_json" | jq '.subcategories | length')
  if [[ "$subcat_count" -lt "${#SUBCATEGORIES[@]}" ]]; then
    missing_items+=("Alcune sottocategorie ($subcat_count/${#SUBCATEGORIES[@]} trovate)")
  fi
  
  if ! echo "$final_json" | jq -e '.sla.id' >/dev/null 2>&1; then
    missing_items+=("SLA personalizzata TK25/003209")
  fi
  
  if [[ "${#missing_items[@]}" -gt 0 ]]; then
    echo ""
    log_warn "  ATTENZIONE: Alcuni elementi non sono stati trovati:"
    for item in "${missing_items[@]}"; do
      echo "  • $item"
    done
    echo ""
    log_info "Controlla i file *-full-dump.json per verificare i dati disponibili nell'API"
    exit 1
  else
    echo ""
    log_success " Tutti gli elementi richiesti sono stati trovati!"
    echo ""
    log_info "Prossimi passi:"
    echo "1. Check the contents of: $OUTPUT_FILE"
    echo "2. Integrate these IDs into your CheckMK notification scripts"
    echo "3. Implement the subcategory → alarm type mapping logic"
  fi
}

# Esegui main
main "$@"
