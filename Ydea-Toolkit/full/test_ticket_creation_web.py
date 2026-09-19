#!/usr/bin/env python3
"""test_ticket_creation_web.py - Test ticket creation via HTML Form (Web Scraping)

Simulate a browser for:
1. Log in to the web
2. Extract CSRF token
3. Send ticket creation form

NOTE: This script depends on the HTML structure of the Ydea web page
and may stop working if the UI changes.
For production, always use the API (as in create_monitoring_ticket.py).

Usage:
    test_ticket_creation_web.py

Version: 1.0.0"""

import sys
import re
import os
import time
import http.cookiejar
import urllib.request
import urllib.parse
import mimetypes
import uuid
from pathlib import Path

# Configuration
YDEA_BASE_URL = "https://my.ydea.cloud"
COOKIE_FILE = Path("/tmp/ydea_cookies.txt")

# Colori
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'

# Load credentials from .env or environment
SCRIPT_DIR = Path(__file__).resolve().parent
ENV_FILE = SCRIPT_DIR / "../.env" # Adjust relative path as needed

username = os.environ.get("YDEA_USERNAME")
password = os.environ.get("YDEA_PASSWORD")

# If not in env, try looking in credentials.sh (legacy) or .env files
if not username or not password:
    # Try .env
    env_path = Path("/opt/ydea-toolkit/.env")
    if env_path.exists():
        with open(env_path) as f:
            content = f.read()
            u_match = re.search(r'YDEA_USERNAME=["\']?([^"\']+)["\']?', content)
            p_match = re.search(r'YDEA_PASSWORD=["\']?([^"\']+)["\']?', content)
            if u_match: username = u_match.group(1)
            if p_match: password = p_match.group(1)

if not username or not password:
    print(f"{Colors.RED} Credenziali non trovate (YDEA_USERNAME, YDEA_PASSWORD){Colors.NC}")
    sys.exit(1)


