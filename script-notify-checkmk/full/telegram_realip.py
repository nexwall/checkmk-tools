#!/usr/bin/env python3
"""telegram_realip - Telegram Notification with Real IP Support
Bulk: no

CheckMK notification script - sends Telegram message with real IP and inline buttons.

Version: 1.2.1"""

import os
import sys
import json
import urllib.request
import urllib.parse
from urllib.error import URLError

VERSION = "1.2.1"

# === CONFIG ===
TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CMK_URL = os.environ.get("CMK_URL", "")
SITE = "monitoring"
# ==============


def _cmk_url_valid(url):
    return bool(url) and url.startswith(("http://", "https://")) and "<" not in url


def get_emoji(state):
    """Get emoji for notification state."""
    state_upper = state.upper()
    if state_upper in ["OK", "UP"]:
        return "🟢"
    elif state_upper in ["WARN", "WARNING"]:
        return "🟡"
    elif state_upper in ["CRIT", "CRITICAL", "DOWN"]:
        return "🔴"
    elif state_upper == "UNKNOWN":
        return "🟡"
    else:
        return ""


def main():
    # Check config
    if not TOKEN or not CHAT_ID:
        print("ERROR: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set", file=sys.stderr)
        return 0  # Exit 0 per non bloccare CheckMK
    
    # Get CheckMK environment variables
    what = os.getenv("NOTIFY_WHAT", "SERVICE")
    hostname = os.getenv("NOTIFY_HOSTNAME", "unknown")
    host_address = os.getenv("NOTIFY_HOSTADDRESS", "")
    real_ip = os.getenv("NOTIFY_HOSTLABEL_real_ip", host_address)
    
    # Build message based on notification type
    if what == "SERVICE":
        service_state = os.getenv("NOTIFY_SERVICESTATE", "UNKNOWN")
        service_desc = os.getenv("NOTIFY_SERVICEDESC", "SERVICE")
        service_output = os.getenv("NOTIFY_SERVICEOUTPUT", "N/A")
        
        emoji = get_emoji(service_state)
        
        # Message
        msg = f"[{emoji} {service_state}] Servizio → {service_desc}\n"
        msg += f"Host: {hostname} ({real_ip})\n"
        msg += f"Output: {service_output}"
        
        if _cmk_url_valid(CMK_URL):
            service_enc = urllib.parse.quote(service_desc)
            service_link = f"{CMK_URL}/check_mk/view.py?view_name=service&host={hostname}&service={service_enc}&site={SITE}"
            host_link = f"{CMK_URL}/check_mk/view.py?view_name=host&host={hostname}&site={SITE}"
            button = {
                "inline_keyboard": [[
                    {"text": " Servizio", "url": service_link},
                    {"text": " Host", "url": host_link}
                ]]
            }
        else:
            button = None
    else:
        # Host notification
        host_state = os.getenv("NOTIFY_HOSTSTATE", "UNKNOWN")
        host_output = os.getenv("NOTIFY_HOSTOUTPUT", "N/A")
        
        emoji = get_emoji(host_state)
        
        # Message
        msg = f"[{emoji} {host_state}] Host → {hostname}\n"
        msg += f"IP: {real_ip}\n"
        msg += f"Output: {host_output}"
        
        if _cmk_url_valid(CMK_URL):
            host_link = f"{CMK_URL}/check_mk/view.py?view_name=host&host={hostname}&site={SITE}"
            button = {
                "inline_keyboard": [[{"text": " Host", "url": host_link}]]
            }
        else:
            button = None
    
    # Prefix to identify VPS
    msg = f"[VPS] {msg}"
    
    # Send to Telegram
    try:
        api_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": msg,
        }
        if button is not None:
            data["reply_markup"] = json.dumps(button)
        
        encoded_data = urllib.parse.urlencode(data).encode('utf-8')
        req = urllib.request.Request(api_url, data=encoded_data)
        
        with urllib.request.urlopen(req, timeout=10) as response:
            pass  # Success
        
        return 0
    
    except (URLError, Exception) as e:
        # Log error but return 0 to not block CheckMK
        print(f"WARNING: Telegram send failed: {e}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
