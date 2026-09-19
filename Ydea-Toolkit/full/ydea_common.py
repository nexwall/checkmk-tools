#!/usr/bin/env python3
"""ydea_common.py - Shared module for Ydea-Toolkit common utilities

Provides common functionality used by all scripts:
- Logging utilities
- Cache management (JSON file-based)
- Configuration loading
- State management
- Email notifications

Version: 1.0.0"""

VERSION = "1.0.0"  # Versione modulo (aggiornare ad ogni modifica)

import os
import sys
import json
import time
import smtplib
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


# ===== LOGGING UTILITIES =====

class Logger:
    """Simple logger with timestamp and emoji"""
    
    @staticmethod
    def _log(emoji: str, level: str, message: str, to_stderr: bool = False):
        """Generic log with timestamp"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_line = f"[{timestamp}] {emoji} {message}"
        
        if to_stderr:
            print(log_line, file=sys.stderr)
        else:
            print(log_line)
    
    @staticmethod
    def info(message: str):
        """Log informativo"""
        Logger._log("ℹ ", "INFO", message)
    
    @staticmethod
    def warn(message: str):
        """Log warning"""
        Logger._log(" ", "WARN", message, to_stderr=True)
    
    @staticmethod
    def error(message: str):
        """Error log"""
        Logger._log("", "ERROR", message, to_stderr=True)
    
    @staticmethod
    def success(message: str):
        """Log success"""
        Logger._log("", "SUCCESS", message)
    
    @staticmethod
    def debug(message: str):
        """Debug log (only if DEBUG=1)"""
        if os.getenv("DEBUG", "0") == "1":
            Logger._log("", "DEBUG", message, to_stderr=True)


# ===== CACHE MANAGEMENT =====

class CacheManager:
    """File-based JSON cache management"""
    
    def __init__(self, cache_file: str):
        """Initialize cache manager
        
        Args:
            cache_file: Path to the JSON cache file"""
        self.cache_file = Path(cache_file)
        self._init_cache()
    
    def _init_cache(self):
        """Initialize cache file if it does not exist"""
        if not self.cache_file.exists():
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.save({})
    
    def load(self) -> Dict[str, Any]:
        """Load cache from file
        
        Returns:
            Dictionary with cached content"""
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def save(self, data: Dict[str, Any]):
        """Save cache to file
        
        Args:
            data: Dictionary to save"""
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            Logger.error(f"Errore salvataggio cache: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache
        
        Args:
            key: Key to search for
            default: Default value if key not found
        
        Returns:
            Value associated with the key or default"""
        cache = self.load()
        return cache.get(key, default)
    
    def set(self, key: str, value: Any):
        """Set value in cache
        
        Args:
            key: Key
            value: Value to save"""
        cache = self.load()
        cache[key] = value
        self.save(cache)
    
    def delete(self, key: str):
        """Remove key from cache
        
        Args:
            key: Key to remove"""
        cache = self.load()
        if key in cache:
            del cache[key]
            self.save(cache)
    
    def exists(self, key: str) -> bool:
        """Check if key exists in cache
        
        Args:
            key: Key to verify
        
        Returns:
            True if key exists, False otherwise"""
        cache = self.load()
        return key in cache
    
    def cleanup_old_entries(self, max_age_seconds: int, timestamp_key: str = 'created_at'):
        """Clear old entries from cache
        
        Args:
            max_age_seconds: Maximum age in seconds
            timestamp_key: Timestamp field name in entries"""
        cache = self.load()
        now = int(time.time())
        cutoff = now - max_age_seconds
        
        cleaned = {
            k: v for k, v in cache.items()
            if isinstance(v, dict) and v.get(timestamp_key, 0) > cutoff
        }
        
        if len(cleaned) < len(cache):
            removed = len(cache) - len(cleaned)
            Logger.debug(f"Rimossi {removed} entry vecchie dalla cache")
            self.save(cleaned)


# ===== CONFIGURATION LOADING =====

