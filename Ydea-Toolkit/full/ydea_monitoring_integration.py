#!/usr/bin/env python3
"""ydea_monitoring_integration.py - System monitoring integration with Ydea

Monitor CPU, memory, disk and systemd services.
Automatically create Ydea tickets when thresholds are exceeded.
Manages cache to avoid duplicates and automatic cleanup.

Usage:
    ydea_monitoring_integration.py [cpu|memory|disk|service|cleanup|main]

Examples:
    ydea_monitoring_integration.py # Perform all checks
    ydea_monitoring_integration.py cpu # CPU monitoring only
    ydea_monitoring_integration.py service nginx # Monitor nginx service

Version: 1.0.0 (ported from Bash)"""

VERSION = "1.0.0"  # Versione script (aggiornare ad ogni modifica)

import sys
import os
import importlib.util
import socket
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

# Requires psutil for system metrics
try:
    import psutil
except ImportError:
    print("ERRORE: psutil non installato. Eseguire: pip3 install psutil")
    sys.exit(1)

# Import moduli locali
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

from ydea_common import Logger, CacheManager  # type: ignore

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


# ===== CONFIGURATION =====

# Soglie alert
ALERT_THRESHOLD_CPU = int(os.getenv("ALERT_THRESHOLD_CPU", "90"))
ALERT_THRESHOLD_MEM = int(os.getenv("ALERT_THRESHOLD_MEM", "85"))
ALERT_THRESHOLD_DISK = int(os.getenv("ALERT_THRESHOLD_DISK", "90"))

# Ticket cache file
TICKET_CACHE_FILE = Path("/tmp/ydea_tickets_cache.json")

# Max age cache (24 hours)
CACHE_MAX_AGE_HOURS = 24


# ===== GESTIONE CACHE TICKET =====

cache = CacheManager(TICKET_CACHE_FILE)


def ticket_exists(alert_key: str) -> bool:
    """Check if there is already an open ticket for this alert
    
    Args:
        alert_key: Unique alert key (e.g. cpu_hostname)
        
    Returns:
        True if ticket exists in cache"""
    return cache.get(alert_key) is not None


def save_ticket_cache(alert_key: str, ticket_id: int):
    """Save tickets in cache
    
    Args:
        alert_key: Unique alert key
        ticket_id: Created ticket ID"""
    cache.set(alert_key, {
        "ticket_id": ticket_id,
        "created_at": int(datetime.now().timestamp())
    })


def remove_ticket_cache(alert_key: str):
    """Remove ticket from cache (when closed or alert resolved)
    
    Args:
        alert_key: Unique alert key"""
    cache.delete(alert_key)


def cleanup_cache():
    """Clear cache from old tickets (>24h)"""
    now = int(datetime.now().timestamp())
    max_age_seconds = CACHE_MAX_AGE_HOURS * 3600
    
    all_data = cache.load()
    removed_count = 0
    
    for key, ticket_data in all_data.items():
        if ticket_data and isinstance(ticket_data, dict):
            created_at = ticket_data.get("created_at", 0)
            if now - created_at > max_age_seconds:
                cache.delete(key)
                removed_count += 1
    
    if removed_count > 0:
        Logger.info(f"Rimossi {removed_count} ticket vecchi dalla cache")


# ===== FUNZIONI CREAZIONE TICKET =====

def create_ticket(title: str, description: str, priority: str = "normal", tags: list = None) -> Optional[int]:
    """Create Ydea ticket
    
    Args:
        title: Ticket title
        description: Ticket description
        priority: Priority (normal, high, critical)
        tags: Tag list
        
    Returns:
        Ticket ID created, None if failed"""
    try:
        api = YdeaAPI()
        
        ticket_body = {
            "titolo": title,
            "descrizione": description,
            "priorita": priority
        }
        
        if tags:
            ticket_body["tags"] = tags
        
        response, status_code = api.api_call("POST", "/tickets", json_body=ticket_body)
        
        if status_code in [200, 201]:
            ticket_id = response.get("id")
            if ticket_id:
                Logger.success(f" Ticket creato: #{ticket_id}")
                return ticket_id
        
        Logger.error("Creazione ticket fallita")
        return None
        
    except Exception as e:
        Logger.error(f"Errore creazione ticket: {e}")
        return None


