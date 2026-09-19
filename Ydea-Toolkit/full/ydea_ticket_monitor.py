#!/usr/bin/env python3
"""ydea_ticket_monitor.py - Automatic tracking ticket status monitoring

Periodically updates the status of tickets and removes old resolved ones.
Detect changes in:
- Ticket status
- Description
- Priorities
- Assignment

Usage:
    ydea_ticket_monitor.py

Version: 1.0.0 (ported from Bash)"""

VERSION = "1.0.0"  # Versione script (aggiornare ad ogni modifica)

import sys
import os
import importlib.util
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

# Import moduli locali
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

from ydea_common import Logger  # type: ignore

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
TrackingSystem = ydea_toolkit.TrackingSystem


# ===== CONFIGURATION =====

CLEANUP_MARKER = Path("/tmp/ydea_last_cleanup")
CLEANUP_INTERVAL_HOURS = 6


# ===== FUNZIONI UTILITY =====

def log_ticket_event(event_type: str, ticket_id: int, details: str = ""):
    """Log ticket event
    
    Args:
        event_type: Event type (RESOLVED, STATUS-CHANGED, etc.)
        ticket_id: Ticket ID
        details: Additional details"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] [TICKET-EVENT] [{event_type}] #{ticket_id} {details}")


def get_tracking_stats(tracking: TrackingSystem) -> Dict[str, int]:
    """Get tracking statistics
    
    Args:
        tracking: TrackingSystem instance
        
    Returns:
        Dict with total_tickets, open_tickets, resolved_tickets"""
    try:
        tracking_data = tracking.load_tracking()
        tickets = tracking_data.get('tickets', [])
        
        total = len(tickets)
        resolved = sum(1 for t in tickets if t.get('resolved_at') is not None)
        open_tickets = total - resolved
        
        return {
            'total_tickets': total,
            'open_tickets': open_tickets,
            'resolved_tickets': resolved
        }
    except Exception:
        return {'total_tickets': 0, 'open_tickets': 0, 'resolved_tickets': 0}


def get_previous_states(tracking: TrackingSystem) -> Dict[int, Dict[str, Any]]:
    """Get previous ticket statuses
    
    Args:
        tracking: TrackingSystem instance
        
    Returns:
        Dict with ticket_id as key and previous data as value"""
    previous = {}
    
    try:
        tracking_data = tracking.load_tracking()
        tickets = tracking_data.get('tickets', [])
        
        for ticket in tickets:
            if ticket.get('resolved_at') is None:  # Solo ticket aperti
                tid = ticket.get('ticket_id')
                if tid:
                    previous[tid] = {
                        'stato': ticket.get('stato', 'Sconosciuto'),
                        'descrizione': ticket.get('descrizione_ticket', ''),
                        'priorita': ticket.get('priorita', 'Normale'),
                        'assegnato': ticket.get('assegnatoA', 'Non assegnato'),
                        'host': ticket.get('host', ''),
                        'service': ticket.get('service', ''),
                        'codice': ticket.get('codice', '')
                    }
    except Exception:
        pass
    
    return previous


def detect_changes(
    ticket_id: int,
    prev_data: Dict[str, Any],
    current_data: Dict[str, Any]
):
    """Track and log changes in a ticket
    
    Args:
        ticket_id: Ticket ID
        prev_data: Previous data
        current_data: Current data from the API"""
    codice = prev_data.get('codice', '')
    host = prev_data.get('host', '')
    service = prev_data.get('service', '')
    
    prev_stato = prev_data.get('stato', 'NUOVO')
    prev_desc = prev_data.get('descrizione', '')
    prev_prio = prev_data.get('priorita', 'Normale')
    prev_assegnato = prev_data.get('assegnato', 'Non assegnato')
    
    current_stato = current_data.get('stato', 'Sconosciuto')
    current_desc = current_data.get('descrizione', '')
    current_prio = current_data.get('priorita', 'Normale')
    
    # Management assignedA (can be object or string)
    assigned = current_data.get('assegnatoA')
    if isinstance(assigned, dict):
        if assigned:
            current_assegnato = ', '.join(str(v) for v in assigned.values())
        else:
            current_assegnato = "Non assegnato"
    elif assigned:
        current_assegnato = str(assigned)
    else:
        current_assegnato = "Non assegnato"
    
    # Rileva modifica descrizione
    if prev_desc and current_desc != prev_desc:
        log_ticket_event("DESCRIZIONE-MODIFICATA", ticket_id, 
                        f"[{codice}] Host: {host}, Service: {service}")
    
    # Rileva modifica priorità
    if current_prio != prev_prio:
        log_ticket_event("PRIORITA-MODIFICATA", ticket_id,
                        f"[{codice}] {prev_prio} → {current_prio} - Host: {host}, Service: {service}")
    
    # Rileva cambio assegnazione
    if current_assegnato != prev_assegnato:
        log_ticket_event("ASSEGNAZIONE-MODIFICATA", ticket_id,
                        f"[{codice}] {prev_assegnato} → {current_assegnato} - Host: {host}, Service: {service}")
    
    # Rileva ticket risolto
    resolved_states = ['Effettuato', 'Chiuso', 'Completato', 'Risolto']
    if current_stato in resolved_states and prev_stato != current_stato:
        log_ticket_event("RISOLTO", ticket_id,
                        f"[{codice}] Host: {host}, Service: {service}, Stato: {prev_stato} → {current_stato}")
    # Detect state change (not resolved)
    elif prev_stato and prev_stato != "NUOVO" and prev_stato != current_stato:
        log_ticket_event("STATO-CAMBIATO", ticket_id,
                        f"[{codice}] {prev_stato} → {current_stato} (Host: {host}, Service: {service})")


def should_cleanup() -> bool:
    """Check if you need to run cleanup
    
    Returns:
        True if at least 6 hours have passed since the last cleanup"""
    if not CLEANUP_MARKER.exists():
        return True
    
    try:
        last_cleanup = int(CLEANUP_MARKER.read_text().strip())
        now = int(time.time())
        hours_since = (now - last_cleanup) / 3600
        return hours_since >= CLEANUP_INTERVAL_HOURS
    except Exception:
        return True


def mark_cleanup_done():
    """Mark cleanup as done"""
    try:
        CLEANUP_MARKER.write_text(str(int(time.time())))
    except Exception as e:
        Logger.warn(f"Impossibile aggiornare marker cleanup: {e}")


def get_hours_until_next_cleanup() -> int:
    """Calculate hours until the next cleanup
    
    Returns:
        Hours missing (0 if cleanup needed now)"""
    if not CLEANUP_MARKER.exists():
        return 0
    
    try:
        last_cleanup = int(CLEANUP_MARKER.read_text().strip())
        now = int(time.time())
        hours_since = (now - last_cleanup) / 3600
        hours_remaining = max(0.0, CLEANUP_INTERVAL_HOURS - hours_since)
        return int(hours_remaining)
    except Exception:
        return 0


# ===== MAIN =====

def main():
    """Main function"""
    
    Logger.info("=" * 60)
    Logger.info(" Avvio monitoraggio ticket tracciati")
    
    # Inizializza tracking e API
    tracking = TrackingSystem()
    api = YdeaAPI()
    
    # Mostra statistiche iniziali
    stats = get_tracking_stats(tracking)
    Logger.info(f" Stato: {stats['total_tickets']} totali "
               f"({stats['open_tickets']} aperti, {stats['resolved_tickets']} risolti)")
    
    # Salva stati precedenti
    previous_states = get_previous_states(tracking)
    
    Logger.info(" Aggiornamento stati ticket...")
    
    # Update ticket statuses
    try:
        tracking.update_tracked_tickets()
    except Exception as e:
        Logger.error(f"Errore aggiornamento tracking: {e}")
        sys.exit(1)
    
    # Ottieni dati aggiornati dall'API
    try:
        api.ensure_token()
        api_response, status_code = api.api_call("GET", "/tickets?limit=100")
        api_tickets = api_response.get('objs', [])
    except Exception as e:
        Logger.error(f"Errore recupero ticket da API: {e}")
        api_tickets = []
    
    # Rileva e logga cambiamenti
    for ticket_id, prev_data in previous_states.items():
        # Trova ticket corrispondente nell'API
        current_ticket = next(
            (t for t in api_tickets if t.get('id') == ticket_id),
            None
        )
        
        if current_ticket:
            detect_changes(ticket_id, prev_data, current_ticket)
    
    Logger.success(" Aggiornamento stati completato")
    
    # Cleanup old resolved tickets (every 6 hours)
    if should_cleanup():
        Logger.info(" Eseguo pulizia ticket risolti vecchi...")
        try:
            tracking.cleanup_tracking()
            mark_cleanup_done()
        except Exception as e:
            Logger.error(f"Errore durante cleanup: {e}")
    else:
        hours_remaining = get_hours_until_next_cleanup()
        Logger.info(f"  Cleanup non necessario (prossimo tra {hours_remaining}h)")
    
    Logger.success(" Monitoraggio completato")
    Logger.info("=" * 60)


if __name__ == "__main__":
    main()