class ConfigLoader:
    """Loading configuration from JSON file"""
    
    @staticmethod
    def load_json(config_file: str) -> Dict[str, Any]:
        """Load configuration from JSON file
        
        Args:
            config_file: Path to the configuration file
        
        Returns:
            Dictionary with configuration
        
        Raises:
            FileNotFoundError: If file does not exist
            json.JSONDecodeError: If JSON is invalid"""
        config_path = Path(config_file)
        
        if not config_path.exists():
            raise FileNotFoundError(f"File configurazione non trovato: {config_file}")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @staticmethod
    def load_env(env_file: str = ".env") -> Dict[str, str]:
        """Load variables from .env file
        
        Args:
            env_file: Path to the .env file
        
        Returns:
            Dictionary with environment variables"""
        env_vars = {}
        env_path = Path(env_file)
        
        if not env_path.exists():
            return env_vars
        
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    # Remove 'export' if present
                    line = line.replace('export ', '', 1).strip()
                    key, value = line.split('=', 1)
                    # Rimuovi quotes
                    value = value.strip().strip('"').strip("'")
                    env_vars[key.strip()] = value
        
        return env_vars


# ===== STATE MANAGEMENT =====

class StateManager:
    """Application state management with JSON persistence"""
    
    def __init__(self, state_file: str, default_state: Optional[Dict[str, Any]] = None):
        """Initialize state manager
        
        Args:
            state_file: Path to the JSON state file
            default_state: Default state if file does not exist"""
        self.state_file = Path(state_file)
        self.default_state = default_state or {}
        self._init_state()
    
    def _init_state(self):
        """Initialize state file if it does not exist"""
        if not self.state_file.exists():
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.save(self.default_state)
    
    def load(self) -> Dict[str, Any]:
        """Load state from file
        
        Returns:
            Dictionary with current status"""
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return self.default_state.copy()
    
    def save(self, state: Dict[str, Any]):
        """Save state to file
        
        Args:
            state: State dictionary to save"""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            Logger.error(f"Errore salvataggio stato: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get value from the state"""
        state = self.load()
        return state.get(key, default)
    
    def set(self, key: str, value: Any):
        """Set value in state"""
        state = self.load()
        state[key] = value
        self.save(state)
    
    def update(self, updates: Dict[str, Any]):
        """Update multiple keys in the state
        
        Args:
            updates: Dictionary with updates"""
        state = self.load()
        state.update(updates)
        self.save(state)


# ===== EMAIL NOTIFICATIONS =====

class EmailNotifier:
    """Gestione notifiche email"""
    
    def __init__(
        self,
        smtp_host: str = "localhost",
        smtp_port: int = 25,
        from_email: Optional[str] = None
    ):
        """Initialize email notifier
        
        Args:
            smtp_host: SMTP host
            smtp_port: SMTP port
            from_email: Sender email"""
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.from_email = from_email or f"checkmk@{os.uname().nodename}"
    
    def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        html: bool = False
    ) -> bool:
        """Send email
        
        Args:
            to_email: Recipient
            subject: Object
            body: Message body
            html: True if body is HTML
        
        Returns:
            True if sending successful, False otherwise"""
        try:
            msg = MIMEMultipart('alternative') if html else MIMEText(body)
            
            if html:
                msg.attach(MIMEText(body, 'plain'))
                msg.attach(MIMEText(body, 'html'))
            
            msg['Subject'] = subject
            msg['From'] = self.from_email
            msg['To'] = to_email
            
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.send_message(msg)
            
            Logger.success(f"Email inviata a {to_email}")
            return True
            
        except Exception as e:
            Logger.error(f"Errore invio email: {e}")
            return False


# ===== UTILITY FUNCTIONS =====

def format_timestamp(timestamp: Optional[int] = None, fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
    """Format Unix timestamp to string
    
    Args:
        timestamp: Unix timestamp (None = now)
        fmt: Output format
    
    Returns:
        Formatted string"""
    if timestamp is None:
        timestamp = int(time.time())
    
    return datetime.fromtimestamp(timestamp).strftime(fmt)


def get_current_timestamp() -> int:
    """Get current Unix timestamp
    
    Returns:
        Unix timestamp (seconds)"""
    return int(time.time())


def ensure_directory(path: str):
    """Ensure directory exists, creating it if necessary
    
    Args:
        path: Path directory"""
    Path(path).mkdir(parents=True, exist_ok=True)


# ===== EXPORTS =====

__all__ = [
    'Logger',
    'CacheManager',
    'ConfigLoader',
    'StateManager',
    'EmailNotifier',
    'format_timestamp',
    'get_current_timestamp',
    'ensure_directory'
]