# ===== MONITORING FUNCTIONS =====

def check_cpu_usage(hostname: Optional[str] = None):
    """Monitor CPU
    
    Args:
        hostname: Hostname (default: current hostname)"""
    if not hostname:
        hostname = socket.gethostname()
    
    # Get CPU Usage (average 1 second)
    cpu_usage = int(psutil.cpu_percent(interval=1))
    
    alert_key = f"cpu_{hostname}"
    
    if cpu_usage > ALERT_THRESHOLD_CPU:
        if not ticket_exists(alert_key):
            Logger.warn(f"CPU usage elevato: {cpu_usage}%")
            
            title = f"[HIGH] CPU usage elevato su {hostname}"
            description = f"""CPU Alert

**Details:**
- Hostname: {hostname}
- CPU Usage: {cpu_usage}%
- Threshold: {ALERT_THRESHOLD_CPU}%
- Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Immediate actions:**
1. Identify processes that consume the most CPU
2. Check if it is a temporary or persistent spike
3. Check for zombie processes
4. Evaluate vertical scaling

**Diagnostics:**
```bash
top -bn1 | head -20
ps auxf --sort=-%cpu | head -10
```"""
            
            ticket_id = create_ticket(title, description, priority="high", 
                                     tags=["cpu", "performance", "infrastruttura"])
            
            if ticket_id:
                save_ticket_cache(alert_key, ticket_id)
    else:
        # CPU OK - rimuovi ticket se esistente
        if ticket_exists(alert_key):
            Logger.info(f"CPU tornata normale ({cpu_usage}%), rimuovo ticket dalla cache")
            remove_ticket_cache(alert_key)


def check_memory_usage(hostname: Optional[str] = None):
    """Monitor memory
    
    Args:
        hostname: Hostname (default: current hostname)"""
    if not hostname:
        hostname = socket.gethostname()
    
    # Get memory usage
    mem = psutil.virtual_memory()
    mem_usage = int(mem.percent)
    
    alert_key = f"mem_{hostname}"
    
    if mem_usage > ALERT_THRESHOLD_MEM:
        if not ticket_exists(alert_key):
            Logger.warn(f"Memory usage elevato: {mem_usage}%")
            
            title = f"[HIGH] Memory usage elevato su {hostname}"
            description = f"""Memory Alert

**Details:**
- Hostname: {hostname}
- Memory Usage: {mem_usage}%
- Threshold: {ALERT_THRESHOLD_MEM}%
- Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Immediate actions:**
1. Identify processes that consume the most memory
2. Check for memory leaks
3. Check cache and buffers
4. Consider increasing RAM

**Diagnostics:**
```bash
free -h
ps auxf --sort=-%mem | head -10
sudo slabtop
```"""
            
            ticket_id = create_ticket(title, description, priority="high",
                                     tags=["memoria", "performance", "infrastruttura"])
            
            if ticket_id:
                save_ticket_cache(alert_key, ticket_id)
    else:
        # Memory OK
        if ticket_exists(alert_key):
            Logger.info(f"Memoria tornata normale ({mem_usage}%), rimuovo ticket dalla cache")
            remove_ticket_cache(alert_key)


def check_disk_usage(hostname: Optional[str] = None, mount_point: str = "/"):
    """Monitor disk
    
    Args:
        hostname: Hostname (default: current hostname)
        mount_point: Mount point to check (default: /)"""
    if not hostname:
        hostname = socket.gethostname()
    
    try:
        # Get disk usage
        disk = psutil.disk_usage(mount_point)
        disk_usage = int(disk.percent)
        
        # Create alert key (replace / with _)
        mount_safe = mount_point.replace("/", "_")
        alert_key = f"disk_{hostname}_{mount_safe}"
        
        if disk_usage > ALERT_THRESHOLD_DISK:
            if not ticket_exists(alert_key):
                Logger.warn(f"Disk usage elevato su {mount_point}: {disk_usage}%")
                
                title = f"[HIGH] Disk usage elevato su {hostname}:{mount_point}"
                description = f"""Disk Alert

**Details:**
- Hostname: {hostname}
- Mount Point: {mount_point}
- Disk Usage: {disk_usage}%
- Threshold: {ALERT_THRESHOLD_DISK}%
- Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Immediate actions:**
1. Identify larger files/directories
2. Clean old logs
3. Remove temporary files
4. Consider storage expansion

**Diagnostics:**
```bash
df -h {mount_point}
du -sh {mount_point}/* | sort -rh | head -10
find {mount_point} -type f -size +100M
```"""
                
                ticket_id = create_ticket(title, description, priority="high",
                                         tags=["disco", "storage", "infrastruttura"])
                
                if ticket_id:
                    save_ticket_cache(alert_key, ticket_id)
        else:
            # Disk OK
            if ticket_exists(alert_key):
                Logger.info(f"Disco {mount_point} tornato normale ({disk_usage}%), rimuovo ticket dalla cache")
                remove_ticket_cache(alert_key)
                
    except Exception as e:
        Logger.error(f"Errore controllo disco {mount_point}: {e}")


