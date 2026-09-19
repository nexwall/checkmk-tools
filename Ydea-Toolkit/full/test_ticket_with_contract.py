#!/usr/bin/env python3
"""test_ticket_with_contract.py - Test ticket creation with associated contract

Prerequisites:
1. Contract created in Ydea UI for registry number 2339268
2. Contract with "Premium_Mon" SLA configured
3. Contract ID passed as argument

Usage:
    test_ticket_with_contract.py <contract_id>

Version: 1.0.0"""

import sys
import json
import time
import importlib.util
from datetime import datetime
from pathlib import Path

# Import ydea-toolkit
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

ydea_toolkit_path = script_dir / "ydea-toolkit.py"
spec = importlib.util.spec_from_file_location("ydea_toolkit", ydea_toolkit_path)
if spec and spec.loader:
    ydea_toolkit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ydea_toolkit)  # type: ignore
else:
    raise ImportError("Cannot load ydea-toolkit.py")

YdeaAPI = ydea_toolkit.YdeaAPI  # type: ignore
Logger = ydea_toolkit.Logger    # type: ignore

# Costanti
ANAGRAFICA_ID = 2339268


def main():
    if len(sys.argv) < 2:
        print(" Errore: Devi specificare l'ID del contratto")
        print("\nUsage: test_ticket_with_contract.py <contract_id>")
        sys.exit(1)
    
    contract_id = sys.argv[1]
    logger = Logger()
    
    print("=" * 60)
    print(" Test Creazione Ticket con Contratto Associato")
    print("=" * 60)
    print()
    
    try:
        api = YdeaAPI()
        
        # Step 1: Check existence of contract
        print(f" Step 1: Verifica esistenza contratto ID {contract_id}...")
        contract_data, status = api.api_call("GET", f"/contratto/{contract_id}")
        
        if status != 200 or not contract_data:
            print(f" Errore: Contratto {contract_id} non trovato!")
            sys.exit(1)
        
        contract_name = contract_data.get("nome", "N/A")
        contract_azienda = contract_data.get("azienda_id", 0)
        
        print(f"    Contratto trovato: {contract_name}")
        print(f"    Azienda ID: {contract_azienda}")
        
        if int(contract_azienda) != ANAGRAFICA_ID:
            print(f" Errore: Il contratto non appartiene all'anagrafica {ANAGRAFICA_ID}!")
            sys.exit(1)
            
        print()
        
        # Step 2: Create test tickets
        print(" Step 2: Creazione ticket di test con contratto...")
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ticket_payload = {
            "titolo": f"TEST Ticket con Contratto - {timestamp}",
            "descrizione": f"Dettagli test: Contratto ID {contract_id}, Contratto {contract_name}",
            "anagrafica_id": ANAGRAFICA_ID,
            "contrattoId": int(contract_id),
            "priorita_id": 30,
            "fonte": "Partner portal",
            "tipo": "Server"
        }
        
        ticket_data, status = api.api_call("POST", "/ticket", ticket_payload)
        
        if status not in [200, 201]:
            print(f" Errore creazione ticket: {status}")
            print(json.dumps(ticket_data, indent=2))
            sys.exit(1)
            
        ticket_id = ticket_data.get("id")
        ticket_codice = ticket_data.get("codice", "N/A")
        print(f"    Ticket creato: ID {ticket_id} - Codice {ticket_codice}")
        print()
        
        # Step 3: Verify association
        print(" Step 3: Verifica dettagli ticket creato...")
        time.sleep(2)  # Attendi propagazione
        
        details, status = api.api_call("GET", f"/ticket/{ticket_id}")
        if status != 200:
            print(" Errore recupero dettagli ticket")
            sys.exit(1)
            
        ticket_info = details.get("ticket", {})
        actual_contract_id = str(ticket_info.get("contrattoId", "0"))
        actual_contract_codice = ticket_info.get("contrattoCodice", "N/A")
        
        print(f"   Contratto nel ticket: {actual_contract_id} ({actual_contract_codice})")
        
        if actual_contract_id == str(contract_id):
            print("\n SUCCESSO: Il contratto è stato associato correttamente!")
            print(f"   Verifica manuale: https://my.ydea.cloud/ticket/{ticket_id}")
        else:
            print("\n FALLIMENTO: Il contratto non corrisponde")
            print(f"   Atteso: {contract_id}")
            print(f"   Trovato: {actual_contract_id}")
            
    except Exception as e:
        print(f" Errore imprevisto: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
