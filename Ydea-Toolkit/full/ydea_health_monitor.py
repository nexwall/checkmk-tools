#!/usr/bin/env python3
"""ydea_health_monitor.py - Ydea API availability monitor

Periodically checks if Ydea is reachable and notifies via email if down/recovery.
Manages consecutive error threshold to avoid false positives.

Usage:
    ydea_health_monitor.py

Typically run via cron every 15 minutes.

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

from ydea_common import Logger, StateManager, EmailNotifier  # type: ignore

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


# ===== CONFIGURATION =====

STATE_FILE = Path("/tmp/ydea_health_state.json")
MAIL_SCRIPT = Path("/omd/sites/monitoring/local/share/check_mk/notifications/mail_ydea_down")

# Email recipient for notifications
ALERT_EMAIL = os.getenv("YDEA_ALERT_EMAIL", "massimo.palazzetti@nethesis.it")

# Threshold of consecutive errors before reporting (to avoid false positives)
FAILURE_THRESHOLD = int(os.getenv("YDEA_FAILURE_THRESHOLD", "3"))

# Default state
DEFAULT_STATE = {
    "status": "unknown",
    "last_check": 0,
    "consecutive_failures": 0,
    "last_failure": "",
    "notified": False
}


# ===== FUNZIONI UTILITY =====

def test_ydea_login() -> bool:
    """Test Ydea API login
    
    Returns:
        True if login successful, False otherwise"""
    try:
        api = YdeaAPI()
        api.ensure_token()
        return True
    except Exception as e:
        Logger.error(f"Login fallito: {e}")
        return False


def send_email_alert(subject: str, body: str) -> bool:
    """Send email notification
    
    Args:
        subject: Email subject
        body: Email body
        
    Returns:
        True if sending successful, False otherwise"""
    Logger.info(f"Invio notifica email a {ALERT_EMAIL}")
    
    # Use the mail_ydea_down script if it exists
    if MAIL_SCRIPT.exists() and os.access(MAIL_SCRIPT, os.X_OK):
        try:
            # Export variables for notification script
            env = os.environ.copy()
            env.update({
                "NOTIFY_HOSTNAME": "ydea.cloud",
                "NOTIFY_HOSTADDRESS": "my.ydea.cloud",
                "NOTIFY_WHAT": "HOST",
                "NOTIFY_HOSTSTATE": "DOWN",
                "NOTIFY_HOSTOUTPUT": "Ydea API non raggiungibile - Impossibile effettuare login",
                "NOTIFY_CONTACTEMAIL": ALERT_EMAIL,
                "NOTIFY_DATE": datetime.now().strftime('%Y-%m-%d'),
                "NOTIFY_SHORTDATETIME": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            
            import subprocess
            result = subprocess.run(
                [str(MAIL_SCRIPT)],
                env=env,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                Logger.info(result.stdout)
                return True
            else:
                Logger.error(f"Script mail fallito: {result.stderr}")
                return False
                
        except Exception as e:
            Logger.error(f"Errore esecuzione script mail: {e}")
            return False
    else:
        # Fallback: usa EmailNotifier
        try:
            notifier = EmailNotifier(smtp_host="localhost", smtp_port=25)
            notifier.send_email(ALERT_EMAIL, subject, body, html=False)
            return True
        except Exception as e:
            Logger.error(f"Errore invio email: {e}")
            return False


def build_down_alert() -> tuple[str, str]:
    """Build email alerts for Ydea down
    
    Returns:
        Tuple (subject, body)"""
    subject = " [ALERT] Ydea API - Servizio Non Raggiungibile"
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    body = f"""ATTENTION: The Ydea API service is not reachable.

Details:
- Date/Time detection: {now}
- Consecutive failed attempts: {FAILURE_THRESHOLD}
- URL: https://my.ydea.cloud
- Endpoint: /app_api_v2/login

Impact:
- Ticketing system not available
- CheckMK Alerts will NOT be converted into Ydea tickets
- Manual ticket creation not possible

Required actions:
1. Check Ydea service status (https://status.ydea.cloud if available)
2. Check network connectivity
3. Verify API credentials
4. Contact Ydea support if necessary

The system will continue to monitor and notify you when service is restored.

---
Ydea Health automatic monitor
Check every 15 minutes"""
    
    return subject, body


def build_recovery_alert(last_failure_timestamp: str) -> tuple[str, str]:
    """Build email alerts for Ydea recovery
    
    Args:
        last_failure_timestamp: Last failure timestamp
        
    Returns:
        Tuple (subject, body)"""
    subject = " [RECOVERY] Ydea API - Servizio Ripristinato"
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Converti timestamp se disponibile
    last_failure_str = "N/A"
    if last_failure_timestamp:
        try:
            last_failure_dt = datetime.fromtimestamp(int(last_failure_timestamp))
            last_failure_str = last_failure_dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            pass
    
    body = f"""The Ydea API service is back online.

Details:
- Date/Time recovery: {now}
- Last check failed: {last_failure_str}

The ticketing service is operational again.

---
Ydea Health automatic monitor"""
    
    return subject, body


# ===== MAIN =====

def main():
    """Main function"""
    
    # Inizializza state manager
    state = StateManager(STATE_FILE, default_state=DEFAULT_STATE)
    
    # Read current status
    current_status = state.get("status")
    consecutive_failures = state.get("consecutive_failures")
    was_notified = state.get("notified")
    
    Logger.info("Controllo disponibilità Ydea API...")
    
    if test_ydea_login():
        # ===== YDEA UP =====
        Logger.success(" Ydea API raggiungibile")
        
        # Se era down e abbiamo notificato, invia recovery email
        if current_status == "down" and was_notified:
            Logger.info("Ydea tornato online, invio notifica di recovery")
            
            last_failure = state.get("last_failure")
            subject, body = build_recovery_alert(last_failure)
            
            send_email_alert(subject, body)
        
        # Reset status
        state.set("status", "up")
        state.set("consecutive_failures", 0)
        state.set("notified", False)
        state.set("last_failure", "")
        state.set("last_check", int(datetime.now().timestamp()))
        
    else:
        # ===== YDEA DOWN =====
        consecutive_failures += 1
        Logger.error(f" Ydea API non raggiungibile (tentativi falliti: {consecutive_failures}/{FAILURE_THRESHOLD})")
        
        # Notify only if we reach the threshold and have not already notified
        if consecutive_failures >= FAILURE_THRESHOLD and not was_notified:
            Logger.info("Soglia di errori raggiunta, invio notifica")
            
            subject, body = build_down_alert()
            
            if send_email_alert(subject, body):
                Logger.success(" Notifica inviata con successo")
                state.set("notified", True)
            else:
                Logger.error("Errore invio notifica")
                state.set("notified", False)
        
        # Update status
        state.set("status", "down")
        state.set("consecutive_failures", consecutive_failures)
        state.set("last_failure", str(int(datetime.now().timestamp())))
        state.set("last_check", int(datetime.now().timestamp()))


if __name__ == "__main__":
    main()
