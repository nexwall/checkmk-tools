#!/usr/bin/env python3
"""Auto Deploy CheckMK Checks - Interactive Install/Remove CheckMK script

Interactive menu for:
- Install CheckMK script (remote/full/both)
- Remove installed scripts
- Automatic host type detection
- Guaranteed forcing of executable permissions

CLI mode available for automation via curl.

Version: 1.7.0"""

import os
import sys
import subprocess
import urllib.request
import json
import argparse
import platform
import re
from pathlib import Path
from typing import Optional, Dict, List, Tuple

VERSION = "2.1.0"  # Aggiunto filtro automatico script NS8 per moduli installati
REPO_URL = "https://raw.githubusercontent.com/nethesis/checkmk-tools/main"
GITHUB_API = "https://api.github.com/repos/nethesis/checkmk-tools/contents"
CHECKMK_LOCAL_PATH = Path("/usr/lib/check_mk_agent/local")

# Colori ANSI
class Colors:
    GREEN = '\033[0;32m'
    BLUE = '\033[0;34m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    CYAN = '\033[0;36m'
    MAGENTA = '\033[0;35m'
    NC = '\033[0m'


class HostDetector:
    """Detect host type and operating system."""
    
    def __init__(self):
        self.os_info = self._read_os_release()
        self.host_type: Optional[str] = None
        self.script_category: Optional[str] = None
        self.detect_host_type()
    
    def _read_os_release(self) -> Dict[str, str]:
        """Read /etc/os-release for OS info."""
        os_info = {}
        
        if Path("/etc/os-release").exists():
            try:
                with open("/etc/os-release", 'r') as f:
                    for line in f:
                        if '=' in line:
                            key, value = line.strip().split('=', 1)
                            os_info[key] = value.strip('"')
            except IOError:
                pass
        
        return os_info
    
    def _run_command(self, cmd: List[str]) -> Tuple[int, str, str]:
        """Execute command and return (exit_code, stdout, stderr)."""
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10
            )
            return result.returncode, result.stdout, result.stderr
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return 1, "", ""
    
    def get_ns8_modules(self) -> List[str]:
        """Returns the list of NS8 modules installed via runagent -l.
        Ex: ['mail1', 'webtop1', 'nethvoice1', 'samba1', ...]"""
        if self.script_category != 'script-check-ns8':
            return []
        exit_code, stdout, _ = self._run_command(['runagent', '-l'])
        if exit_code != 0 or not stdout:
            return []
        return [line.strip() for line in stdout.split('\n') if line.strip()]

    def detect_host_type(self) -> None:
        """Detect host type based on system characteristics."""
        
        # NethServer 7 (CentOS 7 based)
        if Path("/etc/nethserver-release").exists():
            self.host_type = "NethServer 7"
            self.script_category = "script-check-ns7"
            return
        
        # NethSecurity 8 (OpenWrt based) - check BEFORE NS8 because /etc/nethserver can also exist on NethSecurity
        if Path("/etc/openwrt_release").exists():
            with open("/etc/openwrt_release", 'r') as f:
                content = f.read()
                if "NethSecurity" in content or "nethsecurity" in content.lower():
                    self.host_type = "NethSecurity 8"
                    self.script_category = "script-check-nsec8"
                    return
        
        # NethServer 8 (Rocky Linux based)
        ns8_indicators = [
            Path("/usr/bin/runagent"),
            Path("/usr/bin/api-cli"),
            Path("/etc/nethserver"),
            Path("/usr/libexec/nethserver"),
            Path("/usr/share/nethserver"),
            Path("/var/lib/nethserver"),
        ]
        if any(p.exists() for p in ns8_indicators):
            self.host_type = "NethServer 8"
            self.script_category = "script-check-ns8"
            return
        
        # CheckMK Server (OMD)
        if Path("/omd").exists() or Path("/opt/omd").exists():
            # Check presence of OMD sites
            exit_code, stdout, _ = self._run_command(["omd", "sites"])
            if exit_code == 0:
                self.host_type = "CheckMK Server (OMD)"
                self.script_category = "script-check-ubuntu"  # Usa check generici Linux
                return
        
        # Proxmox VE
        if Path("/etc/pve").exists() and Path("/usr/bin/pvesh").exists():
            self.host_type = "Proxmox VE"
            self.script_category = "script-check-proxmox"
            return
        
        # Ubuntu/Debian generic
        if self.os_info.get("ID") in ["ubuntu", "debian"]:
            os_name = self.os_info.get("NAME", "")
            os_version = self.os_info.get("VERSION_ID", "")
            self.host_type = f"{os_name} {os_version}"
            self.script_category = "script-check-ubuntu"
            return
        
        # CentOS/RHEL/Rocky generic
        if self.os_info.get("ID") in ["centos", "rhel", "rocky", "almalinux"]:
            os_name = self.os_info.get("NAME", "")
            os_version = self.os_info.get("VERSION_ID", "")
            self.host_type = f"{os_name} {os_version}"
            self.script_category = "script-check-ubuntu"  # Usa Ubuntu come fallback
            return
        
        # Fallback generico
        os_name = self.os_info.get("NAME", "Unknown")
        self.host_type = f"{os_name} (generico)"
        self.script_category = "script-check-ubuntu"


def print_header() -> None:
    """Print script header."""
    print(f"{Colors.BLUE}╔═══════════════════════════════════════════════════════════╗{Colors.NC}")
    print(f"{Colors.BLUE}║{Colors.NC}   {Colors.GREEN}Auto Deploy CheckMK Checks v{VERSION}{Colors.NC}               {Colors.BLUE}║{Colors.NC}")
    print(f"{Colors.BLUE}╠═══════════════════════════════════════════════════════════╣{Colors.NC}")
    print(f"{Colors.BLUE}║{Colors.NC}  Installazione automatica script CheckMK             {Colors.BLUE}║{Colors.NC}")
    print(f"{Colors.BLUE}╚═══════════════════════════════════════════════════════════╝{Colors.NC}")
    print()


# Mapping: keyword in script name → NS8 module prefix required
NS8_SCRIPT_MODULE_MAP = {
    'services':  'mail',
    'webtop':    'webtop',
    'tomcat':    'webtop',
    'acl':       'samba',
}