def check_service_status(service_name: str, hostname: Optional[str] = None):
    """Monitor systemd service
    
    Args:
        service_name: Systemd service name
        hostname: Hostname (default: current hostname)"""
    if not hostname:
        hostname = socket.gethostname()
    
    try:
        # Check service status with systemctl
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        is_active = (result.returncode == 0)
        service_status = result.stdout.strip()
        
        alert_key = f"service_{hostname}_{service_name}"
        
        if not is_active:
            if not ticket_exists(alert_key):
                Logger.error(f"Servizio {service_name} non attivo")
                
                title = f"[CRITICAL] Servizio {service_name} non attivo su {hostname}"
                description = f"""Service Down Alert

**Details:**
- Hostname: {hostname}
- Service: {service_name}
- Status: {service_status}
- Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Immediate actions:**
1. Attempt to restart service
2. Check service log
3. Check dependencies
4. Check configuration

**Diagnostics:**
```bash
systemctl status {service_name}
journalctl -xeu {service_name} --since '10 minutes ago'
sudo systemctl restart {service_name}
```"""
                
                ticket_id = create_ticket(title, description, priority="critical",
                                         tags=["servizio", "downtime", "infrastruttura"])
                
                if ticket_id:
                    save_ticket_cache(alert_key, ticket_id)
        else:
            # Service OK
            if ticket_exists(alert_key):
                Logger.info(f"Servizio {service_name} tornato attivo, rimuovo ticket dalla cache")
                remove_ticket_cache(alert_key)
                
    except subprocess.TimeoutExpired:
        Logger.error(f"Timeout controllo servizio {service_name}")
    except FileNotFoundError:
        Logger.error("systemctl non trovato - sistema non supportato")
    except Exception as e:
        Logger.error(f"Errore controllo servizio {service_name}: {e}")


# ===== MAIN =====

def main():
    """Main function - performs all checks"""
    Logger.info("Inizio controlli monitoraggio")
    
    # Pulizia cache
    cleanup_cache()
    
    # Default controls
    check_cpu_usage()
    check_memory_usage()
    check_disk_usage()
    
    # Critical service checks (optional - uncomment if necessary)
    # check_service_status("nginx")
    # check_service_status("mysql")
    # check_service_status("postgresql")
    
    Logger.success("Controlli completati")


if __name__ == "__main__":
    # CLI
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "cpu":
            hostname = sys.argv[2] if len(sys.argv) > 2 else None
            check_cpu_usage(hostname)
        
        elif command in ["memory", "mem"]:
            hostname = sys.argv[2] if len(sys.argv) > 2 else None
            check_memory_usage(hostname)
        
        elif command == "disk":
            hostname = sys.argv[2] if len(sys.argv) > 2 else None
            mount_point = sys.argv[3] if len(sys.argv) > 3 else "/"
            check_disk_usage(hostname, mount_point)
        
        elif command == "service":
            if len(sys.argv) < 3:
                print("Usage: ydea_monitoring_integration.py service <service_name> [hostname]")
                sys.exit(1)
            service_name = sys.argv[2]
            hostname = sys.argv[3] if len(sys.argv) > 3 else None
            check_service_status(service_name, hostname)
        
        elif command == "cleanup":
            cleanup_cache()
            Logger.success("Cache pulita")
        
        else:
            main()
    else:
        main()
