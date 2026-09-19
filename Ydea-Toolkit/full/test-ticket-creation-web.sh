#!/bin/bash
# test-ticket-creation-web.sh - Test ticket creation via HTML form (real data from HAR)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration
YDEA_BASE_URL="https://my.ydea.cloud"
COOKIE_FILE="$SCRIPT_DIR/../config/.ydea-cookies"

# Credentials (to be configured)
if [[ ! -f "$SCRIPT_DIR/../config/credentials.sh" ]]; then
    echo "Missing credential file: $SCRIPT_DIR/../config/credentials.sh"
    echo ""
    echo "Create the file with:"
    echo "  YDEA_USERNAME='your@email.com'"
    echo "YDEA_PASSWORD='your-password'"
    exit 1
fi

source "$SCRIPT_DIR/../config/credentials.sh"

echo "════════════════════════════════════════════════════════════════════"
echo " TEST CREAZIONE TICKET YDEA - Via Form HTML"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Funzione login
login_ydea() {
    echo " Login a YDEA..."
    
    # GET login page for CSRF token
    LOGIN_PAGE=$(curl -s -c "$COOKIE_FILE" "${YDEA_BASE_URL}/login")
    
    # Extract CSRF token from login page
    CSRF_TOKEN=$(echo "$LOGIN_PAGE" | grep -oP '(?<=name="_csrf_token" value=")[^"]+' || echo "")
    
    if [[ -z "$CSRF_TOKEN" ]]; then
        echo "CSRF token not found on login page"
        return 1
    fi
    
    echo "CSRF Token: ${CSRF_TOKEN:0:20}..."
    
    # POST login (with verbose for debugging)
    HTTP_CODE=$(curl -w "%{http_code}" -o /tmp/login_response.html \
        -b "$COOKIE_FILE" -c "$COOKIE_FILE" \
        -X POST "${YDEA_BASE_URL}/login_check" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "_username=${YDEA_USERNAME}" \
        -d "_password=${YDEA_PASSWORD}" \
        -d "_csrf_token=${CSRF_TOKEN}" \
        -L)
    
    LOGIN_RESPONSE=$(cat /tmp/login_response.html)
    
    echo "   HTTP Code: $HTTP_CODE"
    
    # Debugging: Save response for analysis
    if [[ "$HTTP_CODE" != "200" ]]; then
        echo "Response saved in /tmp/login_response.html for debugging"
    fi
    
    # Verify successful login - multiple patterns
    if echo "$LOGIN_RESPONSE" | grep -qi "logout\|esci\|dashboard\|/ticket/new\|benvenuto"; then
        echo "Login successful!"
        return 0
    elif echo "$LOGIN_RESPONSE" | grep -qi "invalid\|credenziali\|password\|errato"; then
        echo "Login failed - Invalid credentials"
        echo "Check username/password in credentials.sh"
        return 1
    else
        echo "Login failed - Unexpected response"
        echo "First 500 characters of the response:"
        echo "$LOGIN_RESPONSE" | head -c 500
        return 1
    fi
}

# CSRF token extraction function from ticket form
get_ticket_form_token() {
    echo "Extracting CSRF token from /ticket/new..."
    
    NEW_TICKET_PAGE=$(curl -s -b "$COOKIE_FILE" "${YDEA_BASE_URL}/ticket/new")
    
    # Extract token from appbundle_ticket[_token] field
    FORM_TOKEN=$(echo "$NEW_TICKET_PAGE" | grep -oP '(?<=name="appbundle_ticket\[_token\]" value=")[^"]+' || echo "")
    
    if [[ -z "$FORM_TOKEN" ]]; then
        echo "Form token not found"
        return 1
    fi
    
    echo "Form token: ${FORM_TOKEN:0:40}..."
    echo "$FORM_TOKEN"
}

