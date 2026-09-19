#!/usr/bin/env python3
"""create_monitoring_ticket.py - Create Ydea ticket from CheckMK alarm

Convert CheckMK alarms to Ydea tickets with:
- Automatic determination of type from config
- Added private note with alarm details
- Ticket tracking for monitoring

Usage:
    create_monitoring_ticket.py <HOST> <SERVICE> <STATE> <OUTPUT> [HOST_IP]

Example:
    create_monitoring_ticket.py 'mail.example.com' 'HTTP' 'CRITICAL' 'Connection timeout' '1.2.3.4'

Version: 1.0.0 (ported from Bash)"""

VERSION = "1.0.0"  # Versione script (aggiornare ad ogni modifica)

import sys
import os
import importlib.util
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

# Import moduli locali
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

from ydea_common import Logger, ConfigLoader  # type: ignore

# Import ydea-toolkit.py (hyphenated name requires importlib)
ydea_toolkit_path = script_dir / "ydea-toolkit.py"
spec = importlib.util.spec_from_file_location("ydea_toolkit", ydea_toolkit_path)
if spec and spec.loader:
    ydea_toolkit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ydea_toolkit)  # type: ignore
else:
    raise ImportError("Cannot load ydea-toolkit.py")

# Estrai classi necessarie
YdeaAPI = ydea_toolkit.YdeaAPI
TicketOperations = ydea_toolkit.TicketOperations
TrackingSystem = ydea_toolkit.TrackingSystem


# ===== CONFIGURATION =====

CONFIG_FILE = script_dir.parent / "config" / "premium-mon-config.json"


# ===== FUNZIONI UTILITY =====

def determine_tipo(service: str, output: str, host: str, config: Dict[str, Any]) -> str:
    """Determine ticket type based on service/output/host
    
    Args:
        service: CheckMK service name
        output: Alarm output
        host: Host name
        config: Configuration loaded
    
    Returns:
        Ydea type determined"""
    # Combine all fields in lowercase for matching
    search_text = f"{service} {output} {host}".lower()
    
    # Check each type defined in config
    tipologie = config.get('tipologie', {})
    
    for tipo_key, tipo_data in tipologie.items():
        keywords = tipo_data.get('keywords', [])
        
        # Check if any keywords match
        for keyword in keywords:
            if keyword.lower() in search_text:
                return tipo_data.get('tipo_ydea', config.get('default_tipo', 'Assistenza'))
    
    # Default if no match found
    return config.get('default_tipo', 'Assistenza')


def get_state_icon(state: str) -> str:
    """Get emoji for CheckMK status
    
    Args:
        state: CheckMK status (DOWN, CRITICAL, WARNING, etc.)
    
    Returns:
        Matching emoji"""
    state_upper = state.upper()
    
    if state_upper in ('DOWN', 'CRITICAL'):
        return ''
    elif state_upper == 'WARNING':
        return ''
    else:
        return 'ℹ'


def build_ticket_title(host: str, service: str, state: str, host_ip: Optional[str] = None) -> str:
    """Build ticket title
    
    Args:
        host: Host name
        service: Service name
        state: Alarm state
        host_ip: host IP (optional)
    
    Returns:
        Formatted title"""
    title = f"[{state}] {host}"
    
    if service and service != "Host":
        title += f" - {service}"
    
    if host_ip:
        title += f" [IP={host_ip}]"
    
    return title


def build_private_note(
    host: str,
    service: str,
    state: str,
    output: str,
    host_ip: Optional[str] = None
) -> str:
    """Build HTML private note with alarm details
    
    Args:
        host: Host name
        service: Service name
        state: Alarm state
        output: Alarm output
        host_ip: host IP (optional)
    
    Returns:
        HTML private note"""
    state_icon = get_state_icon(state)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    note = f"""<p><strong>{state_icon} Alarm from CheckMK Monitoring</strong></p>
<ul>
<li><strong>Host:</strong> {host}</li>
<li><strong>Service:</strong> {service or 'Host Check'}</li>
<li><strong>State:</strong> {state}</li>
<li><strong>IP:</strong> {host_ip or 'N/A'}</li>
<li><strong>Date/Time:</strong> {timestamp}</li>
</ul>
<p><strong>Output:</strong></p>
<pre>{output}</pre>
<p><em>Ticket automatically created by the CheckMK monitoring system</em></p>"""
    
    return note


# ===== MAIN =====

