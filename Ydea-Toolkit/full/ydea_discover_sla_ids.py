#!/usr/bin/env python3
"""ydea_discover_sla_ids.py - Discover IDs by categories, subcategories and custom SLA

Used to find IDs needed for ticket management with Premium_Mon SLA.
Query Ydea API and generate configuration JSON files.

Usage:
    ydea_discover_sla_ids.py

Outputs:
    - sla-premium-mon-ids.json: Configuration file with IDs found
    - *-full-dump.json: Full dumps for debugging

Version: 1.0.0 (ported from Bash)"""

VERSION = "1.0.0"

import sys
import json
import importlib.util
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

# Import moduli locali
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

from ydea_common import Logger  # type: ignore

# Import ydea-toolkit.py
ydea_toolkit_path = script_dir / "ydea-toolkit.py"
spec = importlib.util.spec_from_file_location("ydea_toolkit", ydea_toolkit_path)
if spec and spec.loader:
    ydea_toolkit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ydea_toolkit)  # type: ignore
else:
    raise ImportError("Cannot load ydea-toolkit.py")

YdeaAPI = ydea_toolkit.YdeaAPI


# ===== CONFIGURATION =====

OUTPUT_FILE = script_dir / "sla-premium-mon-ids.json"

# Categories to search
MACRO_CATEGORY = "Premium_Mon"
SUBCATEGORIES = [
    "Centrale telefonica NethVoice",
    "Firewall UTM NethSecurity",
    "Collaboration Suite NethService",
    "Computer client",
    "Server",
    "Apparati di rete - Networking",
    "Hypervisor",
    "Consulenza tecnica specialistica",
]

SLA_NAME = "TK25/003209 SLA Personalizzata"


# ===== FUNZIONI HELPER =====

def print_header(title: str):
    """Print formatted header"""
    print()
    print("=" * 64)
    print(f"  {title}")
    print("=" * 64)
    print()