# Funzione creazione ticket
create_ticket() {
    local titolo="$1"
    local contratto="$2"
    local sla="${3:-}"
    
    echo ""
    echo "────────────────────────────────────────────────────────────────────"
    echo " Creazione ticket: $titolo"
    echo "   Contratto: $contratto"
    [[ -n "$sla" ]] && echo "   SLA: $sla"
    echo "────────────────────────────────────────────────────────────────────"
    
    # Get fresh token
    FORM_TOKEN=$(get_ticket_form_token)
    
    if [[ -z "$FORM_TOKEN" ]]; then
        echo "Unable to get form token"
        return 1
    fi
    
    # Dati estratti dal HAR (valori reali)
    # Adapt these IDs to your real data
    AZIENDA_ID="2339268"           # AZIENDA MONITORATA test
    DESTINAZIONE_ID="2831588"       # Sede/destinazione
    
    # Crea multipart form data
    BOUNDARY="----WebKitFormBoundary$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 16 | head -n 1)"
    
    # Costruisci body multipart
    BODY=""
    
    # Titolo
    BODY+="--${BOUNDARY}\r\n"
    BODY+="Content-Disposition: form-data; name=\"appbundle_ticket[titolo]\"\r\n\r\n"
    BODY+="${titolo}\r\n"
    
    # Tipo
    BODY+="--${BOUNDARY}\r\n"
    BODY+="Content-Disposition: form-data; name=\"appbundle_ticket[tipo]\"\r\n\r\n"
    BODY+="Server\r\n"
    
    # Priorità
    BODY+="--${BOUNDARY}\r\n"
    BODY+="Content-Disposition: form-data; name=\"appbundle_ticket[priorita]\"\r\n\r\n"
    BODY+="30\r\n"
    
    # Fonte
    BODY+="--${BOUNDARY}\r\n"
    BODY+="Content-Disposition: form-data; name=\"appbundle_ticket[fonte]\"\r\n\r\n"
    BODY+="\r\n"
    
    # Pagamento (from HAR: 61576)
    BODY+="--${BOUNDARY}\r\n"
    BODY+="Content-Disposition: form-data; name=\"appbundle_ticket[pagamento]\"\r\n\r\n"
    BODY+="61576\r\n"
    
    # ServiceLevelAgreement (se fornito)
    if [[ -n "$sla" ]]; then
        BODY+="--${BOUNDARY}\r\n"
        BODY+="Content-Disposition: form-data; name=\"appbundle_ticket[serviceLevelAgreement]\"\r\n\r\n"
        BODY+="${sla}\r\n"
    fi
    
    # CSRF Token
    BODY+="--${BOUNDARY}\r\n"
    BODY+="Content-Disposition: form-data; name=\"appbundle_ticket[_token]\"\r\n\r\n"
    BODY+="${FORM_TOKEN}\r\n"
    
    # Azienda
    BODY+="--${BOUNDARY}\r\n"
    BODY+="Content-Disposition: form-data; name=\"azienda\"\r\n\r\n"
    BODY+="${AZIENDA_ID}\r\n"
    
    # Destinazione
    BODY+="--${BOUNDARY}\r\n"
    BODY+="Content-Disposition: form-data; name=\"destinazione\"\r\n\r\n"
    BODY+="${DESTINAZIONE_ID}\r\n"
    
    # Contatto (vuoto)
    BODY+="--${BOUNDARY}\r\n"
    BODY+="Content-Disposition: form-data; name=\"contatto\"\r\n\r\n"
    BODY+="\r\n"
    
    # Contratto
    BODY+="--${BOUNDARY}\r\n"
    BODY+="Content-Disposition: form-data; name=\"contratto\"\r\n\r\n"
    BODY+="${contratto}\r\n"
    
    # Asset
    BODY+="--${BOUNDARY}\r\n"
    BODY+="Content-Disposition: form-data; name=\"asset\"\r\n\r\n"
    BODY+="0\r\n"
    
    # Condizione addebito
    BODY+="--${BOUNDARY}\r\n"
    BODY+="Content-Disposition: form-data; name=\"condizioneAddebito\"\r\n\r\n"
    BODY+="C\r\n"
    
    # Progetto
    BODY+="--${BOUNDARY}\r\n"
    BODY+="Content-Disposition: form-data; name=\"progetto\"\r\n\r\n"
    BODY+="\r\n"
    
    # Files (vuoto)
    BODY+="--${BOUNDARY}\r\n"
    BODY+="Content-Disposition: form-data; name=\"files[]\"; filename=\"\"\r\n"
    BODY+="Content-Type: application/octet-stream\r\n\r\n"
    BODY+="\r\n"
    
    # Descrizione
    BODY+="--${BOUNDARY}\r\n"
    BODY+="Content-Disposition: form-data; name=\"appbundle_ticket[descrizione]\"\r\n\r\n"
    BODY+="Test automatico creazione ticket\r\n"
    
    # Custom attribute (from HAR: custom_attributes[int][3958]=14553)
    BODY+="--${BOUNDARY}\r\n"
    BODY+="Content-Disposition: form-data; name=\"custom_attributes[int][3958]\"\r\n\r\n"
    BODY+="14553\r\n"
    
    # End multipart
    BODY+="--${BOUNDARY}--\r\n"
    
    # POST ticket
    RESPONSE=$(curl -s -b "$COOKIE_FILE" -c "$COOKIE_FILE" \
        -X POST "${YDEA_BASE_URL}/ticket/new" \
        -H "Content-Type: multipart/form-data; boundary=${BOUNDARY}" \
        --data-binary "$BODY" \
        -L -w "\nHTTP_CODE:%{http_code}\nREDIRECT:%{url_effective}\n")
    
    # Extract info from response
    HTTP_CODE=$(echo "$RESPONSE" | grep "HTTP_CODE:" | cut -d: -f2)
    REDIRECT_URL=$(echo "$RESPONSE" | grep "REDIRECT:" | cut -d: -f2-)
    
    # Se redirect a /ticket/{ID}, estrai ID
    if [[ "$REDIRECT_URL" =~ /ticket/([0-9]+) ]]; then
        TICKET_ID="${BASH_REMATCH[1]}"
        echo "Ticket created: ID $TICKET_ID"
        echo " URL: ${YDEA_BASE_URL}/ticket/${TICKET_ID}"
        return 0
    elif [[ "$HTTP_CODE" == "200" ]] && echo "$RESPONSE" | grep -q "ticket creato\|success"; then
        echo "Ticket probably created (HTTP 200)"
        # Cerca ID nel body
        TICKET_ID=$(echo "$RESPONSE" | grep -oP '/ticket/\K[0-9]+' | head -1)
        [[ -n "$TICKET_ID" ]] && echo " URL: ${YDEA_BASE_URL}/ticket/${TICKET_ID}"
        return 0
    else
        echo "Creation failed (HTTP $HTTP_CODE)"
        echo ""
        echo "Response (primi 500 char):"
        echo "$RESPONSE" | head -c 500
        return 1
    fi
}

