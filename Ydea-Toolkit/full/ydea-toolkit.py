#!/usr/bin/env python3
"""ydea-toolkit.py - Complete toolkit for Ydea API v2

Includes login, token management, CRUD ticket, tracking system, logging.
Python conversion of the original bash toolkit with full parity feature.

Version: 1.0.0"""

import os
import sys
import json
import time
import gzip
import shutil
import argparse
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone
from urllib.parse import urlencode

try:
    import requests
    from dotenv import load_dotenv
except ImportError:
    print(" Dipendenze mancanti. Installa con:")
    print("   pip3 install requests python-dotenv")
    sys.exit(127)

VERSION = "1.0.2"

# ===== GLOBAL CONFIGURATION =====

class YdeaConfig:
    """Ydea Toolkit configuration management"""
    
    def __init__(self):
        # Load .env only if critical variables not set
        if not os.getenv("YDEA_ID") or not os.getenv("YDEA_API_KEY"):
            script_dir = Path(__file__).resolve().parent
            env_files = [
                script_dir / ".env",
                Path("/opt/ydea-toolkit/.env")
            ]
            for env_file in env_files:
                if env_file.exists():
                    load_dotenv(env_file)
                    break
        
        # API Configuration
        self.BASE_URL = os.getenv("YDEA_BASE_URL", "https://my.ydea.cloud/app_api_v2")
        self.LOGIN_PATH = os.getenv("YDEA_LOGIN_PATH", "/login")
        
        # Credentials
        self.YDEA_ID = os.getenv("YDEA_ID", "")
        self.YDEA_API_KEY = os.getenv("YDEA_API_KEY", "")
        
        # User IDs for operations
        self.USER_ID_CREATE_TICKET = int(os.getenv("YDEA_USER_ID_CREATE_TICKET", "4675"))
        self.USER_ID_CREATE_NOTE = int(os.getenv("YDEA_USER_ID_CREATE_NOTE", "4675"))
        
        # Token management
        self.TOKEN_FILE = Path(os.getenv("YDEA_TOKEN_FILE", Path.home() / ".ydea_token.json"))
        self.EXPIRY_SKEW = int(os.getenv("YDEA_EXPIRY_SKEW", "60"))  # seconds
        
        # Logging
        self.DEBUG = os.getenv("YDEA_DEBUG", "0") == "1"
        self.LOG_FILE = Path(os.getenv("YDEA_LOG_FILE", "/var/log/ydea-toolkit.log"))
        self.LOG_MAX_SIZE = int(os.getenv("YDEA_LOG_MAX_SIZE", str(10 * 1024 * 1024)))  # 10MB
        self.LOG_LEVEL = os.getenv("YDEA_LOG_LEVEL", "INFO").upper()
        
        # Tracking
        self.TRACKING_FILE = Path(os.getenv("YDEA_TRACKING_FILE", "/var/log/ydea-tickets-tracking.json"))
        self.TRACKING_RETENTION_DAYS = int(os.getenv("YDEA_TRACKING_RETENTION_DAYS", "365"))
        
        # HTTP timeouts
        self.CONNECT_TIMEOUT = 10
        self.MAX_TIMEOUT = 30


config = YdeaConfig()


# ===== LOGGING SYSTEM =====