def save_dump(filename: str, data: Dict[str, Any]):
    """Save full dump for debugging"""
    dump_path = script_dir / filename
    with open(dump_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    Logger.debug(f"Dump completo salvato in {filename}")


# ===== DISCOVERY CATEGORIE =====

def discover_categories() -> Dict[str, Any]:
    """Discovery categories and subcategories
    
    Returns:
        Dictionary with macro_category and subcategories"""
    print_header(" DISCOVERY CATEGORIE E SOTTOCATEGORIE")
    
    Logger.info("Recupero lista categorie da Ydea API...")
    
    try:
        api = YdeaAPI()
        categories_data, status_code = api.api_call("GET", "/categories")
        
        if status_code not in [200, 201] or not categories_data:
            Logger.error("Nessuna categoria trovata o errore nella chiamata API")
            return {}
        
        # Salva dump completo
        save_dump("categories-full-dump.json", categories_data)
        
        # Cerca macro categoria
        macro_cat_id = None
        objs = categories_data.get("objs", [])
        
        for cat in objs:
            if cat.get("nome") == MACRO_CATEGORY:
                macro_cat_id = cat.get("id")
                break
        
        if macro_cat_id:
            Logger.success(f"Macro categoria '{MACRO_CATEGORY}' trovata → ID: {macro_cat_id}")
        else:
            Logger.warn(f"Macro categoria '{MACRO_CATEGORY}' non trovata direttamente")
            Logger.info("Elenco tutte le categorie disponibili:")
            for cat in objs:
                print(f"  {cat.get('id')} → {cat.get('nome')}")
        
        # Cerca sottocategorie
        subcategory_list = []
        found_count = 0
        
        print()
        Logger.info("Ricerca sottocategorie...")
        print()
        
        for subcat_name in SUBCATEGORIES:
            subcat_id = None
            for cat in objs:
                if cat.get("nome") == subcat_name:
                    subcat_id = cat.get("id")
                    break
            
            if subcat_id:
                subcategory_list.append({"name": subcat_name, "id": subcat_id})
                print(f"   '{subcat_name}' → ID: {subcat_id}")
                found_count += 1
            else:
                print(f"   '{subcat_name}' → NON TROVATA")
        
        print()
        Logger.info(f"Sottocategorie trovate: {found_count}/{len(SUBCATEGORIES)}")
        
        # Build outputs
        result = {}
        if macro_cat_id:
            result["macro_category"] = {"id": macro_cat_id, "name": MACRO_CATEGORY}
        result["subcategories"] = subcategory_list
        
        return result
        
    except Exception as e:
        Logger.error(f"Errore durante discovery categorie: {e}")
        return {}


# ===== DISCOVERY SLA =====

def discover_sla() -> Dict[str, Any]:
    """Custom SLA discovery
    
    Returns:
        Dictionary with sla info"""
    print_header(" DISCOVERY SLA PERSONALIZZATA")
    
    Logger.info("Recupero lista SLA da Ydea API...")
    
    try:
        api = YdeaAPI()
        
        # Prova endpoint /sla
        sla_data, status_code = api.api_call("GET", "/sla")
        
        if status_code not in [200, 201] or not sla_data or not sla_data.get("objs"):
            Logger.warn("Nessuna SLA trovata o endpoint non disponibile")
            # Prova endpoint alternativo /slas
            sla_data, status_code = api.api_call("GET", "/slas")
        
        if status_code not in [200, 201] or not sla_data:
            Logger.warn("Nessun endpoint SLA disponibile")
            return {}
        
        # Salva dump completo
        save_dump("sla-full-dump.json", sla_data)
        
        # Cerca SLA specifica
        sla_id = None
        objs = sla_data.get("objs", [])
        
        for sla in objs:
            sla_nome = sla.get("nome") or sla.get("name") or sla.get("title")
            if sla_nome == SLA_NAME:
                sla_id = sla.get("id")
                break
        
        if sla_id:
            Logger.success(f"SLA '{SLA_NAME}' trovata → ID: {sla_id}")
        else:
            Logger.warn(f"SLA '{SLA_NAME}' non trovata direttamente")
            Logger.info("Elenco tutte le SLA disponibili:")
            for sla in objs:
                sla_nome = sla.get("nome") or sla.get("name") or sla.get("title")
                print(f"  {sla.get('id')} → {sla_nome}")
            
            # Try partial search
            Logger.info("Tentativo ricerca per codice 'TK25/003209'...")
            for sla in objs:
                sla_nome = sla.get("nome") or sla.get("name") or sla.get("title") or ""
                if "TK25/003209" in sla_nome:
                    sla_id = sla.get("id")
                    Logger.success(f"SLA trovata tramite ricerca parziale → ID: {sla_id}")
                    break
        
        # Build outputs
        result = {}
        if sla_id:
            result["sla"] = {"id": sla_id, "name": SLA_NAME}
        
        return result
        
    except Exception as e:
        Logger.error(f"Errore durante discovery SLA: {e}")
        return {}


# ===== DISCOVERY PRIORITÀ =====

def discover_priorities() -> Dict[str, Any]:
    """Discovery priority
    
    Returns:
        Dictionary with low_priority info"""
    print_header(" DISCOVERY PRIORITÀ")
    
    Logger.info("Recupero lista priorità da Ydea API...")
    
    try:
        api = YdeaAPI()
        priorities_data, status_code = api.api_call("GET", "/priorities")
        
        if status_code not in [200, 201] or not priorities_data:
            Logger.warn("Nessuna priorità trovata o endpoint non disponibile")
            return {}
        
        # Salva dump completo
        save_dump("priorities-full-dump.json", priorities_data)
        
        # Cerca priorità "Bassa"
        low_priority_id = None
        objs = priorities_data.get("objs", [])
        
        for priority in objs:
            priority_nome = priority.get("nome") or priority.get("name")
            if priority_nome in ["Bassa", "Low"]:
                low_priority_id = priority.get("id")
                break
        
        if low_priority_id:
            Logger.success(f"Priorità 'Bassa' trovata → ID: {low_priority_id}")
        else:
            Logger.warn("Priorità 'Bassa' non trovata")
            Logger.info("Elenco tutte le priorità disponibili:")
            for priority in objs:
                priority_nome = priority.get("nome") or priority.get("name")
                print(f"  {priority.get('id')} → {priority_nome}")
        
        # Build outputs
        result = {}
        if low_priority_id:
            result["low_priority"] = {"id": low_priority_id, "name": "Bassa"}
        
        return result
        
    except Exception as e:
        Logger.error(f"Errore durante discovery priorità: {e}")
        return {}


# ===== MAIN =====

def main():
    """Main function"""
    print_header(" YDEA SLA DISCOVERY TOOL")
    
    Logger.info("Inizio discovery per SLA Premium_Mon...")
    Logger.info(f"Output verrà salvato in: {OUTPUT_FILE}")
    
    # Verify authentication
    try:
        api = YdeaAPI()
        if not api.ensure_token():
            Logger.error("Impossibile autenticarsi a Ydea API")
            Logger.error("Verifica YDEA_ID e YDEA_API_KEY nel file .env")
            sys.exit(1)
        
        Logger.success("Autenticazione completata")
        
    except Exception as e:
        Logger.error(f"Errore autenticazione: {e}")
        sys.exit(1)
    
    # Discovery categorie
    categories_json = discover_categories()
    
    # Discovery SLA
    sla_json = discover_sla()
    
    # Discovery priorità
    priorities_json = discover_priorities()
    
    # Combine all results
    print_header(" GENERAZIONE FILE CONFIGURAZIONE")
    
    final_json = {
        "discovery_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "description": "ID per gestione ticket con SLA Premium_Mon",
        "macro_category": categories_json.get("macro_category"),
        "subcategories": categories_json.get("subcategories", []),
        "sla": sla_json.get("sla"),
        "low_priority": priorities_json.get("low_priority")
    }
    
    # Save the file
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_json, f, indent=2, ensure_ascii=False)
    
    print_header(" DISCOVERY COMPLETATO")
    
    Logger.success(f"File di configurazione creato: {OUTPUT_FILE}")
    print()
    print("Contenuto:")
    print(json.dumps(final_json, indent=2, ensure_ascii=False))
    print()
    
    # Check completeness
    missing_items = []
    
    if not final_json.get("macro_category", {}).get("id"):
        missing_items.append("Macro categoria Premium_Mon")
    
    subcat_count = len(final_json.get("subcategories", []))
    if subcat_count < len(SUBCATEGORIES):
        missing_items.append(f"Alcune sottocategorie ({subcat_count}/{len(SUBCATEGORIES)} trovate)")
    
    if not final_json.get("sla", {}).get("id"):
        missing_items.append("SLA personalizzata TK25/003209")
    
    if missing_items:
        print()
        Logger.warn("  ATTENZIONE: Alcuni elementi non sono stati trovati:")
        for item in missing_items:
            print(f"  • {item}")
        print()
        Logger.info("Controlla i file *-full-dump.json per verificare i dati disponibili nell'API")
        sys.exit(1)
    else:
        print()
        Logger.success(" Tutti gli elementi richiesti sono stati trovati!")
        print()
        Logger.info("Prossimi passi:")
        print("  1. Verifica il contenuto di:", OUTPUT_FILE)
        print("  2. Integra questi ID negli script di notifica CheckMK")
        print("  3. Implementa la logica di mapping sottocategoria → tipo allarme")


if __name__ == "__main__":
    main()