# Main
if ! login_ydea; then
    echo "Unable to proceed without login"
    exit 1
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "TEST 1: Ticket with SLA Premium_Mon contract"
echo "════════════════════════════════════════════════════════════════════"

# Valori estratti dal HAR
CONTRACT_ID="171734"  # Contratto con SLA Premium_Mon
SLA_ID="147"          # serviceLevelAgreement ID

create_ticket "[TEST] Contratto Premium_Mon" "$CONTRACT_ID" "$SLA_ID"

echo ""
sleep 2

echo "════════════════════════════════════════════════════════════════════"
echo "TEST 2: Ticket WITHOUT SLA field (contract only)"
echo "════════════════════════════════════════════════════════════════════"

create_ticket "[TEST] Solo contratto, no SLA esplicito" "$CONTRACT_ID" ""

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo " Test completati!"
echo ""
echo "MANUAL VERIFICATION on YDEA:"
echo "1. Go to https://my.ydea.cloud"
echo "2. Check the 2 tickets you just created"
echo "3. Check which one has active SLA 'Premium_Mon'"
echo ""
echo "This will tell you if the 'serviceLevelAgreement' field is:"
echo "- REQUIRED to apply the correct SLA"
echo "- OPTIONAL (the SLA is taken from the contract)"
echo "════════════════════════════════════════════════════════════════════"