class YdeaLogger:
    """Logging system with rotation and levels"""
    
    def __init__(self):
        self.log_file = config.LOG_FILE
        self.max_size = config.LOG_MAX_SIZE
        self.debug_enabled = config.DEBUG
        self._setup_logger()
    
    def _setup_logger(self):
        """Setup logger Python standard"""
        level = getattr(logging, config.LOG_LEVEL, logging.INFO)
        logging.basicConfig(
            level=level,
            format='[%(asctime)s] [%(levelname)s] [PID:%(process)d] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.logger = logging.getLogger('ydea-toolkit')
    
    def rotate(self):
        """Log rotation if exceeds maximum size"""
        if not self.log_file.exists():
            return
        
        try:
            size = self.log_file.stat().st_size
            if size > self.max_size:
                rotated = self.log_file.with_suffix('.log.1')
                shutil.move(str(self.log_file), str(rotated))
                if rotated.exists():
                    with open(rotated, 'rb') as f_in:
                        with gzip.open(str(rotated) + '.gz', 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    rotated.unlink()
        except Exception:
            pass  # Fail silently su rotazione log
    
    def write(self, level: str, message: str):
        """Write log to file"""
        self.rotate()
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        pid = os.getpid()
        log_line = f"[{timestamp}] [{level}] [PID:{pid}] {message}\n"
        
        try:
            # Create directory if it does not exist
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_line)
        except Exception:
            pass  # Fail silently
    
    def debug(self, message: str):
        if self.debug_enabled:
            print(f" {message}", file=sys.stderr)
        self.write("DEBUG", message)
    
    def info(self, message: str):
        print(f"ℹ  {message}", file=sys.stderr)
        self.write("INFO", message)
    
    def success(self, message: str):
        print(f" {message}", file=sys.stderr)
        self.write("INFO", f"SUCCESS: {message}")
    
    def warn(self, message: str):
        print(f"  {message}", file=sys.stderr)
        self.write("WARN", message)
    
    def error(self, message: str):
        print(f" {message}", file=sys.stderr)
        self.write("ERROR", message)
    
    def api_call(self, method: str, url: str, status: Optional[int] = None):
        """Log chiamata API"""
        status_str = f"HTTP {status}" if status else "FAILED"
        self.write("API", f"{method} {url} → {status_str}")


logger = YdeaLogger()


# ===== TOKEN MANAGEMENT =====

class TokenManager:
    """JWT token management"""
    
    def __init__(self):
        self.token_file = config.TOKEN_FILE
    
    def save_token(self, token: str):
        """Save JWT token to file"""
        now = int(time.time())
        expires = now + 3600  # 1 ora
        
        token_data = {
            "token": token,
            "scheme": "Bearer",
            "obtained_at": now,
            "expires_at": expires
        }
        
        try:
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_file, 'w', encoding='utf-8') as f:
                json.dump(token_data, f, indent=2)
            
            expires_date = datetime.fromtimestamp(expires).strftime('%Y-%m-%d %H:%M:%S')
            logger.debug(f"Token salvato in {self.token_file} (scade: {expires_date})")
            logger.write("AUTH", f"Token ottenuto e salvato, scadenza: {expires_date}")
        except Exception as e:
            logger.error(f"Errore salvataggio token: {e}")
            raise
    
    def load_token(self) -> Optional[str]:
        """Load token from file"""
        if not self.token_file.exists():
            return None
        
        try:
            with open(self.token_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get("token")
        except Exception:
            return None
    
    def get_expires_at(self) -> int:
        """Get token expiration timestamp"""
        if not self.token_file.exists():
            return 0
        
        try:
            with open(self.token_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get("expires_at", 0)
        except Exception:
            return 0
    
    def is_fresh(self) -> bool:
        """Check if token is still valid"""
        if not self.token_file.exists():
            return False
        
        now = int(time.time())
        expires = self.get_expires_at()
        skew = config.EXPIRY_SKEW
        
        if now < (expires - skew):
            remaining = expires - now
            logger.debug(f"Token valido (scade tra {remaining} secondi)")
            return True
        else:
            logger.debug("Token scaduto o in scadenza")
            return False


token_manager = TokenManager()


# ===== YDEA API CLIENT =====

class YdeaAPI:
    """Ydea API Client v2"""
    
    def __init__(self):
        self.base_url = config.BASE_URL.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
    
    def login(self):
        """Log in and save token"""
        logger.info("Tentativo login a Ydea Cloud...")
        
        if not config.YDEA_ID or not config.YDEA_API_KEY:
            logger.error("YDEA_ID e YDEA_API_KEY non impostati")
            print("Esempio:", file=sys.stderr)
            print("  export YDEA_ID='tuo_id'", file=sys.stderr)
            print("  export YDEA_API_KEY='tua_chiave'", file=sys.stderr)
            sys.exit(2)
        
        url = f"{self.base_url}{config.LOGIN_PATH}"
        body = {
            "id": config.YDEA_ID,
            "api_key": config.YDEA_API_KEY
        }
        
        logger.debug(f"POST {url}")
        
        try:
            response = self.session.post(
                url,
                json=body,
                timeout=(config.CONNECT_TIMEOUT, config.MAX_TIMEOUT)
            )
            response.raise_for_status()
            
            logger.api_call("POST", url, response.status_code)
            
            data = response.json()
            token = data.get('token') or data.get('access_token') or data.get('jwt') or data.get('id_token')
            
            if not token:
                logger.error("Login fallito: risposta senza token")
                print(json.dumps(data, indent=2))
                sys.exit(1)
            
            token_manager.save_token(token)
            logger.success("Login effettuato (token valido ~1h)")
            
        except requests.RequestException as e:
            logger.error(f"Login fallito: {e}")
            logger.api_call("POST", url, None)
            sys.exit(1)
    
    def ensure_token(self):
        """Ensure token is valid, otherwise login"""
        if token_manager.is_fresh():
            logger.debug("Token ancora valido")
        else:
            logger.info("Token scaduto o mancante, effettuo il login...")
            self.login()
    
    def api_call(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[Any, Any]] = None
    ) -> Tuple[Dict[Any, Any], int]:
        """Generic API call with retry on 401
        
        Returns:
            Tuple[response_json, status_code]"""
        if not method or not path:
            logger.error("Uso: api_call(method, path, [json_body])")
            raise ValueError("Method e path obbligatori")
        
        self.ensure_token()
        token = token_manager.load_token()
        url = f"{self.base_url}/{path.lstrip('/')}"
        
        logger.debug(f"{method} {url}")
        if json_body:
            body_preview = json.dumps(json_body)[:200]
            logger.write("REQUEST", f"{method} {url} | Body: {body_preview}...")
        
        headers = {
            'Authorization': f'Bearer {token}'
        }
        
        try:
            response = self.session.request(
                method,
                url,
                json=json_body,
                headers=headers,
                timeout=(config.CONNECT_TIMEOUT, config.MAX_TIMEOUT)
            )
            
            status_code = response.status_code
            logger.api_call(method, url, status_code)
            
            # If 401, refresh token and retry
            if status_code == 401:
                logger.warn("Token scaduto (401), rinnovo e riprovo...")
                self.login()
                token = token_manager.load_token()
                headers['Authorization'] = f'Bearer {token}'
                
                response = self.session.request(
                    method,
                    url,
                    json=json_body,
                    headers=headers,
                    timeout=(config.CONNECT_TIMEOUT, config.MAX_TIMEOUT)
                )
                status_code = response.status_code
                logger.api_call(method, url, f"{status_code} (retry dopo refresh token)")
            
            logger.debug(f"HTTP {status_code}")
            
            # Log response (primi 500 caratteri)
            if config.DEBUG:
                try:
                    response_preview = response.text[:500]
                    logger.write("RESPONSE", f"{method} {url} → {status_code} | Body: {response_preview}...")
                except Exception:
                    pass
            
            # Show error if not 2xx
            if not (200 <= status_code < 300):
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message') or error_data.get('error') or str(error_data)[:200]
                except Exception:
                    error_msg = response.text[:200]
                logger.error(f"HTTP {status_code}: {error_msg}")
            
            response.raise_for_status()
            
            try:
                return response.json(), status_code
            except Exception:
                return {}, status_code
        
        except requests.RequestException as e:
            logger.error(f"API call fallita: {method} {url}")
            logger.error(f"Errore: {e}")
            logger.api_call(method, url, None)
            raise


api = YdeaAPI()


# ===== TICKET OPERATIONS =====

class TicketOperations:
    """CRUD operations on tickets"""
    
    @staticmethod
    def list_tickets(limit: int = 50, status: Optional[str] = None) -> Dict[Any, Any]:
        """List all tickets with optional filters"""
        path = f"/tickets?limit={limit}"
        if status:
            path += f"&status={status}"
        
        status_msg = f", status: {status}" if status else ""
        logger.info(f"Recupero ticket (limit: {limit}{status_msg})...")
        
        response, _ = api.api_call("GET", path)
        return response
    
    @staticmethod
    def get_ticket(ticket_id: int) -> Dict[Any, Any]:
        """Details of a single ticket"""
        if not ticket_id:
            logger.error("Ticket ID richiesto")
            raise ValueError("ticket_id obbligatorio")
        
        logger.info(f"Recupero ticket #{ticket_id}...")
        
        # The /tickets/{id} endpoint is not accessible, we use list and filter
        all_tickets_response = TicketOperations.list_tickets(limit=100)
        ticket_data = next(
            (t for t in all_tickets_response.get('objs', []) if t.get('id') == ticket_id),
            None
        )
        
        if not ticket_data:
            logger.error(f"Ticket #{ticket_id} non trovato")
            raise ValueError(f"Ticket {ticket_id} non trovato")
        
        return ticket_data
    
    @staticmethod
    def create_ticket(
        title: str,
        description: str = "",
        priority: str = "normal",
        sla_id: Optional[int] = None,
        tipo: Optional[str] = None,
        creatoda: Optional[int] = None
    ) -> Dict[Any, Any]:
        """Create a new ticket"""
        if not title:
            logger.error("Specifica almeno il titolo")
            raise ValueError("title obbligatorio")
        
        # Mappa priorità testuale a priority_id
        priority_map = {
            "low": 30,
            "bassa": 30,
            "normal": 20,
            "normale": 20,
            "medium": 20,
            "media": 20,
            "high": 10,
            "alta": 10,
            "urgent": 10,
            "urgente": 10,
            "critical": 10,
            "critica": 10
        }
        priority_num = priority_map.get(priority.lower(), 30)
        
        # Valori predefiniti
        azienda_str = os.getenv("YDEA_AZIENDA")
        if not azienda_str:
            raise ValueError("YDEA_AZIENDA non configurata nell'env file - impostare l'ID anagrafica azienda")
        azienda = int(azienda_str)
        contatto = int(os.getenv("YDEA_CONTATTO", "773763"))
        contratto_id = os.getenv("YDEA_CONTRATTO_ID")
        
        # Body base
        body = {
            "titolo": title,
            "testo": description,
            "priorita": priority_num,
            "azienda": azienda,
            "contatto": contatto,
            "anagrafica_id": azienda,
            "fonte": "Partner portal",
            "condizioneAddebito": "C"
        }
        
        # Aggiungi contrattoId se disponibile
        if contratto_id:
            body["contrattoId"] = int(contratto_id)
        
        # Aggiungi sla_id se fornito
        if sla_id and not contratto_id:
            body["sla_id"] = sla_id
        
        # Aggiungi tipo se fornito
        if tipo:
            body["tipo"] = tipo
        
        # Aggiungi creatoda se fornito
        if creatoda:
            body["creatoda"] = creatoda
        
        tipo_msg = f", tipo: {tipo}" if tipo else ""
        logger.info(f"Creazione ticket: {title} (priorità: {priority}{tipo_msg})")
        
        response, _ = api.api_call("POST", "/ticket", body)
        return response
    
    @staticmethod
    def update_ticket(ticket_id: int, json_updates: Dict[Any, Any]) -> Dict[Any, Any]:
        """Update a ticket"""
        if not ticket_id or not json_updates:
            logger.error("Specifica ticket_id e json_updates")
            raise ValueError("ticket_id e json_updates obbligatori")
        
        logger.info(f"Aggiornamento ticket #{ticket_id}...")
        response, _ = api.api_call("PATCH", f"/tickets/{ticket_id}", json_updates)
        return response
    
    @staticmethod
    def close_ticket(ticket_id: int, note: str = "Ticket chiuso") -> Dict[Any, Any]:
        """Chiudi un ticket"""
        if not ticket_id:
            logger.error("Specifica ticket_id")
            raise ValueError("ticket_id obbligatorio")
        
        body = {
            "status": "closed",
            "closing_note": note
        }
        
        logger.info(f"Chiusura ticket #{ticket_id}...")
        response, _ = api.api_call("PATCH", f"/tickets/{ticket_id}", body)
        return response
    
    @staticmethod
    def add_comment(ticket_id: int, comment: str, is_public: bool = False) -> Dict[Any, Any]:
        """Aggiungi commento a un ticket"""
        if not ticket_id or not comment:
            logger.error("Uso: add_comment(ticket_id, commento, [pubblico])")
            raise ValueError("ticket_id e comment obbligatori")
        
        user_id = config.USER_ID_CREATE_NOTE
        
        body = {
            "ticket_id": ticket_id,
            "atk": {
                "descrizione": comment,
                "pubblico": is_public,
                "creatoda": user_id
            }
        }
        
        logger.info(f"Aggiunta commento a ticket #{ticket_id} (pubblico: {is_public})...")
        response, _ = api.api_call("POST", "/ticket/atk", body)
        return response
    
    @staticmethod
    def search_tickets(query: str, limit: int = 20) -> Dict[Any, Any]:
        """Search tickets by text"""
        if not query:
            logger.error("Specifica una query di ricerca")
            raise ValueError("query obbligatoria")
        
        from urllib.parse import quote
        encoded_query = quote(query)
        
        logger.info(f"Ricerca ticket: '{query}'...")
        response, _ = api.api_call("GET", f"/tickets?search={encoded_query}&limit={limit}")
        return response
    
    @staticmethod
    def list_categories() -> Dict[Any, Any]:
        """List of available categories"""
        logger.info("Recupero categorie...")
        response, _ = api.api_call("GET", "/categories")
        return response
    
    @staticmethod
    def list_users(limit: int = 50) -> Dict[Any, Any]:
        """User list"""
        logger.info(f"Recupero utenti (limit: {limit})...")
        response, _ = api.api_call("GET", f"/users?limit={limit}")
        return response


tickets = TicketOperations()


# ===== TRACKING SYSTEM =====

class TrackingSystem:
    """Ticket tracking system for status monitoring"""
    
    def __init__(self):
        self.tracking_file = config.TRACKING_FILE
    
    def init_tracking_file(self):
        """Initialize tracking file if it does not exist"""
        if not self.tracking_file.exists():
            self.tracking_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.tracking_file, 'w', encoding='utf-8') as f:
                json.dump({"tickets": [], "last_update": ""}, f, indent=2)
            logger.debug(f"File tracking inizializzato: {self.tracking_file}")
    
    def track_ticket(
        self,
        ticket_id: int,
        codice: str = "",
        host: str = "",
        service: str = "",
        description: str = ""
    ):
        """Aggiungi ticket al tracking"""
        self.init_tracking_file()
        
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        
        # Retrieve ticket details from API (use /tickets?limit=100 because /tickets/{id} not accessible)
        try:
            all_tickets = tickets.list_tickets(limit=100)
            ticket_data = next(
                (t for t in all_tickets.get('objs', []) if t.get('id') == ticket_id),
                {}
            )
        except Exception:
            ticket_data = {}
        
        stato = ticket_data.get('stato', 'Sconosciuto')
        titolo = ticket_data.get('titolo', '')
        descrizione_ticket = ticket_data.get('descrizione', '')
        priorita = ticket_data.get('priorita', 'Normale')
        
        # Management assignedA (can be object or string)
        assigned = ticket_data.get('assegnatoA')
        if isinstance(assigned, dict):
            if assigned:
                assegnato_a = ', '.join(str(v) for v in assigned.values())
            else:
                assegnato_a = "Non assegnato"
        elif assigned:
            assegnato_a = str(assigned)
        else:
            assegnato_a = "Non assegnato"
        
        new_entry = {
            "ticket_id": ticket_id,
            "codice": codice,
            "host": host,
            "service": service,
            "description": description,
            "titolo": titolo,
            "stato": stato,
            "descrizione_ticket": descrizione_ticket,
            "priorita": priorita,
            "assegnatoA": assegnato_a,
            "created_at": now,
            "last_update": now,
            "resolved_at": None,
            "checks_count": 1
        }
        
        # Leggi tracking esistente
        with open(self.tracking_file, 'r', encoding='utf-8') as f:
            tracking = json.load(f)
        
        # Check if already tracked
        existing = next((t for t in tracking['tickets'] if t['ticket_id'] == ticket_id), None)
        
        if existing:
            logger.warn(f"Ticket #{ticket_id} già tracciato, aggiorno contatore")
            existing['checks_count'] += 1
            existing['last_update'] = now
        else:
            logger.info(f"Aggiunto ticket #{ticket_id} al tracking")
            tracking['tickets'].append(new_entry)
        
        tracking['last_update'] = now
        
        with open(self.tracking_file, 'w', encoding='utf-8') as f:
            json.dump(tracking, f, indent=2, ensure_ascii=False)
        
        logger.success(f"Ticket #{ticket_id} ({codice}) tracciato - Host: {host}, Service: {service}")
    
    def update_tracked_tickets(self):
        """Update status of all tracked tickets"""
        self.init_tracking_file()
        
        count = 0
        updated = 0
        resolved = 0
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        
        logger.info("Aggiornamento stati ticket tracciati...")
        
        with open(self.tracking_file, 'r', encoding='utf-8') as f:
            tracking = json.load(f)
        
        # Retrieve all tickets from the API
        try:
            all_tickets_response = tickets.list_tickets(limit=100)
            all_tickets = {t['id']: t for t in all_tickets_response.get('objs', [])}
        except Exception:
            logger.error("Errore recupero ticket dall'API")
            return
        
        for ticket_entry in tracking['tickets']:
            if ticket_entry.get('resolved_at'):
                continue  # Skip ticket già risolti
            
            ticket_id = ticket_entry['ticket_id']
            count += 1
            
            logger.debug(f"Controllo ticket #{ticket_id}...")
            
            ticket_data = all_tickets.get(ticket_id, {})
            
            if not ticket_data:
                logger.warn(f" Ticket #{ticket_id} non trovato, potrebbe essere stato eliminato - contrassegnato come risolto")
                ticket_entry['stato'] = 'Eliminato'
                ticket_entry['resolved_at'] = now
                ticket_entry['last_update'] = now
                resolved += 1
                continue
            
            stato = ticket_data.get('stato', 'Sconosciuto')
            descrizione_ticket = ticket_data.get('descrizione', '')
            priorita = ticket_data.get('priorita', 'Normale')
            
            assigned = ticket_data.get('assegnatoA')
            if isinstance(assigned, dict):
                if assigned:
                    assegnato_a = ', '.join(str(v) for v in assigned.values())
                else:
                    assegnato_a = "Non assegnato"
            elif assigned:
                assegnato_a = str(assigned)
            else:
                assegnato_a = "Non assegnato"
            
            # Check if resolved
            if stato in ['Effettuato', 'Chiuso', 'Completato', 'Risolto']:
                logger.success(f"  Ticket #{ticket_id} RISOLTO (stato: {stato})")
                ticket_entry['stato'] = stato
                ticket_entry['descrizione_ticket'] = descrizione_ticket
                ticket_entry['priorita'] = priorita
                ticket_entry['assegnatoA'] = assegnato_a
                ticket_entry['resolved_at'] = now
                ticket_entry['last_update'] = now
                resolved += 1
            else:
                # Update status
                ticket_entry['stato'] = stato
                ticket_entry['descrizione_ticket'] = descrizione_ticket
                ticket_entry['priorita'] = priorita
                ticket_entry['assegnatoA'] = assegnato_a
                ticket_entry['last_update'] = now
                ticket_entry['checks_count'] += 1
                updated += 1
        
        tracking['last_update'] = now
        
        with open(self.tracking_file, 'w', encoding='utf-8') as f:
            json.dump(tracking, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Aggiornamento completato: {count} ticket controllati, {updated} aggiornati, {resolved} risolti")
    
    def cleanup_resolved_tickets(self):
        """Pulisci ticket risolti vecchi"""
        self.init_tracking_file()
        
        retention_seconds = config.TRACKING_RETENTION_DAYS * 86400
        now_epoch = int(time.time())
        cutoff_epoch = now_epoch - retention_seconds
        cutoff_date = datetime.fromtimestamp(cutoff_epoch, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        
        logger.info(f"Pulizia ticket risolti più vecchi di {config.TRACKING_RETENTION_DAYS} giorni (prima di {cutoff_date})...")
        
        with open(self.tracking_file, 'r', encoding='utf-8') as f:
            tracking = json.load(f)
        
        before_count = len(tracking['tickets'])
        
        # Filter tickets to keep
        tracking['tickets'] = [
            t for t in tracking['tickets']
            if not t.get('resolved_at') or t.get('resolved_at', '') > cutoff_date
        ]
        
        after_count = len(tracking['tickets'])
        removed = before_count - after_count
        
        with open(self.tracking_file, 'w', encoding='utf-8') as f:
            json.dump(tracking, f, indent=2, ensure_ascii=False)
        
        if removed > 0:
            logger.success(f"Rimossi {removed} ticket risolti vecchi")
        else:
            logger.info("Nessun ticket da rimuovere")
    
    def show_tracking_stats(self):
        """Mostra statistiche ticket tracciati"""
        self.init_tracking_file()
        
        with open(self.tracking_file, 'r', encoding='utf-8') as f:
            tracking = json.load(f)
        
        total = len(tracking['tickets'])
        open_tickets = [t for t in tracking['tickets'] if not t.get('resolved_at')]
        resolved_tickets = [t for t in tracking['tickets'] if t.get('resolved_at')]
        
        print(" Statistiche Ticket Tracking")
        print("══════════════════════════════")
        print(f"Totale ticket tracciati: {total}")
        print(f"   Aperti: {len(open_tickets)}")
        print(f"   Risolti: {len(resolved_tickets)}")
        print("")
        
        if open_tickets:
            print(" Ticket Aperti:")
            for t in open_tickets:
                print(f"  [#{t['ticket_id']}] {t['codice']} - {t['host']}/{t['service']} - Stato: {t['stato']} - Creato: {t['created_at']}")
            print("")
        
        if resolved_tickets:
            print(" Ultimi 5 Ticket Risolti:")
            sorted_resolved = sorted(resolved_tickets, key=lambda x: x.get('resolved_at', ''), reverse=True)[:5]
            for t in sorted_resolved:
                print(f"  [{t.get('resolved_at', 'N/A')}] #{t['ticket_id']} {t['codice']} - {t['host']}/{t['service']}")
            print("")
        
        # Average resolution time
        if resolved_tickets:
            try:
                resolutions = []
                for t in resolved_tickets:
                    created = datetime.fromisoformat(t['created_at'].replace('Z', '+00:00'))
                    resolved = datetime.fromisoformat(t['resolved_at'].replace('Z', '+00:00'))
                    hours = (resolved - created).total_seconds() / 3600
                    resolutions.append(hours)
                
                avg_hours = int(sum(resolutions) / len(resolutions))
                print(f"  Tempo medio risoluzione: ~{avg_hours} ore")
            except Exception:
                pass
    
    def list_tracked_tickets(self):
        """List of all tracked tickets (JSON)"""
        self.init_tracking_file()
        
        with open(self.tracking_file, 'r', encoding='utf-8') as f:
            tracking = json.load(f)
        
        print(json.dumps(tracking, indent=2, ensure_ascii=False))


tracking = TrackingSystem()


# ===== INTERACTIVE CONFIG =====

def interactive_config():
    """Interactive configuration (wizard .env)"""
    script_dir = Path(__file__).resolve().parent
    env_file = script_dir / ".env"
    
    print("  Configurazione Interattiva Ydea Toolkit")
    print("==========================================")
    print("")
    
    # Leggi valori attuali se esistono
    current_id = config.YDEA_ID
    current_key = config.YDEA_API_KEY
    current_ticket_id = config.USER_ID_CREATE_TICKET
    current_note_id = config.USER_ID_CREATE_NOTE
    
    print(" CREDENZIALI API (obbligatorie)")
    print("   Ottienile da: https://my.ydea.cloud → Impostazioni → La mia azienda → API")
    print("")
    
    # YDEA_ID
    if current_id:
        new_id = input(f"YDEA_ID [{current_id}]: ").strip() or current_id
    else:
        new_id = ""
        while not new_id:
            new_id = input("YDEA_ID: ").strip()
            if not new_id:
                print(" YDEA_ID è obbligatorio!")
    
    # YDEA_API_KEY
    if current_key:
        new_key_input = input("YDEA_API_KEY [***nascosta***] (invio per mantenere): ").strip()
        new_key = new_key_input if new_key_input else current_key
    else:
        new_key = ""
        while not new_key:
            new_key = input("YDEA_API_KEY: ").strip()
            if not new_key:
                print(" YDEA_API_KEY è obbligatoria!")
    
    print("")
    print(" ID UTENTE PER OPERAZIONI (opzionali)")
    print("   Usa gli ID degli utenti Ydea per attribuire creazioni")
    print("")
    
    # YDEA_USER_ID_CREATE_TICKET
    new_ticket_id = input(f"ID utente creazione ticket [{current_ticket_id}]: ").strip() or str(current_ticket_id)
    
    # YDEA_USER_ID_CREATE_NOTE
    new_note_id = input(f"ID utente creazione note/commenti [{current_note_id}]: ").strip() or str(current_note_id)
    
    print("")
    print(" GESTIONE LOG E TRACKING (opzionali)")
    print("   Configurazione avanzata per logging e monitoraggio")
    print("")
    
    # Log file location
    current_log_file = str(config.LOG_FILE)
    new_log_file = input(f"Percorso file log [{current_log_file}]: ").strip() or current_log_file
    
    # Log max size (in MB)
    current_log_size_mb = config.LOG_MAX_SIZE // 1048576
    new_log_size_mb_str = input(f"Dimensione massima log in MB [{current_log_size_mb}]: ").strip() or str(current_log_size_mb)
    new_log_size = int(new_log_size_mb_str) * 1048576
    
    # Log level
    current_log_level = config.LOG_LEVEL
    new_log_level = input(f"Livello log (DEBUG/INFO/WARN/ERROR) [{current_log_level}]: ").strip() or current_log_level
    new_log_level = new_log_level.upper()
    
    # Tracking files
    current_tracking_file = str(config.TRACKING_FILE)
    new_tracking_file = input(f"Percorso file tracking ticket [{current_tracking_file}]: ").strip() or current_tracking_file
    
    # Retention days
    current_retention = config.TRACKING_RETENTION_DAYS
    new_retention = input(f"Giorni mantenimento ticket risolti [{current_retention}]: ").strip() or str(current_retention)
    
    print("")
    print(f" Salvataggio configurazione in: {env_file}")
    
    # Backup if exists
    if env_file.exists():
        backup_name = f"{env_file}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy(env_file, backup_name)
        print(f"   (backup creato: {backup_name})")
    
    # Write new .env
    env_content = f"""# ===== YDEA TOOLKIT CONFIGURATION =====
# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

# API Credentials (MANDATORY)
export YDEA_ID="{new_id}"
export YDEA_API_KEY="{new_key}"

# User ID for operations (optional)
export YDEA_USER_ID_CREATE_TICKET={new_ticket_id}
export YDEA_USER_ID_CREATE_NOTE={new_note_id}

# ===== LOG MANAGEMENT AND TRACKING =====
export YDEA_LOG_FILE="{new_log_file}"
export YDEA_LOG_MAX_SIZE={new_log_size}
export YDEA_LOG_LEVEL="{new_log_level}"
export YDEA_TRACKING_FILE="{new_tracking_file}"
export YDEA_TRACKING_RETENTION_DAYS={new_retention}

# ===== ADVANCED CONFIGURATIONS =====
# Uncomment and edit if necessary
# export YDEA_BASE_URL="https://my.ydea.cloud/app_api_v2"
# export YDEA_TOKEN_FILE="${{HOME}}/.ydea_token.json"
# export YDEA_DEBUG=0"""
    
    with open(env_file, 'w', encoding='utf-8') as f:
        f.write(env_content.lstrip())
    
    os.chmod(env_file, 0o600)
    
    print("")
    print(" Configurazione salvata con successo!")
    print("")
    print(" Riepilogo:")
    print(f"   YDEA_ID: {new_id}")
    print(f"   YDEA_API_KEY: {new_key[:10]}***")
    print(f"   ID creazione ticket: {new_ticket_id}")
    print(f"   ID creazione note: {new_note_id}")
    print("")
    print(" Configurazione Log & Tracking:")
    print(f"   File log: {new_log_file}")
    print(f"   Dimensione max: {new_log_size_mb_str}MB")
    print(f"   Livello log: {new_log_level}")
    print(f"   File tracking: {new_tracking_file}")
    print(f"   Retention giorni: {new_retention}")
    print("")
    print(" Test configurazione:")
    print(f"   source {env_file}")
    print(f"   {sys.argv[0]} login")
    print("")


# ===== CLI INTERFACE =====

def show_usage():
    """Mostra help/usage"""
    usage = """Ydea Toolkit - API Management v2 (Python)

SETUP:
  export YDEA_ID="your_id" # From: Settings → My Company → API
  export YDEA_API_KEY="your_api_key"
  
  # User ID for operations (optional)
  export YDEA_USER_ID_CREATE_TICKET=4675 # ID for ticket creation
  export YDEA_USER_ID_CREATE_NOTE=4675 # ID for creating notes/comments
  
  export YDEA_DEBUG=1 # (optional) for verbose debugging
  export YDEA_LOG_FILE=/path/log.log # (default: /var/log/ydea-toolkit.log)

COMMANDS:

  Authentication:
    login Log in and save token

  Generic APIs:
    api <METHOD> </path> [json_body] Generic API call
    
  Ticket - List and Search:
    list [limit] [status] Ticket list (default: 50)
    search <query> [limit] Search tickets by text
    get <ticket_id> Specific ticket details
    
  Ticket - Creation and Modification:
    create <title> [description] [priority] [sla_id]
    update <ticket_id> '<json>' Update ticket (JSON format)
    close <ticket_id> [note] Close ticket
    comment <ticket_id> '<text>' [public:true|false]
                                       Add comment
  
  Tracking Ticket (Status Monitoring):
    track <ticket_id> <code> <host> <service> [desc]
                                       Add tickets to automatic tracking
    update-tracking Update statuses of all tracked tickets
    cleanup-tracking Remove old resolved tickets
    list-tracking Show full JSON tracked tickets
    stats Ticket statistics (open/resolved/times)
    
  Logs and Debugging:
    logs [lines] Show last N logs (default: 50)
    clearlog Clear log files
  
  Configuration:
    config Interactive configuration (ID, API key, user ID)
    
  Other:
    categories List of categories
    users [limit] List of users
    version Show toolkit version

EXAMPLES:

  # Interactive initial setup
  ./ydea-toolkit.py config
  
  # Initial login
  ./ydea-toolkit.py login

  # List of last 10 open tickets
  ./ydea-toolkit.py list 10 open | jq .

  # Create new ticket
  ./ydea-toolkit.py create "Server down" "The web server is not responding" high

  # Search tickets
  ./ydea-toolkit.py search "database error" | jq '.data[] | {id, title, status}'

  # Add comment
  ./ydea-toolkit.py comment 12345 "Problem resolved by restarting the service"

  # Close ticket
  ./ydea-toolkit.py close 12345 "Solved with reboot"

  # Tracking tickets from CheckMK
  ./ydea-toolkit.py track 12345 "TK25/003376" "web-server" "Apache Status" "Alert from CheckMK"
  
  # View tracking statistics
  ./ydea-toolkit.py stats
  
  # Update all tracked tickets
  ./ydea-toolkit.py update-tracking
  
  # View log
  ./ydea-toolkit.py logs 100

  # Custom API call
  ./ydea-toolkit.py api GET /tickets/12345/history | jq .

ENVIRONMENT VARIABLES:
  # API Credentials (MANDATORY)
  YDEA_ID Ydea API account ID
  YDEA_API_KEY Ydea API key
  
  # User ID for operations (optional)
  YDEA_USER_ID_CREATE_TICKET (default: 4675) ID for ticket creation
  YDEA_USER_ID_CREATE_NOTE (default: 4675) ID for creating notes/comments
  
  # General configurations
  YDEA_BASE_URL (default: https://my.ydea.cloud/app_api_v2)
  YDEA_TOKEN_FILE (default: ~/.ydea_token.json)
  YDEA_LOG_FILE (default: /var/log/ydea-toolkit.log)
  YDEA_LOG_MAX_SIZE (default: 10485760 = 10MB)
  YDEA_TRACKING_FILE (default: /var/log/ydea-tickets-tracking.json)
  YDEA_TRACKING_RETENTION_DAYS (default: 365 days)
  YDEA_EXPIRY_SKEW (default: 60 seconds)
  YDEA_DEBUG (default: 0, set 1 for debug)

VERSION: {VERSION}"""
    print(usage)


def show_logs(lines: int = 50):
    """Mostra ultimi N log"""
    if not config.LOG_FILE.exists():
        print(f"File di log non trovato: {config.LOG_FILE}", file=sys.stderr)
        sys.exit(1)
    
    try:
        with open(config.LOG_FILE, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
        
        for line in all_lines[-lines:]:
            print(line, end='')
    except Exception as e:
        logger.error(f"Errore lettura log: {e}")
        sys.exit(1)


def clear_log():
    """Clean log files"""
    if config.LOG_FILE.exists():
        with open(config.LOG_FILE, 'w', encoding='utf-8') as f:
            f.write('')
        logger.info(f"File di log pulito: {config.LOG_FILE}")
    else:
        logger.warn(f"File di log non esistente: {config.LOG_FILE}")


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='Ydea Toolkit - Gestione API v2',
        add_help=False
    )
    parser.add_argument('command', nargs='?', help='Comando da eseguire')
    parser.add_argument('args', nargs='*', help='Argomenti comando')
    parser.add_argument('-h', '--help', action='store_true', help='Mostra help')
    parser.add_argument('--version', action='store_true', help='Mostra versione')
    
    args = parser.parse_args()
    
    if args.help or args.command == 'help':
        show_usage()
        sys.exit(0)
    
    if args.version or args.command == 'version':
        print(f"Ydea Toolkit v{VERSION}")
        sys.exit(0)
    
    if not args.command:
        show_usage()
        sys.exit(1)
    
    try:
        # Authentication
        if args.command == 'login':
            api.login()
        
        # API generic
        elif args.command == 'api':
            if len(args.args) < 2:
                logger.error("Uso: api <METHOD> </path> [json_body]")
                sys.exit(1)
            method = args.args[0]
            path = args.args[1]
            json_body = None
            if len(args.args) > 2:
                json_body = json.loads(args.args[2])
            response, _ = api.api_call(method, path, json_body)
            print(json.dumps(response, indent=2, ensure_ascii=False))
        
        # Configuration
        elif args.command == 'config':
            interactive_config()
        
        # Ticket operations
        elif args.command == 'list':
            limit = int(args.args[0]) if args.args else 50
            status = args.args[1] if len(args.args) > 1 else None
            response = tickets.list_tickets(limit, status)
            print(json.dumps(response, indent=2, ensure_ascii=False))
        
        elif args.command == 'get':
            if not args.args:
                logger.error("Uso: get <ticket_id>")
                sys.exit(1)
            ticket_id = int(args.args[0])
            response = tickets.get_ticket(ticket_id)
            print(json.dumps(response, indent=2, ensure_ascii=False))
        
        elif args.command == 'create':
            if not args.args:
                logger.error("Uso: create <title> [description] [priority] [sla_id] [tipo] [creatoda]")
                sys.exit(1)
            title = args.args[0]
            description = args.args[1] if len(args.args) > 1 else ""
            priority = args.args[2] if len(args.args) > 2 else "normal"
            sla_id = int(args.args[3]) if len(args.args) > 3 else None
            tipo = args.args[4] if len(args.args) > 4 else None
            creatoda = int(args.args[5]) if len(args.args) > 5 else None
            response = tickets.create_ticket(title, description, priority, sla_id, tipo, creatoda)
            print(json.dumps(response, indent=2, ensure_ascii=False))
        
        elif args.command == 'update':
            if len(args.args) < 2:
                logger.error("Uso: update <ticket_id> '<json>'")
                sys.exit(1)
            ticket_id = int(args.args[0])
            json_updates = json.loads(args.args[1])
            response = tickets.update_ticket(ticket_id, json_updates)
            print(json.dumps(response, indent=2, ensure_ascii=False))
        
        elif args.command == 'close':
            if not args.args:
                logger.error("Uso: close <ticket_id> [nota]")
                sys.exit(1)
            ticket_id = int(args.args[0])
            note = args.args[1] if len(args.args) > 1 else "Ticket chiuso"
            response = tickets.close_ticket(ticket_id, note)
            print(json.dumps(response, indent=2, ensure_ascii=False))
        
        elif args.command == 'comment':
            if len(args.args) < 2:
                logger.error("Uso: comment <ticket_id> '<testo>' [pubblico:true|false]")
                sys.exit(1)
            ticket_id = int(args.args[0])
            comment = args.args[1]
            is_public = args.args[2].lower() == 'true' if len(args.args) > 2 else False
            response = tickets.add_comment(ticket_id, comment, is_public)
            print(json.dumps(response, indent=2, ensure_ascii=False))
        
        elif args.command == 'search':
            if not args.args:
                logger.error("Uso: search <query> [limit]")
                sys.exit(1)
            query = args.args[0]
            limit = int(args.args[1]) if len(args.args) > 1 else 20
            response = tickets.search_tickets(query, limit)
            print(json.dumps(response, indent=2, ensure_ascii=False))
        
        # Tracking operations
        elif args.command == 'track':
            if len(args.args) < 4:
                logger.error("Uso: track <ticket_id> <codice> <host> <service> [desc]")
                sys.exit(1)
            ticket_id = int(args.args[0])
            codice = args.args[1]
            host = args.args[2]
            service = args.args[3]
            description = args.args[4] if len(args.args) > 4 else ""
            tracking.track_ticket(ticket_id, codice, host, service, description)
        
        elif args.command == 'update-tracking':
            tracking.update_tracked_tickets()
        
        elif args.command == 'cleanup-tracking':
            tracking.cleanup_resolved_tickets()
        
        elif args.command == 'list-tracking':
            tracking.list_tracked_tickets()
        
        elif args.command == 'stats':
            tracking.show_tracking_stats()
        
        # Log operations
        elif args.command == 'logs':
            lines = int(args.args[0]) if args.args else 50
            show_logs(lines)
        
        elif args.command == 'clearlog':
            clear_log()
        
        # Other
        elif args.command == 'categories':
            response = tickets.list_categories()
            print(json.dumps(response, indent=2, ensure_ascii=False))
        
        elif args.command == 'users':
            limit = int(args.args[0]) if args.args else 50
            response = tickets.list_users(limit)
            print(json.dumps(response, indent=2, ensure_ascii=False))
        
        else:
            logger.error(f"Comando sconosciuto: {args.command}")
            show_usage()
            sys.exit(1)
    
    except KeyboardInterrupt:
        print("\n  Operazione interrotta dall'utente", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        logger.error(f"Errore: {e}")
        if config.DEBUG:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