def main():
    """Main function"""
    
    # Parse argomenti
    if len(sys.argv) < 5:
        print(" Uso: create_monitoring_ticket.py <HOST> <SERVICE> <STATE> <OUTPUT> [HOST_IP]")
        print("")
        print("Esempio:")
        print("  create_monitoring_ticket.py 'mail.example.com' 'HTTP' 'CRITICAL' 'Connection timeout' '1.2.3.4'")
        sys.exit(1)
    
    cmk_host = sys.argv[1]
    cmk_service = sys.argv[2]
    cmk_state = sys.argv[3]
    cmk_output = sys.argv[4]
    cmk_hostip = sys.argv[5] if len(sys.argv) > 5 else None
    
    Logger.info("=== Creazione ticket da CheckMK ===")
    Logger.info(f"Host: {cmk_host}")
    Logger.info(f"Service: {cmk_service}")
    Logger.info(f"State: {cmk_state}")
    Logger.info(f"Output: {cmk_output}")
    Logger.info(f"IP: {cmk_hostip or 'N/A'}")
    
    # Load configuration
    if not CONFIG_FILE.exists():
        Logger.error(f"File configurazione non trovato: {CONFIG_FILE}")
        sys.exit(1)
    
    try:
        config = ConfigLoader.load_json(str(CONFIG_FILE))
    except Exception as e:
        Logger.error(f"Errore caricamento configurazione: {e}")
        sys.exit(1)
    
    # Extract parameters from config
    anagrafica_id = config.get('anagrafica_id')
    priorita_id = config.get('priorita_id')
    fonte = config.get('fonte', 'CheckMK')
    sla_id = config.get('sla_id')
    assegnatoa_id = config.get('assegnatoa_id')
    
    Logger.debug(f"Config: anagrafica={anagrafica_id}, priorita={priorita_id}, sla={sla_id}, assegnatoa={assegnatoa_id}")
    
    # Determina tipologia
    tipo = determine_tipo(cmk_service, cmk_output, cmk_host, config)
    Logger.info(f"Tipologia determinata: {tipo}")
    
    # Costruisci titolo e descrizione
    titolo = build_ticket_title(cmk_host, cmk_service, cmk_state, cmk_hostip)
    descrizione = "Allarme da sistema di monitoraggio CheckMK"
    
    Logger.info(f"Titolo: {titolo}")
    
    # Inizializza API e tracking
    api = YdeaAPI()
    tracking = TrackingSystem()
    
    # Costruisci body ticket base
    ticket_body = {
        "titolo": titolo,
        "descrizione": descrizione,
        "anagrafica_id": anagrafica_id,
        "priorita_id": priorita_id,
        "fonte": fonte,
        "tipo": tipo
    }
    
    # Aggiungi campi opzionali se presenti
    if assegnatoa_id:
        ticket_body["assegnatoa"] = [assegnatoa_id]
    
    if sla_id:
        ticket_body["sla_id"] = sla_id
    
    Logger.debug(f"Body: {ticket_body}")
    
    # Crea ticket
    Logger.info("Creazione ticket in corso...")
    
    try:
        # Ensure valid token
        api.ensure_token()
        
        # API call to create tickets
        response, status_code = api.api_call("POST", "/ticket", ticket_body)
        
        # Extract created ticket ID
        ticket_id = response.get('id') or response.get('ticket_id') or response.get('data', {}).get('id')
        ticket_code = response.get('codice') or response.get('code') or response.get('data', {}).get('codice')
        
        if ticket_id:
            Logger.success(" Ticket creato con successo!")
            Logger.success(f"   ID: {ticket_id}")
            Logger.success(f"   Codice: {ticket_code or 'N/A'}")
            Logger.success(f"   Link: https://my.ydea.cloud/ticket/{ticket_id}")
            
            # Add private note with alarm details
            Logger.info("Aggiunta nota privata con dettagli allarme...")
            
            nota_privata = build_private_note(cmk_host, cmk_service, cmk_state, cmk_output, cmk_hostip)
            note_user_id = assegnatoa_id or 12336
            
            note_body = {
                "ticket_id": ticket_id,
                "atk": {
                    "descrizione": nota_privata,
                    "pubblico": False,
                    "creatoda": note_user_id
                }
            }
            
            try:
                api.api_call("POST", "/ticket/atk", note_body)
                Logger.success(" Nota privata aggiunta")
            except Exception as e:
                Logger.warn(f"  Nota privata non aggiunta (ticket comunque creato): {e}")
            
            # Track the ticket
            tracking.track_ticket(
                ticket_id,
                ticket_code or f"TK-{ticket_id}",
                cmk_host,
                cmk_service,
                cmk_output
            )
            
            # Output for CheckMK
            print(f"TICKET_ID={ticket_id}")
            print(f"TICKET_CODE={ticket_code}")
            
            sys.exit(0)
        else:
            Logger.error(" Errore nella creazione del ticket")
            print(response)
            sys.exit(1)
    
    except Exception as e:
        Logger.error(f" Errore nella creazione del ticket: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