def filter_scripts_by_ns8_modules(scripts: List[Tuple[str, str]], modules: List[str]) -> Tuple[List[Tuple[str, str]], List[str]]:
    """Filter the script list based on installed NS8 modules.
    Returns (applicable_scripts, excluded_scripts)."""
    if not modules:
        return scripts, []

    # Prefissi moduli attivi (es: ['mail', 'webtop', 'nethvoice', 'samba'])
    active_prefixes = set()
    for m in modules:
        # Rimuovi suffisso numerico: mail1 → mail, webtop2 → webtop
        prefix = m.rstrip('0123456789')
        active_prefixes.add(prefix)

    applicable = []
    excluded = []

    for filename, url in scripts:
        name_lower = filename.lower()
        required_module = None
        for keyword, module in NS8_SCRIPT_MODULE_MAP.items():
            if keyword in name_lower:
                required_module = module
                break

        if required_module is None:
            # No requirements → always applicable
            applicable.append((filename, url))
        elif required_module in active_prefixes:
            # Required form present
            applicable.append((filename, url))
        else:
            excluded.append(filename)

    return applicable, excluded


def list_available_scripts(category: str, script_type: str = 'both') -> List[Tuple[str, str]]:
    """List of scripts available in the category via GitHub API.
    
    Args:
        category: Category name (e.g. script-check-ns7)
        script_type: 'remote', 'full', or 'both'
        
    Returns:
        List of tuples (filename, url_raw)"""
    scripts = []
    
    # Determina quali subdirectory scansionare
    subdirs = []
    if script_type in ['remote', 'both']:
        subdirs.append('remote')
    if script_type in ['full', 'both']:
        subdirs.append('full')
    
    for subdir in subdirs:
        api_url = f"{GITHUB_API}/{category}/{subdir}"
        
        try:
            with urllib.request.urlopen(api_url, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            for item in data:
                if item['type'] == 'file':
                    filename = item['name']
                    # Filter ONLY Python script (.py) - EXCLUDE bash (.sh)
                    if filename.endswith('.py'):
                        download_url = item['download_url']
                        scripts.append((filename, download_url))
        
        except (urllib.error.URLError, json.JSONDecodeError, KeyError):
            continue
    
    return scripts


def list_installed_scripts() -> List[str]:
    """List of scripts already installed in /usr/lib/check_mk_agent/local/.
    
    Returns:
        List of installed file names"""
    installed = []
    
    if CHECKMK_LOCAL_PATH.exists():
        for item in CHECKMK_LOCAL_PATH.iterdir():
            if item.is_file() and os.access(item, os.X_OK):
                installed.append(item.name)
    
    return sorted(installed)


def download_script(url: str, dest_path: Path) -> bool:
    """Download script from remote URL.
    
    Args:
        url: GitHub raw URL
        dest_path: Local destination path
        
    Returns:
        True if successful, False otherwise"""
    try:
        # Aggiungi cache buster
        import time
        if '?' in url:
            url += f"&v={int(time.time())}"
        else:
            url += f"?v={int(time.time())}"

        with urllib.request.urlopen(url, timeout=30) as response:
            content = response.read()
        
        with open(dest_path, 'wb') as f:
            f.write(content)
        
        # Rendi eseguibile
        os.chmod(dest_path, 0o755)
        
        return True
    
    except (urllib.error.URLError, IOError) as e:
        print(f"{Colors.RED} Errore download: {e}{Colors.NC}")
        return False


def show_scripts_menu(scripts: List[Tuple[str, str]], category: str) -> None:
    """Show available script menus with multiple selection.
    
    Args:
        scripts: List (filename, url)
        category: Script category"""
    print(f"\n{Colors.CYAN}Script disponibili in {category}:{Colors.NC}\n")
    
    # Separate by type (remote vs full)
    remote_scripts = [(i, name, url) for i, (name, url) in enumerate(scripts, 1) if '/remote/' in url]
    full_scripts = [(i, name, url) for i, (name, url) in enumerate(scripts, 1) if '/full/' in url]
    
    if remote_scripts:
        print(f"{Colors.YELLOW}▶ Remote Launchers (scaricano da GitHub):{Colors.NC}")
        for idx, name, _ in remote_scripts:
            print(f"  {Colors.BLUE}{idx:2d}){Colors.NC} {name}")
    
    if full_scripts:
        print(f"\n{Colors.YELLOW}▶ Full Scripts (standalone completi):{Colors.NC}")
        for idx, name, _ in full_scripts:
            print(f"  {Colors.BLUE}{idx:2d}){Colors.NC} {name}")
    
    print(f"\n{Colors.MAGENTA}Opzioni:{Colors.NC}")
    print(f"  {Colors.GREEN}a{Colors.NC}) Installa TUTTI gli script")
    print(f"  {Colors.GREEN}r{Colors.NC}) Installa solo remote launchers")
    print(f"  {Colors.GREEN}1,2,3{Colors.NC}) Installa script specifici (separati da virgola)")
    print(f"  {Colors.GREEN}0{Colors.NC}) Annulla")


def parse_selection(selection: str, max_idx: int) -> List[int]:
    """Parsea user input for multiple selection.
    
    Args:
        selection: User input (e.g. "1,3,5" or "1-5" or "a" or "r")
        max_idx: Maximum number of scripts
        
    Returns:
        List of selected indices"""
    if selection.lower() == 'a':
        return list(range(1, max_idx + 1))
    
    if selection.lower() == 'r':
        return []  # Gestito separatamente
    
    indices = []
    for part in selection.split(','):
        part = part.strip()
        
        # Gestione range: "1-5" → [1,2,3,4,5]
        if '-' in part:
            try:
                start, end = part.split('-', 1)
                start = int(start.strip())
                end = int(end.strip())
                
                # Valida range
                if 1 <= start <= max_idx and 1 <= end <= max_idx and start <= end:
                    indices.extend(range(start, end + 1))
            except (ValueError, AttributeError):
                # Ignora range malformati
                pass
        
        # Gestione singoli numeri: "3" → [3]
        elif part.isdigit():
            idx = int(part)
            if 1 <= idx <= max_idx:
                indices.append(idx)
    
    return sorted(set(indices))  # Rimuovi duplicati e ordina


def install_scripts(scripts: List[Tuple[str, str]], selected_indices: List[int]) -> int:
    """Install selected scripts.
    
    Args:
        scripts: Complete list (filename, url)
        selected_indexes: Indices to install
        
    Returns:
        Number of successfully installed scripts"""
    if not CHECKMK_LOCAL_PATH.exists():
        print(f"{Colors.RED} Path CheckMK non trovato: {CHECKMK_LOCAL_PATH}{Colors.NC}")
        print(f"{Colors.YELLOW}  Installare prima CheckMK Agent{Colors.NC}")
        return 0
    
    installed = 0
    
    for idx in selected_indices:
        if idx < 1 or idx > len(scripts):
            continue
        
        filename, url = scripts[idx - 1]
        
        # Remove extension for deployment (CheckMK convention)
        deploy_name = filename.rsplit('.', 1)[0] if '.' in filename else filename
        
        # CRITICAL: CheckMK ignores files with underscores! Convert _ → -
        deploy_name = deploy_name.replace('_', '-')
        
        dest_path = CHECKMK_LOCAL_PATH / deploy_name
        
        print(f"{Colors.CYAN}Installazione:{Colors.NC} {filename} → {dest_path}... ", end='', flush=True)
        
        if download_script(url, dest_path):
            # Force executable permissions (double security)
            try:
                os.chmod(dest_path, 0o755)
            except OSError:
                pass  # Ignora errori chmod, già gestito in download_script
            
            print(f"{Colors.GREEN}{Colors.NC}")
            installed += 1
        else:
            print(f"{Colors.RED}{Colors.NC}")
    
    return installed


def uninstall_scripts(script_names: List[str]) -> int:
    """Removes installed scripts.
    
    Args:
        script_names: List of file names to remove
        
    Returns:
        Number of scripts successfully removed"""
    if not CHECKMK_LOCAL_PATH.exists():
        print(f"{Colors.RED} Path CheckMK non trovato: {CHECKMK_LOCAL_PATH}{Colors.NC}")
        return 0
    
    removed = 0
    
    for script_name in script_names:
        script_path = CHECKMK_LOCAL_PATH / script_name
        
        if not script_path.exists():
            print(f"{Colors.YELLOW} Non trovato:{Colors.NC} {script_name}")
            continue
        
        print(f"{Colors.CYAN}Rimozione:{Colors.NC} {script_name}... ", end='', flush=True)
        
        try:
            script_path.unlink()
            print(f"{Colors.GREEN}{Colors.NC}")
            removed += 1
        except OSError as e:
            print(f"{Colors.RED} {e}{Colors.NC}")
    
    return removed


def show_main_menu() -> str:
    """Mostra menu principale e restituisce azione scelta.
    
    Returns:
        'install_agent', 'install', 'uninstall', 'uninstall_all', o 'exit'"""
    print(f"\n{Colors.CYAN}╔═══════════════════════════════════════╗{Colors.NC}")
    print(f"{Colors.CYAN}║  Cosa vuoi fare?                      ║{Colors.NC}")
    print(f"{Colors.CYAN}╚═══════════════════════════════════════╝{Colors.NC}\n")
    print(f"  {Colors.MAGENTA}1.{Colors.NC} Installa CheckMK Agent (prerequisito)")
    print(f"  {Colors.GREEN}2.{Colors.NC} Installa script CheckMK")
    print(f"  {Colors.RED}3.{Colors.NC} Rimuovi script installati")
    print(f"  {Colors.RED}4.{Colors.NC} Rimuovi tutto (Agent + FRPC + Script)")
    print(f"  {Colors.YELLOW}0.{Colors.NC} Esci\n")
    
    try:
        print(f"{Colors.YELLOW}Scelta:{Colors.NC} ", end='', flush=True)
        choice = input().strip()
    except EOFError:
        return 'exit'
    
    if choice == '1':
        print(f"\n{Colors.GREEN} Hai scelto:{Colors.NC} Installa CheckMK Agent\n")
        return 'install_agent'
    elif choice == '2':
        print(f"\n{Colors.GREEN} Hai scelto:{Colors.NC} Installa script CheckMK\n")
        return 'install'
    elif choice == '3':
        print(f"\n{Colors.GREEN} Hai scelto:{Colors.NC} Rimuovi script installati\n")
        return 'uninstall'
    elif choice == '4':
        print(f"\n{Colors.GREEN} Hai scelto:{Colors.NC} Rimuovi tutto (Agent + FRPC + Script)\n")
        return 'uninstall_all'
    elif choice == '0':
        print(f"\n{Colors.YELLOW} Uscita in corso...{Colors.NC}\n")
        return 'exit'
    else:
        print(f"\n{Colors.RED} Scelta non valida: '{choice}'{Colors.NC}\n")
        return 'exit'


def uninstall_agent() -> int:
    """Remove CheckMK Agent from your system.
    
    Returns:
        0 = success, 1 = error"""
    print(f"\n{Colors.YELLOW}Rimozione CheckMK Agent...{Colors.NC}\n")
    
    # Check if installed
    if not os.path.exists('/usr/bin/check_mk_agent'):
        print(f"  {Colors.YELLOW}CheckMK Agent non installato{Colors.NC}")
        return 0
    
    try:
        # Stop services
        subprocess.run(
            ['systemctl', 'stop', 'check-mk-agent-plain.socket'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        subprocess.run(
            ['systemctl', 'disable', 'check-mk-agent-plain.socket'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Remove package
        # Prova rpm
        result = subprocess.run(
            ['rpm', '-e', 'check-mk-agent'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        if result.returncode != 0:
            # Prova dpkg
            result = subprocess.run(
                ['dpkg', '-r', 'check-mk-agent'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        
        if result.returncode == 0:
            print(f"  {Colors.GREEN} CheckMK Agent rimosso{Colors.NC}")
            return 0
        else:
            print(f"  {Colors.RED} Errore rimozione CheckMK Agent{Colors.NC}")
            return 1
            
    except Exception as e:
        print(f"  {Colors.RED} Errore: {e}{Colors.NC}")
        return 1


def uninstall_frpc() -> int:
    """Removes FRPC Client from the system.
    
    Returns:
        0 = success, 1 = error"""
    print(f"\n{Colors.YELLOW}Rimozione FRPC Client...{Colors.NC}\n")
    
    # Check if installed
    if not os.path.exists('/usr/local/bin/frpc'):
        print(f"  {Colors.YELLOW}FRPC Client non installato{Colors.NC}")
        return 0
    
    try:
        # Stop and disable service
        subprocess.run(
            ['systemctl', 'stop', 'frpc'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        subprocess.run(
            ['systemctl', 'disable', 'frpc'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Remove files
        files_to_remove = [
            '/usr/local/bin/frpc',
            '/etc/systemd/system/frpc.service',
            '/etc/frp/frpc.toml'
        ]
        
        for file_path in files_to_remove:
            if os.path.exists(file_path):
                os.remove(file_path)
        
        # Remove directory if empty
        if os.path.exists('/etc/frp'):
            try:
                os.rmdir('/etc/frp')
            except OSError:
                pass  # Directory non vuota, lasciala
        
        # Reload systemd
        subprocess.run(
            ['systemctl', 'daemon-reload'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        print(f"  {Colors.GREEN} FRPC Client rimosso{Colors.NC}")
        return 0
        
    except Exception as e:
        print(f"  {Colors.RED} Errore: {e}{Colors.NC}")
        return 1


def check_agent_installed() -> Tuple[bool, str]:
    """Check if CheckMK Agent is installed.
    
    Returns:
        (is_installed, version_info)"""
    # Method 1: Check executable file
    if not os.path.exists('/usr/bin/check_mk_agent'):
        return False, ""
    
    # Method 2: Get version from package manager
    try:
        # Prova rpm (RHEL/CentOS/NethServer)
        result = subprocess.run(
            ['rpm', '-q', '--queryformat', '%{VERSION}-%{RELEASE}', 'check-mk-agent'],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            timeout=5
        )
        
        if result.returncode == 0:
            return True, result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    
    try:
        # Prova dpkg (Debian/Ubuntu)
        result = subprocess.run(
            ['dpkg-query', '-W', '-f=${Version}', 'check-mk-agent'],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            timeout=5
        )
        
        if result.returncode == 0:
            return True, result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    
    # If file exists but we can't get version
    return True, "(versione sconosciuta)"


def check_frpc_installed() -> Tuple[bool, str]:
    """Check if FRPC is installed and active.
    
    Returns:
        (is_installed, status_info)"""
    # Check if binary exists
    if not Path("/usr/local/bin/frpc").exists():
        return False, "non installato"
    
    try:
        # Check systemd service
        result = subprocess.run(
            ['systemctl', 'is-active', 'frpc'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=5
        )
        
        status = result.stdout.strip()
        if status == "active":
            return True, "attivo"
        elif status == "inactive":
            return True, "installato (non attivo)"
        else:
            return True, f"installato ({status})"
    
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # If systemctl doesn't work, just check files
        return True, "installato (stato sconosciuto)"


def show_current_status() -> Tuple[bool, bool]:
    """Show current CheckMK Agent and FRPC status.
    
    Returns:
        (agent_installed, frpc_installed)"""
    print(f"\n{Colors.CYAN}╔═══════════════════════════════════════════════════════════╗{Colors.NC}")
    print(f"{Colors.CYAN}║   Stato Attuale Sistema                                ║{Colors.NC}")
    print(f"{Colors.CYAN}╚═══════════════════════════════════════════════════════════╝{Colors.NC}\n")
    
    # CheckMK Agent
    agent_installed, agent_info = check_agent_installed()
    if agent_installed:
        print(f"  {Colors.GREEN} CheckMK Agent:{Colors.NC} Installato - {agent_info}")
    else:
        print(f"  {Colors.RED} CheckMK Agent:{Colors.NC} Non installato")
    
    # FRPC
    frpc_installed, frpc_info = check_frpc_installed()
    if frpc_installed:
        print(f"  {Colors.GREEN} FRPC Client:{Colors.NC} {frpc_info}")
    else:
        print(f"  {Colors.RED} FRPC Client:{Colors.NC} {frpc_info}")
    
    print()
    return agent_installed, frpc_installed


def install_checkmk_agent() -> int:
    """Complete workflow: Agent → FRPC → Deploy Script.
    Checks status, installs missing components, then offers deploy script.
    
    Returns:
        0 if successful, 1 if error"""
    print(f"\n{Colors.MAGENTA}╔═══════════════════════════════════════════════════════════╗{Colors.NC}")
    print(f"{Colors.MAGENTA}║   Setup Completo Sistema CheckMK                       ║{Colors.NC}")
    print(f"{Colors.MAGENTA}╚═══════════════════════════════════════════════════════════╝{Colors.NC}")
    
    # ===== STEP 1: Check and install CheckMK Agent =====
    print(f"\n{Colors.CYAN}━━━ STEP 1: CheckMK Agent ━━━{Colors.NC}\n")
    
    agent_installed, agent_info = check_agent_installed()
    
    if agent_installed:
        print(f"  {Colors.GREEN} CheckMK Agent:{Colors.NC} Già installato - {agent_info}")
        print(f"\n{Colors.YELLOW}Vuoi aggiornare/reinstallare CheckMK Agent?{Colors.NC}")
        print(f"  {Colors.GREEN}s{Colors.NC} = Sì, aggiorna agent")
        print(f"  {Colors.YELLOW}n{Colors.NC} = No, mantieni versione attuale\n")
        
        try:
            print(f"{Colors.YELLOW}Scelta [s/N]:{Colors.NC} ", end='', flush=True)
            choice = input().strip().lower()
        except EOFError:
            choice = 'n'
        
        if choice == 's':
            print(f"\n{Colors.GREEN} Hai scelto:{Colors.NC} Aggiorna agent\n")
            print(f"  {Colors.GREEN}⤷ Procedo con aggiornamento...{Colors.NC}\n")
            result = install_agent_only()
            if result != 0:
                print(f"{Colors.RED} Aggiornamento agent fallito{Colors.NC}")
                return 1
            
            # Double check version
            agent_installed, agent_info = check_agent_installed()
            if agent_installed:
                print(f"\n  {Colors.GREEN} CheckMK Agent aggiornato - {agent_info}{Colors.NC}\n")
        else:
            print(f"\n{Colors.YELLOW} Hai scelto:{Colors.NC} Mantieni versione attuale\n")
            print(f"  {Colors.YELLOW}⤷ Mantengo versione attuale{Colors.NC}\n")
    else:
        print(f"  {Colors.RED} CheckMK Agent:{Colors.NC} Non installato")
        print(f"  {Colors.GREEN}⤷ Procedo con installazione...{Colors.NC}\n")
        
        result = install_agent_only()
        if result != 0:
            print(f"{Colors.RED} Installazione agent fallita{Colors.NC}")
            return 1
        
        # Ricontrolla
        agent_installed, agent_info = check_agent_installed()
        if agent_installed:
            print(f"\n  {Colors.GREEN} CheckMK Agent installato con successo - {agent_info}{Colors.NC}\n")
        else:
            print(f"\n  {Colors.YELLOW} Agent potrebbe non essere stato installato{Colors.NC}\n")
    
    # ===== STEP 2: Check and install FRPC =====
    print(f"{Colors.CYAN}━━━ STEP 2: FRPC Client (tunnel remoto) ━━━{Colors.NC}\n")
    
    frpc_installed, frpc_info = check_frpc_installed()
    
    if frpc_installed:
        print(f"  {Colors.GREEN} FRPC Client:{Colors.NC} {frpc_info}")
        print(f"  {Colors.YELLOW}⤷ Salto installazione FRPC{Colors.NC}\n")
    else:
        print(f"  {Colors.RED} FRPC Client:{Colors.NC} Non installato")
        print(f"\n{Colors.YELLOW}Vuoi installare FRPC per monitoraggio remoto tramite tunnel?{Colors.NC}")
        print(f"  {Colors.GREEN}s{Colors.NC} = Sì, installa FRPC")
        print(f"  {Colors.YELLOW}n{Colors.NC} = No, salta\n")
        
        try:
            print(f"{Colors.YELLOW}Scelta [s/N]:{Colors.NC} ", end='', flush=True)
            choice = input().strip().lower()
        except EOFError:
            choice = 'n'
        
        if choice == 's':
            print(f"\n{Colors.GREEN} Hai scelto:{Colors.NC} Installa FRPC\n")
            print(f"  {Colors.GREEN}⤷ Procedo con installazione FRPC...{Colors.NC}\n")
            result = install_frpc_only()
            if result == 0:
                frpc_installed, frpc_info = check_frpc_installed()
                if frpc_installed:
                    print(f"\n  {Colors.GREEN} FRPC installato con successo - {frpc_info}{Colors.NC}\n")
            else:
                print(f"\n  {Colors.YELLOW} FRPC non installato{Colors.NC}\n")
        else:
            print(f"\n{Colors.YELLOW} Hai scelto:{Colors.NC} Salta FRPC\n")
            print(f"  {Colors.YELLOW}⤷ Installazione FRPC saltata{Colors.NC}\n")
    
    # ===== STEP 3: Deploy Script CheckMK =====
    print(f"{Colors.CYAN}━━━ STEP 3: Deploy Script CheckMK ━━━{Colors.NC}\n")
    
    print(f"{Colors.YELLOW}Vuoi procedere con l'installazione degli script CheckMK?{Colors.NC}")
    print(f"  {Colors.GREEN}s{Colors.NC} = Sì, vai al deploy script")
    print(f"  {Colors.YELLOW}n{Colors.NC} = No, esci\n")
    
    try:
        print(f"{Colors.YELLOW}Scelta [s/N]:{Colors.NC} ", end='', flush=True)
        choice = input().strip().lower()
    except EOFError:
        choice = 'n'
    
    if choice == 's':
        print(f"\n{Colors.GREEN} Hai scelto:{Colors.NC} Procedi con deploy script\n")
        print(f"{Colors.GREEN} Setup base completato. Passo al deploy script...{Colors.NC}\n")
        # It returns 2 as a signal to continue with deploy script
        return 2
    else:
        print(f"\n{Colors.YELLOW} Hai scelto:{Colors.NC} Esci senza deploy script\n")
        print(f"{Colors.GREEN} Setup completato{Colors.NC}\n")
        return 0


def install_agent_only() -> int:
    """Install CheckMK Agent directly (without external script).
    Detects OS, downloads correct package and installs it.
    
    Returns:
        0 if successful, 1 if error"""
    print(f"{Colors.YELLOW}Download e installazione CheckMK Agent...{Colors.NC}\n")
    
    try:
        # Rileva tipo OS
        if Path("/etc/os-release").exists():
            with open("/etc/os-release", 'r') as f:
                os_release = f.read()
            
            if any(x in os_release.lower() for x in ["debian", "ubuntu"]):
                pkg_type = "deb"
                pkg_manager = "apt"
            elif any(x in os_release.lower() for x in ["centos", "rhel", "rocky", "almalinux", "nethserver"]):
                pkg_type = "rpm"
                pkg_manager = "yum"
            else:
                print(f"{Colors.RED} OS non supportato{Colors.NC}")
                return 1
        elif Path("/etc/nethserver-release").exists():
            pkg_type = "rpm"
            pkg_manager = "yum"
        else:
            print(f"{Colors.RED} Impossibile rilevare sistema operativo{Colors.NC}")
            return 1
        
        print(f"  Tipo pacchetto: {pkg_type}")
        
        # URL base CheckMK agents
        base_url = os.environ.get("CMK_AGENTS_URL", "https://<your-checkmk-server>/monitoring/check_mk/agents")
        
        # Download listing agent
        print(f"  Recupero lista agent da CheckMK server...")
        
        request = urllib.request.Request(base_url + "/", headers={'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(request, timeout=30) as response:
            listing = response.read().decode('utf-8')
        
        # Find latest version
        if pkg_type == "deb":
            pattern = r'check-mk-agent_[\d.]+p[\d]+-[\d]+_all\.deb'
        else:  # rpm
            pattern = r'check-mk-agent-[\d.]+p[\d]+-[\d]+\.noarch\.rpm'
        
        matches = re.findall(pattern, listing)
        if not matches:
            print(f"{Colors.RED} Nessun pacchetto agent trovato{Colors.NC}")
            return 1
        
        # Get latest version (sort)
        latest_pkg = sorted(matches)[-1]
        pkg_url = f"{base_url}/{latest_pkg}"
        
        print(f"  Versione: {latest_pkg}")
        print(f"  Download da: {pkg_url}\n")
        
        # Download package
        tmp_pkg = f"/tmp/{latest_pkg}"
        
        print(f"{Colors.YELLOW}Download in corso...{Colors.NC}")
        request = urllib.request.Request(pkg_url, headers={'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(request, timeout=60) as response:
            with open(tmp_pkg, 'wb') as f:
                f.write(response.read())
        
        print(f"{Colors.GREEN} Download completato{Colors.NC}\n")
        
        # Install package
        print(f"{Colors.YELLOW}Installazione pacchetto...{Colors.NC}")
        
        if pkg_type == "deb":
            result = subprocess.run(
                ['dpkg', '-i', tmp_pkg],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            if result.returncode != 0:
                # Fix dipendenze
                subprocess.run(['apt-get', 'install', '-f', '-y'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        else:  # rpm
            result = subprocess.run(
                ['rpm', '-Uvh', '--replacepkgs', tmp_pkg],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
        
        # Cleanup
        try:
            os.remove(tmp_pkg)
        except OSError:
            pass
        
        if result.returncode != 0 and "already installed" not in result.stderr.lower():
            print(f"{Colors.RED} Errore installazione: {result.stderr}{Colors.NC}")
            return 1
        
        print(f"{Colors.GREEN} Pacchetto installato{Colors.NC}\n")
        
        # Configure systemd sockets
        print(f"{Colors.YELLOW}Configurazione socket systemd...{Colors.NC}")
        
        # Disable old-style services
        subprocess.run(['systemctl', 'stop', 'check-mk-agent.socket', 'cmk-agent-ctl-daemon.service'], 
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['systemctl', 'disable', 'check-mk-agent.socket', 'cmk-agent-ctl-daemon.service'],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Crea socket plain TCP
        socket_config = """[Unit]
Description=Checkmk Agent (TCP 6556 plain)
Documentation=https://docs.checkmk.com/

[Socket]
ListenStream=6556
Accept=yes

[Install]
WantedBy=sockets.target"""
        
        service_config = """[Unit]
Description=Checkmk Agent Service (plain)

[Service]
Type=simple
ExecStart=/usr/bin/check_mk_agent
StandardInput=socket
User=root"""
        
        with open('/etc/systemd/system/check-mk-agent-plain.socket', 'w') as f:
            f.write(socket_config)
        
        with open('/etc/systemd/system/check-mk-agent-plain@.service', 'w') as f:
            f.write(service_config)
        
        # Enable and start socket
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'enable', 'check-mk-agent-plain.socket'], 
                      check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['systemctl', 'start', 'check-mk-agent-plain.socket'], check=True)
        
        print(f"{Colors.GREEN} Socket systemd configurato e attivo (porta 6556){Colors.NC}\n")
        
        return 0
    
    except Exception as e:
        print(f"{Colors.RED} Errore: {e}{Colors.NC}\n")
        import traceback
        traceback.print_exc()
        return 1


def install_frpc_only() -> int:
    """Install FRPC Client only (requires configuration).
    
    Returns:
        0 if successful, 1 if error"""
    print(f"{Colors.YELLOW}═══════════════════════════════════════════════════════════{Colors.NC}")
    print(f"{Colors.CYAN}Configurazione FRPC{Colors.NC}")
    print(f"{Colors.YELLOW}═══════════════════════════════════════════════════════════{Colors.NC}\n")
    
    try:
        # Ottieni hostname
        hostname_result = subprocess.run(
            ['hostname'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=5
        )
        default_hostname = hostname_result.stdout.strip() if hostname_result.returncode == 0 else "host"
        
        # Ask for configuration
        print(f"Nome host [{default_hostname}]: ", end='', flush=True)
        frpc_hostname = input().strip() or default_hostname
        
        print("Remote FRP server: ", end='', flush=True)
        frp_server = input().strip() or os.environ.get("FRP_SERVER", "")
        
        while True:
            print(f"Porta remota (es: 20001): ", end='', flush=True)
            remote_port = input().strip()
            if remote_port.isdigit():
                break
            print(f"{Colors.RED}Porta deve essere un numero{Colors.NC}")
        
        while True:
            print(f"Token FRP: ", end='', flush=True)
            auth_token = input().strip()
            if auth_token:
                break
            print(f"{Colors.RED}Token obbligatorio{Colors.NC}")
        
        print(f"\n{Colors.YELLOW}Installazione FRPC...{Colors.NC}\n")
        
        # Create configuration directory
        os.makedirs("/etc/frp", exist_ok=True)
        
        # Write configuration
        config = f"""[common]
server_addr = "{frp_server}"
server_port = 7000
auth.method = "token"
auth.token = "{auth_token}"
tls.enable = true
log.to = "/var/log/frpc.log"
log.level = "info"

[{frpc_hostname}]
type = "tcp"
local_ip = "127.0.0.1"
local_port = 6556
remote_port = {remote_port}"""
        
        with open("/etc/frp/frpc.toml", 'w') as f:
            f.write(config)
        
        # Download FRPC binary if it does not exist
        if not Path("/usr/local/bin/frpc").exists():
            frp_version = "0.64.0"
            import platform
            arch = platform.machine()
            if arch == "x86_64":
                arch = "amd64"
            
            frpc_url = f"https://github.com/fatedier/frp/releases/download/v{frp_version}/frp_{frp_version}_linux_{arch}.tar.gz"
            
            print(f"Download FRPC {frp_version}...")
            subprocess.run(['wget', '-q', '-O', '/tmp/frpc.tar.gz', frpc_url], check=True)
            subprocess.run(['tar', '-xzf', '/tmp/frpc.tar.gz', '-C', '/tmp'], check=True)
            subprocess.run(['cp', f'/tmp/frp_{frp_version}_linux_{arch}/frpc', '/usr/local/bin/frpc'], check=True)
            subprocess.run(['chmod', '+x', '/usr/local/bin/frpc'], check=True)
            os.remove('/tmp/frpc.tar.gz')
        
        # Create systemd service
        service = """[Unit]
Description=FRP Client Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/frpc -c /etc/frp/frpc.toml
Restart=on-failure
RestartSec=5s
User=root

[Install]
WantedBy=multi-user.target"""
        
        with open("/etc/systemd/system/frpc.service", 'w') as f:
            f.write(service)
        
        # Enable and start service
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'enable', 'frpc'], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['systemctl', 'start', 'frpc'], check=True)
        
        print(f"{Colors.GREEN} FRPC configurato e avviato{Colors.NC}")
        print(f"  Tunnel: {frp_server}:{remote_port} → localhost:6556")
        
        return 0
    
    except Exception as e:
        print(f"{Colors.RED} Errore installazione FRPC: {e}{Colors.NC}\n")
        return 1


def ask_script_type() -> str:
    """Asks the user what type of script to install.
    
    Returns:
        'remote', 'full', or 'both'"""
    print(f"\n{Colors.CYAN}╔═══════════════════════════════════════╗{Colors.NC}")
    print(f"{Colors.CYAN}║  Quale tipo di script?                ║{Colors.NC}")
    print(f"{Colors.CYAN}╚═══════════════════════════════════════╝{Colors.NC}\n")
    print(f"  {Colors.GREEN}1.{Colors.NC} Remote launchers (eseguono script da GitHub)")
    print(f"  {Colors.GREEN}2.{Colors.NC} Full scripts (script completi locali)")
    print(f"  {Colors.GREEN}3.{Colors.NC} Entrambi (remote + full)")
    print(f"  {Colors.YELLOW}0.{Colors.NC} Annulla\n")
    
    try:
        print(f"{Colors.YELLOW}Scelta:{Colors.NC} ", end='', flush=True)
        choice = input().strip()
    except EOFError:
        return 'remote'  # Default per pipe execution
    
    if choice == '1':
        print(f"\n{Colors.GREEN} Hai scelto:{Colors.NC} Remote launchers\n")
        return 'remote'
    elif choice == '2':
        print(f"\n{Colors.GREEN} Hai scelto:{Colors.NC} Full scripts\n")
        return 'full'
    elif choice == '3':
        print(f"\n{Colors.GREEN} Hai scelto:{Colors.NC} Entrambi (remote + full)\n")
        return 'both'
    elif choice == '0':
        print(f"\n{Colors.YELLOW} Annullato{Colors.NC}\n")
        return 'cancel'
    else:
        print(f"\n{Colors.YELLOW} Scelta non valida '{choice}', uso default: Remote launchers{Colors.NC}\n")
        return 'remote'


def main() -> int:
    """Main entry point."""
    
    # Parse argomenti CLI
    parser = argparse.ArgumentParser(
        description='Auto Deploy CheckMK Checks - Rileva host e installa script corretti',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Interactive mode (menu)
  %(prog)s
  
  # Install all scripts automatically
  %(prog)s --install-all --yes
  
  # Install specific scripts
  %(prog)s --install "1,3,5" --yes
  
  # Remove installed scripts (interactive)
  %(prog)s --uninstall
  
  # One-liner via curl
  curl -fsSL URL | sudo python3 - --install-all --yes
  
Note: ONLY full (full/) scripts are now installed, no more remote launchers."""
    )
    
    parser.add_argument('--install-all', action='store_true',
                        help='Installa tutti gli script senza menu')
    parser.add_argument('--install-remote', action='store_true',
                        help='[OBSOLETO] Ora installa sempre script full')
    parser.add_argument('--install', type=str, metavar='INDICES',
                        help='Installa script specifici (es: "1,2,3")')
    parser.add_argument('--type', type=str, choices=['remote', 'full', 'both'],
                        help='[OBSOLETO] Ignorato - installa sempre script full')
    parser.add_argument('--uninstall', action='store_true',
                        help='Rimuovi script installati')
    parser.add_argument('--yes', '-y', action='store_true',
                        help='Conferma automaticamente senza chiedere')
    parser.add_argument('--version', action='version',
                        version=f'%(prog)s {VERSION}')
    
    args = parser.parse_args()
    
    print_header()
    
    # Verify root
    if os.geteuid() != 0:
        print(f"{Colors.RED} Questo script richiede privilegi root{Colors.NC}")
        print(f"{Colors.YELLOW}  Esegui con: sudo {sys.argv[0]}{Colors.NC}\n")
        return 1
    
    # ===== MENU INTERATTIVO (se nessun argomento CLI specificato) =====
    if not any([args.uninstall, args.install_all, args.install, args.type, args.install_remote]):
        # Interactive mode with main menu
        action = show_main_menu()
        
        if action == 'exit':
            print(f"{Colors.YELLOW}Uscita{Colors.NC}")
            return 0
        
        elif action == 'install_agent':
            # Setup completo: Agent → FRPC → Deploy Script
            result = install_checkmk_agent()
            
            if result == 2:
                # User wants to continue with deploy script
                # Chiedi tipo script
                script_type = ask_script_type()
                if script_type == 'cancel':
                    print(f"{Colors.YELLOW}Annullato{Colors.NC}")
                    return 0
                
                # Forza modalità install-all
                args.install_all = True
                args.type = script_type
                # Continue the flow below
            else:
                # Setup complete or error
                return result
        
        elif action == 'uninstall':
            # Forza modalità uninstall
            args.uninstall = True
        
        elif action == 'uninstall_all':
            # Complete removal: Script → FRPC → Agent
            print(f"\n{Colors.YELLOW}╔═══════════════════════════════════════════════════════════╗{Colors.NC}")
            print(f"{Colors.YELLOW}║    RIMOZIONE COMPLETA SISTEMA CHECKMK                  ║{Colors.NC}")
            print(f"{Colors.YELLOW}╚═══════════════════════════════════════════════════════════╝{Colors.NC}\n")
            print(f"{Colors.RED}Verranno rimossi:{Colors.NC}")
            print(f"  • Tutti gli script CheckMK installati")
            print(f"  • FRPC Client (tunnel remoto)")
            print(f"  • CheckMK Agent\n")
            
            if not args.yes:
                print(f"{Colors.YELLOW}Sei sicuro di voler procedere? [s/N]:{Colors.NC} ", end='', flush=True)
                try:
                    confirm = input().strip().lower()
                except EOFError:
                    confirm = 'n'
                
                if confirm != 's':
                    print(f"\n{Colors.YELLOW} Hai scelto:{Colors.NC} Annulla rimozione completa\n")
                    print(f"{Colors.YELLOW}Rimozione annullata{Colors.NC}")
                    return 0
                else:
                    print(f"\n{Colors.GREEN} Hai scelto:{Colors.NC} Conferma rimozione completa\n")
            
            print(f"{Colors.CYAN}━━━ STEP 1: Rimozione Script CheckMK ━━━{Colors.NC}")
            installed = list_installed_scripts()
            if installed:
                result = uninstall_scripts(installed)
                if result == 0:
                    print(f"  {Colors.GREEN} Script rimossi: {len(installed)}{Colors.NC}")
            else:
                print(f"  {Colors.YELLOW}Nessuno script installato{Colors.NC}")
            
            print(f"\n{Colors.CYAN}━━━ STEP 2: Rimozione FRPC Client ━━━{Colors.NC}")
            uninstall_frpc()
            
            print(f"\n{Colors.CYAN}━━━ STEP 3: Rimozione CheckMK Agent ━━━{Colors.NC}")
            uninstall_agent()
            
            print(f"\n{Colors.GREEN} Rimozione completa terminata{Colors.NC}\n")
            return 0
        
        elif action == 'install':
            # Interactive installation mode
            # The type will be asked later in the flow
            pass
    
    # ===== REMOVAL MODE =====
    if args.uninstall:
        print(f"\n{Colors.YELLOW}Modalità: Rimozione script installati{Colors.NC}\n")
        
        installed = list_installed_scripts()
        
        if not installed:
            print(f"{Colors.YELLOW}Nessuno script installato in {CHECKMK_LOCAL_PATH}{Colors.NC}")
            return 0
        
        print(f"{Colors.GREEN}Script installati ({len(installed)}):{Colors.NC}\n")
        for i, name in enumerate(installed, 1):
            print(f"  {Colors.GREEN}{i:2d}.{Colors.NC} {name}")
        
        print(f"\n{Colors.YELLOW}Seleziona script da rimuovere{Colors.NC}")
        print(f"  {Colors.CYAN}Esempio:{Colors.NC} 1,3,5 oppure 1-3 oppure all")
        print(f"  {Colors.YELLOW}0.{Colors.NC} Annulla\n")
        
        try:
            print(f"{Colors.YELLOW}Selezione:{Colors.NC} ", end='', flush=True)
            selection = input().strip().lower()
        except EOFError:
            print(f"\n{Colors.RED} Input non disponibile{Colors.NC}")
            return 1
        
        if selection == '0':
            print(f"{Colors.YELLOW}Rimozione annullata{Colors.NC}")
            return 0
        
        # Parse selezione
        if selection == 'all':
            to_remove = installed
        else:
            indices = parse_selection(selection, len(installed))
            to_remove = [installed[i - 1] for i in indices]
        
        if not to_remove:
            print(f"{Colors.RED} Nessuno script selezionato{Colors.NC}")
            return 1
        
        # Confirm removal
        print(f"\n{Colors.RED} Verranno rimossi {len(to_remove)} script{Colors.NC}")
        for name in to_remove:
            print(f"  - {name}")
        
        if not args.yes:
            try:
                print(f"\n{Colors.YELLOW}Confermi rimozione? (s/n):{Colors.NC} ", end='', flush=True)
                confirm = input().strip().lower()
            except EOFError:
                confirm = 'n'
            
            if confirm not in ['s', 'si', 'y', 'yes']:
                print(f"\n{Colors.YELLOW} Hai scelto:{Colors.NC} Annulla rimozione\n")
                print(f"{Colors.YELLOW}Rimozione annullata{Colors.NC}")
                return 0
            else:
                print(f"\n{Colors.GREEN} Hai scelto:{Colors.NC} Conferma rimozione\n")
        
        # Perform removal
        print(f"{Colors.RED}▶ Rimozione in corso...{Colors.NC}\n")
        removed = uninstall_scripts(to_remove)
        
        print(f"\n{Colors.BLUE}{'='*60}{Colors.NC}")
        print(f"{Colors.GREEN} Rimozione completata{Colors.NC}")
        print(f"  Script rimossi: {removed}/{len(to_remove)}")
        print(f"{Colors.BLUE}{'='*60}{Colors.NC}\n")
        
        return 0
    
    # ===== INSTALLATION MODE =====
    
    # Detect hosts
    print(f"{Colors.YELLOW}Rilevamento sistema in corso...{Colors.NC}\n")
    detector = HostDetector()
    
    print(f"{Colors.GREEN} Sistema rilevato:{Colors.NC}")
    print(f"  {Colors.CYAN}Tipo Host:{Colors.NC} {detector.host_type}")
    print(f"  {Colors.CYAN}Categoria Script:{Colors.NC} {detector.script_category}")
    
    if detector.script_category is None:
        print(f"\n{Colors.RED} Impossibile determinare categoria script appropriata{Colors.NC}")
        return 1
    
    # ALWAYS USE FULL SCRIPT (no more remote launchers)
    script_type = 'full'
    
    # Backward compatibility: ignora --type e --install-remote
    if args.type or args.install_remote:
        print(f"\n{Colors.YELLOW}[INFO] Ora vengono installati SOLO script completi (full/), non più launcher{Colors.NC}")
    
    # List of available scripts
    print(f"\n{Colors.YELLOW}Recupero lista script da GitHub...{Colors.NC}")
    scripts = list_available_scripts(detector.script_category, script_type)
    
    if not scripts:
        print(f"{Colors.RED} Nessuno script trovato per categoria: {detector.script_category} (tipo: {script_type}){Colors.NC}")
        return 1
    
    print(f"{Colors.GREEN} Trovati {len(scripts)} script completi{Colors.NC}")

    # Filter scripts for installed NS8 modules
    if detector.script_category == 'script-check-ns8':
        ns8_modules = detector.get_ns8_modules()
        if ns8_modules:
            scripts, excluded = filter_scripts_by_ns8_modules(scripts, ns8_modules)
            print(f"{Colors.CYAN}ℹ Moduli NS8 attivi: {', '.join(ns8_modules)}{Colors.NC}")
            if excluded:
                print(f"{Colors.YELLOW} Script esclusi (modulo non installato): {', '.join(excluded)}{Colors.NC}")
            print(f"{Colors.GREEN} Script applicabili a questo host: {len(scripts)}{Colors.NC}")

    # Determine selection (from args or interactive input)
    selected_indices: List[int] = []
    
    if args.install_all:
        # Install all
        selected_indices = list(range(1, len(scripts) + 1))
        print(f"\n{Colors.CYAN}Modalità: Installa TUTTI gli script completi{Colors.NC}")
    
    elif args.install:
        # Install specific scripts
        selected_indices = parse_selection(args.install, len(scripts))
        print(f"\n{Colors.CYAN}Modalità: Installa script specifici{Colors.NC}")
    
    else:
        # Modalità interattiva
        show_scripts_menu(scripts, detector.script_category)
        
        try:
            print(f"\n{Colors.YELLOW}Selezione:{Colors.NC} ", end='', flush=True)
            selection = input().strip()
        except EOFError:
            print(f"\n{Colors.RED} Input non disponibile (esegui interattivamente o usa --install-*)${Colors.NC}")
            print(f"{Colors.YELLOW}Suggerimento:{Colors.NC} Usa --install-all --yes per installazione automatica")
            return 1
        
        if selection == '0':
            print(f"{Colors.YELLOW}Installazione annullata{Colors.NC}")
            return 0
        
        # Parse selezione
        selected_indices = parse_selection(selection, len(scripts))
    
    if not selected_indices:
        print(f"{Colors.RED} Nessuno script selezionato{Colors.NC}")
        return 1
    
    # Confirm installation
    print(f"\n{Colors.YELLOW}Verranno installati {len(selected_indices)} script in:{Colors.NC}")
    print(f"  {CHECKMK_LOCAL_PATH}\n")
    
    if not args.yes:
        try:
            print(f"{Colors.YELLOW}Confermi? (s/n):{Colors.NC} ", end='', flush=True)
            confirm = input().strip().lower()
        except EOFError:
            print(f"\n{Colors.YELLOW}Conferma automatica (usa --yes per evitare prompt){Colors.NC}")
            confirm = 's'
        
        if confirm not in ['s', 'si', 'y', 'yes']:
            print(f"{Colors.YELLOW}Installazione annullata{Colors.NC}")
            return 0
    else:
        print(f"{Colors.GREEN}Conferma automatica (--yes){Colors.NC}")
    
    # Installation
    print(f"\n{Colors.GREEN}▶ Installazione in corso...{Colors.NC}\n")
    installed = install_scripts(scripts, selected_indices)
    
    # Check executable permissions post-installation
    executable_count = 0
    if CHECKMK_LOCAL_PATH.exists():
        for item in CHECKMK_LOCAL_PATH.iterdir():
            if item.is_file() and os.access(item, os.X_OK):
                executable_count += 1
    
    # Riepilogo
    print(f"\n{Colors.BLUE}{'='*60}{Colors.NC}")
    print(f"{Colors.GREEN} Installazione completata{Colors.NC}")
    print(f"  Script installati: {installed}/{len(selected_indices)}")
    print(f"  Script eseguibili: {executable_count}")
    print(f"  Path: {CHECKMK_LOCAL_PATH}")
    print(f"{Colors.BLUE}{'='*60}{Colors.NC}\n")
    
    # Post-installation tips
    print(f"{Colors.CYAN}Prossimi step:{Colors.NC}")
    print(f"  1. Verifica output agent: {Colors.YELLOW}check_mk_agent{Colors.NC}")
    print(f"  2. Forza discovery su CheckMK server")
    print(f"  3. Check visibili in CheckMK UI\n")
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrotto dall'utente{Colors.NC}")
        sys.exit(130)
    except Exception as e:
        print(f"{Colors.RED} Errore inatteso: {e}{Colors.NC}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