class YdeaWebClient:
    def __init__(self):
        self.cookie_jar = http.cookiejar.MozillaCookieJar(COOKIE_FILE)
        if COOKIE_FILE.exists():
            try:
                self.cookie_jar.load(ignore_discard=True, ignore_expires=True)
            except:
                pass
        
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self.opener.addheaders = [
            ('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
        ]
    
    def get(self, url):
        try:
            with self.opener.open(url) as response:
                return response.read().decode('utf-8'), response.getcode()
        except urllib.error.HTTPError as e:
            return e.read().decode('utf-8'), e.code
            
    def post(self, url, data=None, headers=None):
        try:
            if isinstance(data, dict):
                data = urllib.parse.urlencode(data).encode('utf-8')
            
            req = urllib.request.Request(url, data=data)
            if headers:
                for k, v in headers.items():
                    req.add_header(k, v)
                    
            with self.opener.open(req) as response:
                return response.read().decode('utf-8'), response.getcode(), response.geturl()
        except urllib.error.HTTPError as e:
            return e.read().decode('utf-8'), e.code, e.geturl()

    def save_cookies(self):
        self.cookie_jar.save(ignore_discard=True, ignore_expires=True)

    def login(self):
        print(" Login a YDEA (web)...")
        # 1. GET login page for CSRF
        html, code = self.get(f"{YDEA_BASE_URL}/login")
        if code != 200:
            print(" Errore caricamento pagina login")
            return False
            
        csrf = re.search(r'name="_csrf_token" value="([^"]+)"', html)
        if not csrf:
            print(" Token CSRF non trovato")
            return False
            
        csrf_token = csrf.group(1)
        
        # 2. POST login
        data = {
            "_username": username,
            "_password": password,
            "_csrf_token": csrf_token
        }
        
        html, code, url = self.post(f"{YDEA_BASE_URL}/login_check", data)
        self.save_cookies()
        
        if "logout" in html.lower() or "esci" in html.lower() or "/ticket/new" in html.lower():
            print(" Login riuscito")
            return True
        else:
            print(" Login fallito")
            return False

    def create_ticket(self, titolo, contrato_id, sla_id=None):
        print(f"\n Creazione ticket: {titolo}")
        
        # 1. GET new ticket page for form token
        html, code = self.get(f"{YDEA_BASE_URL}/ticket/new")
        form_token_match = re.search(r'name="appbundle_ticket\[_token\]" value="([^"]+)"', html)
        if not form_token_match:
            print(" Form token non trovato")
            return False
        form_token = form_token_match.group(1)
        
        # 2. Prepare Multipart Data
        boundary = '----WebKitFormBoundary' + uuid.uuid4().hex
        body = []
        
        # Helper to add fields
        def add_field(name, value):
            body.append(f'--{boundary}')
            body.append(f'Content-Disposition: form-data; name="{name}"')
            body.append('')
            body.append(str(value))
            
        add_field('appbundle_ticket[titolo]', titolo)
        add_field('appbundle_ticket[tipo]', 'Server')
        add_field('appbundle_ticket[priorita]', '30')
        add_field('appbundle_ticket[fonte]', 'Partner portal') # Empty in bash, verify? Bash said BODY+="\r\n" which is empty value? No, bash had BODY+="\r\n". Wait, bash script line 149 is empty. Source empty?
        # Bash script:
        # name="appbundle_ticket[fonte]" ... \r\n\r\n (empty)
        # But wait, line 116 in json payload of test_ticket_with_contract says "Partner portal".
        # Let's assume empty if bash script sends empty.
        # Actually line 149 in bash is empty.
        add_field('appbundle_ticket[fonte]', '') 
        
        add_field('appbundle_ticket[pagamento]', '61576')
        if sla_id:
            add_field('appbundle_ticket[serviceLevelAgreement]', sla_id)
            
        add_field('appbundle_ticket[_token]', form_token)
        add_field('azienda', '2339268')
        add_field('destinazione', '2831588')
        add_field('contatto', '')
        add_field('contratto', contrato_id)
        add_field('asset', '0')
        add_field('condizioneAddebito', 'C')
        add_field('progetto', '')
        
        # File field (empty)
        body.append(f'--{boundary}')
        body.append('Content-Disposition: form-data; name="files[]"; filename=""')
        body.append('Content-Type: application/octet-stream')
        body.append('')
        body.append('')
        
        add_field('appbundle_ticket[descrizione]', 'Test automatico creazione ticket (Python Web Client)')
        add_field('custom_attributes[int][3958]', '14553')
        
        body.append(f'--{boundary}--')
        body.append('')
        
        body_bytes = '\r\n'.join(body).encode('utf-8')
        
        headers = {
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'Content-Length': str(len(body_bytes))
        }
        
        try:
            req = urllib.request.Request(f"{YDEA_BASE_URL}/ticket/new", data=body_bytes, headers=headers)
            with self.opener.open(req) as response:
                html = response.read().decode('utf-8')
                url = response.geturl()
                code = response.getcode()
                
                # Check redirect to /ticket/ID
                match = re.search(r'/ticket/(\d+)', url)
                if match:
                    print(f" Ticket creato: ID {match.group(1)}")
                    print(f" URL: {url}")
                    return True
                elif "ticket creato" in html.lower() or "success" in html.lower():
                     print(" Ticket probabilmente creato (messaggio successo trovato)")
                     return True
                else:
                    print(f" Creazione fallita. URL finale: {url}")
                    return False
        except Exception as e:
            print(f" Errore POST: {e}")
            return False


def main():
    print(f"{Colors.BLUE}════════════════════════════════════════════════════════════════════{Colors.NC}")
    print(f"{Colors.BLUE} TEST CREAZIONE TICKET YDEA - Via Form HTML (Python){Colors.NC}")
    print(f"{Colors.BLUE}════════════════════════════════════════════════════════════════════{Colors.NC}")
    
    client = YdeaWebClient()
    if not client.login():
        sys.exit(1)
        
    contract_id = "171734"
    sla_id = "147"
    
    print("\n TEST 1: Ticket con contratto SLA Premium_Mon")
    client.create_ticket("[TEST Python] Contratto Premium_Mon", contract_id, sla_id)
    
    print("\n TEST 2: Ticket SENZA campo SLA")
    client.create_ticket("[TEST Python] Solo contratto", contract_id)

if __name__ == "__main__":
    main()
