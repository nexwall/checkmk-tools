#!/usr/bin/env python3
"""ns8-audit-report-table.py - NS8 Report with Compact Table Format

Complete NethServer 8 environment report with table view:
  1) Active Directory Users (Samba)
  2) AD user password expiration dates (4 column table)
  3) AD groups with members (2 column table, one row per member)
  4) Network share permissions with complete ACLs (3 column table)
  5) WebTop shares (3 column table)

Output: Directory /tmp/ns8-audit-YYYYMMDD-HHMMSS/

Version: 2.8.1"""

import subprocess
import sys
import re
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import tempfile
import socket
import getpass
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

VERSION = "2.12.1"
MAX_PWD_AGE_DAYS = 42

# Cache globale SID
SID_CACHE: Dict[str, str] = {}

# Contatori globali
GLOBAL_USER_COUNT = 0
GLOBAL_GROUP_COUNT = 0
GLOBAL_COMPUTER_COUNT = 0
GLOBAL_SHARE_COUNT = 0
GLOBAL_WEBTOP_COUNT = 0

# ANSI colors
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'

# Excluded groups
EXCLUDE_GROUPS = [
    "Denied RODC Password Replication Group",
    "Allowed RODC Password Replication Group",
    "DnsUpdateProxy",
    "Enterprise Read-Only Domain Controllers",
    "Network Configuration Operators",
    "Pre-Windows 2000 Compatible Access",
    "Incoming Forest Trust Builders",
    "Terminal Server License Servers",
    "Cryptographic Operators",
    "Remote Desktop Users",
    "RAS and IAS Servers",
    "Event Log Readers",
    "Guests",
    "Certificate Service DCOM Access",
    "Read-Only Domain Controllers",
    "Windows Authorization Access Group",
    "Performance Monitor Users",
]

# System SIDs to skip
SYSTEM_SIDS = [
    "S-1-5-18",  # SYSTEM
    "S-1-5-32-544",  # Administrators
    "S-1-5-2",   # Network
    "S-1-1-0",   # Everyone
]


def log_info(msg: str) -> None:
    """Print info message."""
    print(f"{BLUE}[INFO]{NC} {msg}")


def log_success(msg: str) -> None:
    """Print success message."""
    print(f"{GREEN}[OK]{NC} {msg}")


def log_warn(msg: str) -> None:
    """Print warning message."""
    print(f"{YELLOW}[WARN]{NC} {msg}")


def log_error(msg: str) -> None:
    """Print error message."""
    print(f"{RED}[ERROR]{NC} {msg}")


def run_command(cmd: List[str], timeout: int = 30) -> Tuple[int, str, str]:
    """Execute command with timeout."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "Timeout"
    except FileNotFoundError:
        return 127, "", "Command not found"
    except Exception as e:
        return 1, "", str(e)


def sid_to_name(sid: str, samba_module: str) -> Optional[str]:
    """Convert SID to username/groupname using wbinfo.
    Uses global SID_CACHE for performance.
    
    Args:
        sid: Windows SID (e.g., S-1-5-21-...)
        samba_module: Samba module name
        
    Returns:
        Entity name or None if system SID or error"""
    global SID_CACHE
    
    # Skip system SIDs
    if sid in SYSTEM_SIDS:
        return None
    
    # Check cache
    if sid in SID_CACHE:
        return SID_CACHE[sid] if SID_CACHE[sid] else None
    
    # Query wbinfo
    cmd = [
        "runagent", "-m", samba_module,
        "podman", "exec", "samba-dc",
        "wbinfo", "--sid-to-name", sid
    ]
    
    exit_code, stdout, _ = run_command(cmd, timeout=5)
    
    if exit_code == 0 and stdout.strip():
        # Extract name (format: DOMAIN\name type)
        parts = stdout.strip().split()
        if parts:
            name = parts[0]
            # Cache it
            SID_CACHE[sid] = name
            return name
    
    # Cache negative result
    SID_CACHE[sid] = ""
    return None


def decode_access_mask(mask_str: str) -> str:
    """Decode Windows access_mask to RW/RO.
    
    Args:
        mask_str: Hex mask (e.g., "0x001f01ff")
        
    Returns:
        "RW" or "RO""""
    try:
        mask = int(mask_str, 16) if mask_str.startswith("0x") else int(mask_str)
        
        # Check WRITE (0x0002) or DELETE (0x00010000) bits
        if (mask & 0x0002) or (mask & 0x00010000):
            return "RW"
        else:
            return "RO"
    except (ValueError, TypeError):
        return "RO"


def check_prerequisites() -> Tuple[Optional[str], Optional[str]]:
    """Check prerequisites and find modules."""
    log_info("Verifica prerequisiti...")
    
    exit_code, _, _ = run_command(["runagent", "--list-modules"])
    if exit_code != 0:
        log_error("runagent non trovato")
        sys.exit(1)
    
    exit_code, stdout, _ = run_command(["runagent", "--list-modules"])
    samba_modules = [line.strip() for line in stdout.splitlines() if re.match(r'^samba\d+$', line.strip())]
    
    if not samba_modules:
        log_error("Nessun modulo Samba trovato")
        sys.exit(1)
    
    samba_module = samba_modules[0]
    log_success(f"Modulo Samba: {samba_module}")
    
    # Find WebTop with Postgres
    webtop_modules = [line.strip() for line in stdout.splitlines() if re.match(r'^webtop\d+$', line.strip())]
    webtop_module = None
    
    for wt_mod in webtop_modules:
        cmd = ["runagent", "-m", wt_mod, "podman", "ps", "--format", "{{.Names}}"]
        exit_code, stdout_ps, _ = run_command(cmd, timeout=10)
        if exit_code == 0 and "postgres" in stdout_ps.lower():
            webtop_module = wt_mod
            log_success(f"Modulo WebTop: {webtop_module} (con Postgres attivo)")
            break
    
    if not webtop_module and webtop_modules:
        log_warn("Nessun modulo WebTop con Postgres attivo")
    elif not webtop_modules:
        log_warn("Nessun modulo WebTop trovato")
    
    return samba_module, webtop_module


def collect_ad_users(samba_module: str, output_dir: Path) -> int:
    """Collect AD users and return count.
    
    Returns:
        Number of users collected"""
    log_info("Raccolta utenti AD...")
    
    users_dir = output_dir / "01_users"
    users_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = users_dir / "users.txt"
    
    cmd = [
        "runagent", "-m", samba_module,
        "podman", "exec", "samba-dc",
        "samba-tool", "user", "list"
    ]
    
    exit_code, stdout, _ = run_command(cmd)
    
    if exit_code == 0:
        output_file.write_text(stdout, encoding='utf-8')
        user_count = len([l for l in stdout.splitlines() if l.strip()])
        log_success(f"Utenti AD raccolti: {user_count}")
        return user_count
    else:
        log_error("Fallita raccolta utenti")
        return 0


def collect_password_expiry_table(samba_module: str, output_dir: Path) -> None:
    """Collect and display expiry password as table for ALL users."""
    log_info("Raccolta scadenze password (tabella)...")
    
    users_file = output_dir / "01_users" / "users.txt"
    password_dir = output_dir / "02_password"
    password_dir.mkdir(parents=True, exist_ok=True)
    
    if not users_file.exists():
        log_error("File utenti non trovato")
        return
    
    users = [line.strip() for line in users_file.read_text().splitlines() if line.strip()]
    
    # Collect data for ALL users (header printed AFTER data collection)
    pwd_data = []
    user_count = 0
    
    for username in users:
        user_count += 1
        
        # Progress every 10 users
        if user_count % 10 == 0:
            log_info(f"  Progress: {user_count}/{len(users)} utenti elaborati...")
        
        cmd = [
            "runagent", "-m", samba_module,
            "podman", "exec", "samba-dc",
            "samba-tool", "user", "show", username
        ]
        
        exit_code, stdout, _ = run_command(cmd, timeout=10)
        
        if exit_code != 0:
            pwd_data.append((username, "N/A", "N/A", "N/A"))
            continue
        
        pwd_match = re.search(r'^pwdLastSet:\s+(\d+)', stdout, re.MULTILINE)
        
        if not pwd_match or int(pwd_match.group(1)) == 0:
            pwd_data.append((username, "Mai cambiata", "Mai", "N/A"))
            continue
        
        assert pwd_match is not None
        try:
            pwd_last_set = int(pwd_match.group(1))
            # FILETIME to Unix timestamp
            unix_time = int((pwd_last_set - 116444736000000000) / 10000000)
            pwd_date = datetime.fromtimestamp(unix_time)
            
            last_change = pwd_date.strftime("%Y-%m-%d")
            expires_date = pwd_date + timedelta(days=MAX_PWD_AGE_DAYS)
            expires_str = expires_date.strftime("%Y-%m-%d")
            days_left = (expires_date - datetime.now()).days
            
            pwd_data.append((username, last_change, expires_str, days_left))
            
        except (ValueError, OverflowError, OSError):
            pwd_data.append((username, "Errore", "N/A", "N/A"))
    
    # Print table header AFTER all data collected
    print()
    print("=" * 120)
    print("  SCADENZE PASSWORD UTENTI AD")
    print("=" * 120)
    print()
    print(f"{'UTENTE':<25} {'ULTIMO CAMBIO':<20} {'SCADENZA':<20} {'GIORNI RIMANENTI':<20}")
    print(f"{'-'*25} {'-'*20} {'-'*20} {'-'*20}")
    
    # Display ALL users on console
    for username, last_change, expires_str, days_left in pwd_data:
        # Color coding
        if days_left == "N/A" or days_left == "Errore":
            days_display = str(days_left)
        elif isinstance(days_left, int):
            if days_left < 0:
                days_display = f"{RED}Scaduta{NC}"
            elif days_left < 7:
                days_display = f"{RED}{days_left}{NC}"
            elif days_left < 14:
                days_display = f"{YELLOW}{days_left}{NC}"
            else:
                days_display = str(days_left)
        else:
            days_display = str(days_left)
        
        print(f"{username:<25} {last_change:<20} {expires_str:<20} {days_display:<20}")
    
    print()
    print("=" * 120)
    log_success(f"Tabella password completata ({len(pwd_data)} utenti totali)")
    
    # Write MD file with ALL data
    md_file = output_dir / "01_password_expiry.md"
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write("# Password Expiry Report\n\n")
        f.write(f"Report generato: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n")
        
        # Count stats
        expired_count = sum(1 for _, _, _, d in pwd_data if isinstance(d, int) and d < 0)
        expiring_count = sum(1 for _, _, _, d in pwd_data if isinstance(d, int) and 0 <= d <= 7)
        
        f.write("## Riepilogo\n\n")
        f.write(f"- **Utenti totali:** {len(pwd_data)}\n")
        f.write(f"- **Password scadute:** {expired_count}\n")
        f.write(f"- **Password in scadenza (≤7 giorni):** {expiring_count}\n\n")
        f.write("---\n\n")
        f.write("## Tabella Scadenza Password\n\n")
        f.write(f"| {'Utente':<20} | {'Scade Il':<12} | {'Giorni':<10} | {'Status':<18} |\n")
        f.write(f"|{'-'*22}|{'-'*14}|{'-'*12}|{'-'*20}|\n")
        
        for username, _, expires_str, days_left in pwd_data:
            if days_left == "N/A":
                status = "Info N/A"
            elif days_left == "Errore":
                status = "Errore"
            elif not isinstance(days_left, int):
                status = str(days_left)
            elif days_left < 0:
                status = "[!] Scaduta"
            elif days_left <= 7:
                status = "[*] In scadenza"
            else:
                status = "[OK] Valida"
            
            f.write(f"| {username:<20} | {expires_str:<12} | {str(days_left):<10} | {status:<18} |\n")
        
        f.write("\n")
    
    global GLOBAL_USER_COUNT
    GLOBAL_USER_COUNT = len(pwd_data)


def collect_ad_groups_table(samba_module: str, output_dir: Path) -> int:
    """Collect AD groups with members and display as table.
    
    Returns:
        Number of groups collected"""
    log_info("Raccolta gruppi AD (tabella)...")
    
    # Get group list
    cmd = [
        "runagent", "-m", samba_module,
        "podman", "exec", "samba-dc",
        "samba-tool", "group", "list"
    ]
    
    exit_code, stdout, _ = run_command(cmd)
    
    if exit_code != 0:
        log_error("Fallita raccolta gruppi")
        return 0
    
    all_groups = [g.strip() for g in stdout.splitlines() if g.strip()]
    groups = [g for g in all_groups if g not in EXCLUDE_GROUPS]
    
    # Collect members for each group (header printed AFTER data collection)
    displayed_rows = 0
    group_member_data = []
    
    for idx, groupname in enumerate(groups, 1):
        # Progress every 10 groups
        if idx % 10 == 0:
            log_info(f"  Progress: {idx}/{len(groups)} gruppi...")
        
        # Query members
        cmd_members = [
            "runagent", "-m", samba_module,
            "podman", "exec", "samba-dc",
            "samba-tool", "group", "listmembers", groupname
        ]
        
        exit_code, stdout_members, _ = run_command(cmd_members, timeout=10)
        
        members = []
        computers = []
        
        if exit_code == 0 and stdout_members.strip():
            for member in stdout_members.strip().splitlines():
                member = member.strip()
                if member.endswith('$'):
                    computers.append(member)
                else:
                    members.append(member)
        
        # Store data for MD files
        group_member_data.append((groupname, members, computers))
    
    # Print table header AFTER all data collected
    print()
    print("=" * 80)
    print("  GRUPPI ACTIVE DIRECTORY")
    print("=" * 80)
    print()
    print(f"{'GRUPPO':<40} {'MEMBRI':<40}")
    print(f"{'-'*40} {'-'*40}")
    
    # Display on console: one row per member (ALL members shown)
    displayed_rows = 0
    for groupname, members, computers in group_member_data:
        if members:
            for member in members:
                print(f"{groupname[:39]:<40} {member[:39]:<40}")
                displayed_rows += 1  # type: ignore[operator]
        elif not computers:
            print(f"{groupname[:39]:<40} {'(nessun membro)':<40}")
            displayed_rows += 1  # type: ignore[operator]
    
    print()
    print("=" * 80)
    log_success(f"Gruppi AD raccolti: {len(groups)} ({displayed_rows} membri mostrati)")
    
    # Domain Computers console table
    total_computers = sum(len(comps) for _, _, comps in group_member_data)
    if total_computers > 0:
        # Collect all computers with their groups
        computer_list = []
        for groupname, _, computers in group_member_data:
            for computer in computers:
                computer_list.append((groupname, computer))
        
        # Sort by group name
        computer_list.sort()
        
        # Print console table
        print()
        print("=" * 80)
        print("  DOMAIN COMPUTER")
        print("=" * 80)
        print()
        print(f"Totale computer a dominio: {total_computers}")
        print()
        print(f"{'GRUPPO':<40} {'COMPUTER':<40}")
        print(f"{'-'*40} {'-'*40}")
        
        for groupname, computer in computer_list:
            print(f"{groupname[:39]:<40} {computer[:39]:<40}")
        
        print()
        print("=" * 80)
        log_success(f"Domain Computer: {total_computers} computer joinati al dominio")
    
    # Write MD file with ALL groups and members
    md_file = output_dir / "02_gruppi_ad.md"
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write("# Gruppi Active Directory\n\n")
        f.write(f"Report generato: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n")
        f.write(f"**Totale gruppi:** {len(all_groups)}\n\n")
        f.write("---\n\n")
        f.write("## Tabella Membri Gruppi\n\n")
        f.write(f"| {'Gruppo':<35} | {'Membro':<35} |\n")
        f.write(f"|{'-'*37}|{'-'*37}|\n")
        
        # Write one row per member
        for groupname, members, computers in group_member_data:
            if members:
                for member in members:
                    f.write(f"| {groupname[:35]:<35} | {member[:35]:<35} |\n")
            elif not computers:
                f.write(f"| {groupname[:35]:<35} | {'(nessun membro)':<35} |\n")
        
        f.write("\n")
    
    # Calculate total computers for global counter
    total_computers = sum(len(comps) for _, _, comps in group_member_data)
    
    # Create separate Domain Computers MD files
    if total_computers > 0:
        computers_md_file = output_dir / "05_domain_computers.md"
        with open(computers_md_file, 'w', encoding='utf-8') as f:
            f.write("# Domain Computer\n\n")
            f.write(f"Report generato: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n")
            f.write(f"**Totale computer a dominio:** {total_computers}\n\n")
            f.write("---\n\n")
            f.write("## Tabella Computer A Dominio\n\n")
            f.write(f"| {'Gruppo':<35} | {'Computer':<35} |\n")
            f.write(f"|{'-'*37}|{'-'*37}|\n")
            
            for groupname, _, computers in group_member_data:
                for computer in computers:
                    f.write(f"| {groupname[:35]:<35} | {computer[:35]:<35} |\n")
            
            f.write("\n")
        
        log_success(f"Report computer generato → 05_domain_computers.md")
    
    global GLOBAL_GROUP_COUNT, GLOBAL_COMPUTER_COUNT
    GLOBAL_GROUP_COUNT = len(groups)
    GLOBAL_COMPUTER_COUNT = total_computers
    
    return len(groups)


def collect_shares_table(samba_module: str, output_dir: Path) -> int:
    """Collect Samba shares with real ACL permissions and display as table.
    
    Returns:
        Number of shares collected"""
    log_info("Raccolta share Samba (tabella)...")
    
    shares_dir = output_dir / "03_shares"
    shares_dir.mkdir(parents=True, exist_ok=True)
    
    # List shares
    cmd = [
        "runagent", "-m", samba_module,
        "podman", "exec", "samba-dc",
        "smbclient", "-L", "localhost", "-N"
    ]
    
    exit_code, stdout, _ = run_command(cmd)
    
    if exit_code != 0:
        log_error("Impossibile listare share")
        return 0
    
    shares = []
    for line in stdout.splitlines():
        if "Disk" in line:
            parts = line.split()
            if parts:
                share_name = parts[0].strip()
                if share_name not in ['IPC$', 'print$', 'sysvol', 'netlogon']:
                    shares.append(share_name)
    
    if not shares:
        log_warn("Nessuno share trovato")
        return 0
    
    log_info(f"Trovati {len(shares)} share")
    
    # Collect ACL for each share (header printed AFTER data collection)
    share_data = []
    acl_success = 0
    acl_failed = 0
    
    for idx, share_name in enumerate(shares, 1):
        # Progress every 5 shares
        if idx % 5 == 0:
            log_info(f"  Progress: {idx}/{len(shares)} share...")
        
        # Get share path
        cmd_path = [
            "runagent", "-m", samba_module,
            "podman", "exec", "samba-dc",
            "net", "conf", "getparm", share_name, "path"
        ]
        
        exit_code, stdout_path, _ = run_command(cmd_path, timeout=10)
        
        if exit_code != 0 or not stdout_path.strip():
            share_path = "N/A"
            share_data.append((share_name, share_path, [], []))
            acl_failed += 1
            continue
        
        share_path = stdout_path.strip()
        
        # Get ACL
        cmd_acl = [
            "runagent", "-m", samba_module,
            "podman", "exec", "samba-dc",
            "samba-tool", "ntacl", "get", share_path
        ]
        
        exit_code, stdout_acl, _ = run_command(cmd_acl, timeout=15)
        
        if exit_code != 0 or "trustee" not in stdout_acl:
            share_data.append((share_name, share_path, [], []))
            acl_failed += 1  # type: ignore[operator]
            continue
        
        acl_success += 1  # type: ignore[operator]
        
        # Parse ACL (access_mask comes BEFORE trustee in output)
        users_rw = []
        users_ro = []
        
        current_mask = None
        current_sid = None
        
        for line in stdout_acl.splitlines():
            # Extract access_mask
            mask_match = re.search(r'access_mask\s*:\s*(0x[0-9a-f]+)', line)
            if mask_match:
                current_mask = mask_match.group(1)
            
            # Extract trustee SID
            sid_match = re.search(r'trustee\s*:\s*(S-1-[0-9-]+)', line)
            if sid_match:
                current_sid = sid_match.group(1)
                
                # Process when we have both
                if current_mask and current_sid:
                    entity_name = sid_to_name(current_sid, samba_module)
                    
                    if entity_name:
                        perm_type = decode_access_mask(current_mask)
                        
                        if perm_type == "RW":
                            users_rw.append(entity_name)
                        else:
                            users_ro.append(entity_name)
                    
                    # Reset
                    current_mask = None
                    current_sid = None
        
        share_data.append((share_name, share_path, users_rw, users_ro))
    
    # Print table header AFTER all data collected
    print()
    print("=" * 130)
    print("  SHARE SAMBA")
    print("=" * 130)
    print()
    print(f"{'SHARE':<30} {'PERCORSO':<40} {'UTENTE/GRUPPO':<20} {'PERM':<10}")
    print(f"{'-'*30} {'-'*40} {'-'*20} {'-'*10}")
    
    # Display on console: show ALL permissions details
    displayed_rows = 0
    for share_name, share_path, users_rw, users_ro in share_data:
        path_display = share_path[:39] if len(share_path) > 39 else share_path  # type: ignore[index]
        
        # Display one row for permission
        if users_rw:
            for user in users_rw:  # type: ignore[union-attr]
                user_display = user[:29] if len(user) > 29 else user  # type: ignore[index]
                print(f"{share_name:<30} {path_display:<40} {user_display:<20} RW")
                displayed_rows += 1  # type: ignore[operator]
        
        if users_ro:
            for user in users_ro:  # type: ignore[union-attr]
                user_display = user[:29] if len(user) > 29 else user  # type: ignore[index]
                print(f"{share_name:<30} {path_display:<40} {user_display:<20} RO")
                displayed_rows += 1  # type: ignore[operator]
        
        # If no permissions, show one row
        if not users_rw and not users_ro:
            print(f"{share_name:<30} {path_display:<40} {'(nessun permesso)':<20} -")
            displayed_rows += 1
    
    print()
    print("=" * 130)
    log_success(f"Share raccolte: {len(shares)} ({displayed_rows} permessi mostrati, ACL: {acl_success} OK, {acl_failed} errori)")
    
    # Write MD file with ALL share permissions
    md_file = output_dir / "04_share_permissions.md"
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write("# Share Samba - Permessi\n\n")
        f.write(f"Report generato: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n")
        f.write(f"**Totale share:** {len(shares)}\n\n")
        f.write("---\n\n")
        f.write("## Tabella Share - Permessi\n\n")
        f.write(f"| {'Share':<30} | {'Utente/Gruppo':<35} | {'Permesso':<10} |\n")
        f.write(f"|{'-'*32}|{'-'*37}|{'-'*12}|\n")
        
        # Write one line for permission
        for share_name, share_path, users_rw, users_ro in share_data:
            has_perms = False
            
            for user in users_rw:
                f.write(f"| {share_name[:30]:<30} | {user[:35]:<35} | {'RW':<10} |\n")
                has_perms = True
            
            for user in users_ro:
                f.write(f"| {share_name[:30]:<30} | {user[:35]:<35} | {'RO':<10} |\n")
                has_perms = True
            
            if not has_perms:
                f.write(f"| {share_name[:30]:<30} | {'(nessun permesso)':<35} | {'-':<10} |\n")
        
        f.write("\n")
    
    global GLOBAL_SHARE_COUNT
    GLOBAL_SHARE_COUNT = len(shares)
    
    return len(shares)


def collect_webtop_sharing(webtop_module: Optional[str], samba_module: str, output_dir: Path) -> int:
    """Collect WebTop email sharing information.
    
    Returns:
        Number of email shares collected"""
    md_file = output_dir / "03_webtop_shares.md"
    
    if not webtop_module:
        log_warn("Modulo WebTop non disponibile - skip raccolta email sharing")
        with open(md_file, 'w', encoding='utf-8') as f:
            f.write("# Condivisioni Email WebTop\n\n")
            f.write("[!] **Modulo WebTop non disponibile**\n")
        return 0
    
    log_info("Raccolta condivisioni email WebTop...")
    
    # Find Postgres container
    cmd_ps = [
        "runagent", "-m", webtop_module,
        "podman", "ps", "--format", "{{.Names}}"
    ]
    
    exit_code, stdout_ps, _ = run_command(cmd_ps, timeout=10)
    
    postgres_container = None
    if exit_code == 0:
        for line in stdout_ps.splitlines():
            if "postgres" in line.lower():
                postgres_container = line.strip()
                break
    
    if not postgres_container:
        log_warn("Container Postgres non trovato")
        with open(md_file, 'w', encoding='utf-8') as f:
            f.write("# Condivisioni Email WebTop\n\n")
            f.write("[ERRORE] **Errore:** Container Postgres non trovato\n")
        return 0
    
    # Find WebTop database
    cmd_list_db = [
        "runagent", "-m", webtop_module,
        "podman", "exec", postgres_container,
        "psql", "-U", "postgres", "-t", "-c", "\\l"
    ]
    
    exit_code, stdout_db, _ = run_command(cmd_list_db, timeout=10)
    
    webtop_db = None
    if exit_code == 0:
        for line in stdout_db.splitlines():
            if "webtop" in line.lower():
                parts = line.strip().split()
                if parts:
                    webtop_db = parts[0]
                    break
    
    if not webtop_db:
        log_warn("Database WebTop non trovato")
        with open(md_file, 'w', encoding='utf-8') as f:
            f.write("# Condivisioni Email WebTop\n\n")
            f.write("[ERRORE] **Errore:** Database WebTop non trovato\n")
        return 0
    
    # Get UUID → username mapping
    mapping_query = "SELECT user_uid, user_id FROM core.users;"
    
    cmd_mapping = [
        "runagent", "-m", webtop_module,
        "podman", "exec", "-i", postgres_container,
        "psql", "-U", "postgres", "-d", webtop_db, "-t"
    ]
    
    try:
        result = subprocess.run(
            cmd_mapping,
            input=mapping_query,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15
        )
        
        uuid_map = {}
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.strip().split('|')
                if len(parts) >= 2:
                    uuid = parts[0].strip()
                    username = parts[1].strip()
                    if uuid and username:
                        uuid_map[uuid.lower()] = username
        
        log_info(f"Caricati {len(uuid_map)} mapping UUID → username")
        
    except (subprocess.TimeoutExpired, Exception) as e:
        log_warn(f"Impossibile caricare mapping UUID: {e}")
        uuid_map = {}
    
    # Get sharing data
    shares_query = """SELECT s.share_id, s.user_uid AS owner, s.service_id, s.key AS mailbox_path, 
                    s.instance, sd.user_uid AS shared_with, sd.value AS permissions 
                    FROM core.shares s LEFT JOIN core.shares_data sd ON s.share_id = sd.share_id 
                    WHERE s.service_id LIKE '%mail%' ORDER BY s.user_uid, s.share_id, sd.user_uid;"""
    
    cmd_shares = [
        "runagent", "-m", webtop_module,
        "podman", "exec", "-i", postgres_container,
        "psql", "-U", "postgres", "-d", webtop_db
    ]
    
    try:
        result = subprocess.run(
            cmd_shares,
            input=shares_query,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20
        )
        
        shares_data = []
        
        if result.returncode == 0:
            # Parse output lines
            for line in result.stdout.splitlines():
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 6 and parts[0].isdigit():
                    share_id = parts[0]
                    owner_uuid = parts[1]
                    mailbox = parts[3]
                    shared_uuid = parts[5]
                    perms = parts[6] if len(parts) > 6 else "N/A"
                    
                    # Resolve UUIDs
                    owner_name = uuid_map.get(owner_uuid.lower(), owner_uuid)
                    shared_name = uuid_map.get(shared_uuid.lower(), shared_uuid)
                    
                    # Parse permissions JSON
                    perm_icon = "RO"
                    if "shareIdentity" in perms and "true" in perms:
                        perm_icon = "RW"
                    
                    shares_data.append((owner_name, shared_name, perm_icon))
        
        log_success(f"Raccolte {len(shares_data)} condivisioni email")
        
    except (subprocess.TimeoutExpired, Exception) as e:
        log_warn(f"Errore query condivisioni: {e}")
        shares_data = []
    
    # Write MD file
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write("# Condivisioni Email WebTop\n\n")
        f.write(f"Report generato: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n")
        f.write(f"**Totale condivisioni:** {len(shares_data)}\n\n")
        f.write("---\n\n")
        
        if shares_data:
            f.write("## Tabella Condivisioni\n\n")
            f.write(f"| {'Da':<22} | {'A':<22} | {'Tipo':<10} |\n")
            f.write(f"|{'-'*24}|{'-'*24}|{'-'*12}|\n")
            
            for owner, shared, perm in shares_data:
                f.write(f"| {owner[:22]:<22} | {shared[:22]:<22} | {perm:<10} |\n")  # type: ignore[index]
            
            f.write("\n")
        else:
            f.write("*Nessuna condivisione email configurata*\n")
    
    global GLOBAL_WEBTOP_COUNT
    GLOBAL_WEBTOP_COUNT = len(shares_data)
    
    return len(shares_data)


def generate_summary_table(output_dir: Path) -> None:
    """Generate summary in table format."""
    global GLOBAL_USER_COUNT, GLOBAL_GROUP_COUNT, GLOBAL_COMPUTER_COUNT, GLOBAL_SHARE_COUNT, GLOBAL_WEBTOP_COUNT
    
    print()
    print("=" * 80)
    print("  RIEPILOGO REPORT")
    print("=" * 80)
    print()
    print(f"{'CATEGORIA':<30} {'TOTALE':<20}")
    print(f"{'-'*30} {'-'*20}")
    print(f"{'Utenti AD':<30} {GLOBAL_USER_COUNT:<20}")
    print(f"{'Gruppi AD':<30} {GLOBAL_GROUP_COUNT:<20}")
    print(f"{'Computer A Dominio':<30} {GLOBAL_COMPUTER_COUNT:<20}")
    print(f"{'Share Samba':<30} {GLOBAL_SHARE_COUNT:<20}")
    print(f"{'Condivisioni WebTop':<30} {GLOBAL_WEBTOP_COUNT:<20}")
    print()
    print("=" * 80)
    
    # Write to file
    summary_file = output_dir / "SUMMARY_TABLE.txt"
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("NS8 AUDIT REPORT TABLE VERSION\n")
        f.write(f"Version: {VERSION}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"Utenti AD: {GLOBAL_USER_COUNT}\n")
        f.write(f"Gruppi AD: {GLOBAL_GROUP_COUNT}\n")
        f.write(f"Computer A Dominio: {GLOBAL_COMPUTER_COUNT}\n")
        f.write(f"Share Samba: {GLOBAL_SHARE_COUNT}\n")
        f.write(f"Condivisioni WebTop: {GLOBAL_WEBTOP_COUNT}\n")
    
    log_success("Summary table generato")


def send_email_interactive(output_dir: Path) -> bool:
    """Send report via email with interactive prompts.
    
    Args:
        output_dir: Report output directory
        
    Returns:
        True if email sent successfully, False otherwise"""
    print()
    print("=" * 80)
    
    try:
        send_prompt = input("Vuoi inviare il report via email? (s/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        log_info("Invio email saltato.")
        return False
    
    if send_prompt not in ['s', 'si', 'y', 'yes']:
        log_info("Invio email saltato.")
        return False
    
    print()
    log_info("Configurazione invio email...")
    
    try:
        # Email destinatario
        print()
        recipient = input("Email destinatario: ").strip()
        if not recipient:
            log_error("Email destinatario obbligatoria")
            return False
        
        # Mittente (From)
        print()
        hostname = socket.gethostname()
        from_default = f"root@{hostname}"
        from_email = input(f"Mostra come mittente (From) [{from_default}]: ").strip()
        if not from_email:
            from_email = from_default
        
        # SMTP server
        print()
        smtp_server = input("Server SMTP [smtp.example.com]: ").strip()
        if not smtp_server:
            log_error("Server SMTP obbligatorio")
            return False
        
        # SMTP port
        print()
        smtp_port_str = input("Porta SMTP [587]: ").strip()
        smtp_port = int(smtp_port_str) if smtp_port_str else 587
        
        # Username SMTP
        print()
        smtp_user = input("Username SMTP: ").strip()
        if not smtp_user:
            log_error("Username SMTP obbligatorio")
            return False
        
        # SMTP password (hidden)
        print()
        smtp_pass = getpass.getpass("Password SMTP: ")
        if not smtp_pass:
            log_error("Password SMTP obbligatoria")
            return False
        
    except (EOFError, KeyboardInterrupt):
        print()
        log_error("Input interrotto dall'utente")
        return False
    
    print()
    log_info("Preparazione email...")
    
    # Subject with hostname and date
    subject = f"NS8 Audit Report - {hostname} - {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    
    # Costruisci email MIME multipart
    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = recipient
    msg['Subject'] = subject
    
    # Body: riepilogo testuale senza emoji
    body_text = f"""NS8 Audit Report - {hostname}
Date: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

========================================================================================
REPORT SUMMARY
========================================================================================

AD Users: {GLOBAL_USER_COUNT}
AD Groups: {GLOBAL_GROUP_COUNT}
Domain Computer: {GLOBAL_COMPUTER_COUNT}
Share Samba: {GLOBAL_SHARE_COUNT}
WebTop Shares: {GLOBAL_WEBTOP_COUNT}

========================================================================================

Full details are available in the attached files in Markdown format.

Attached files:
- 00_REPORT_SUMMARY.md (general summary)
- 01_password_expiry.md (password expiring)
- 02_gruppi_ad.md (groups and members)
- 03_webtop_shares.md (WebTop shares)
- 04_share_permissions.md (Samba share permissions)
- 05_domain_computers.md (domain computers)"""
    
    msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
    
    # Attachments: all .md files
    md_files = [
        "00_REPORT_SUMMARY.md",
        "01_password_expiry.md",
        "02_gruppi_ad.md",
        "03_webtop_shares.md",
        "04_share_permissions.md",
        "05_domain_computers.md"
    ]
    
    attached_count = 0
    for md_filename in md_files:
        md_path = output_dir / md_filename
        if md_path.exists():
            with open(md_path, 'rb') as f:
                part = MIMEBase('text', 'markdown')
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename="{md_filename}"')
                msg.attach(part)
                attached_count += 1  # type: ignore[operator]
    
    log_info(f"Allegati: {attached_count} file")
    
    # Invia email via SMTP
    log_info(f"Invio email a {recipient} tramite {smtp_server}:{smtp_port}...")
    
    try:
        # SMTP connection with STARTTLS
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        
        log_success(f"Email inviata con successo a {recipient}")
        return True
        
    except smtplib.SMTPAuthenticationError:
        log_error("Errore autenticazione SMTP - Verifica username e password")
        return False
    except smtplib.SMTPException as e:
        log_error(f"Errore SMTP: {e}")
        return False
    except socket.timeout:
        log_error(f"Timeout connessione a {smtp_server}:{smtp_port}")
        return False
    except Exception as e:
        log_error(f"Errore invio email: {e}")
        return False


def main() -> int:
    """Main entry point."""
    global GLOBAL_USER_COUNT, GLOBAL_GROUP_COUNT, GLOBAL_COMPUTER_COUNT, GLOBAL_SHARE_COUNT, GLOBAL_WEBTOP_COUNT
    
    print("=" * 80)
    print(f"NS8 Audit Report - Table Version v{VERSION}")
    print("=" * 80)
    print()
    
    # Parse arguments
    output_base = Path("/tmp")
    
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--help":
            print("Uso: ns8-audit-report-table.py [--output-dir /path]")
            return 0
        elif sys.argv[i] == "--output-dir" and i + 1 < len(sys.argv):
            output_base = Path(sys.argv[i + 1])
            i += 2
        else:
            i += 1
    
    # Create output directory
    report_date = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = output_base / f"ns8-audit-{report_date}"
    output_dir.mkdir(parents=True, exist_ok=True)
    log_success(f"Output: {output_dir}")
    
    # Check prerequisites
    samba_module, webtop_module = check_prerequisites()
    print()
    
    # Collect data with table display
    assert samba_module is not None, "Modulo Samba non trovato"
    GLOBAL_USER_COUNT = collect_ad_users(samba_module, output_dir)
    collect_password_expiry_table(samba_module, output_dir)
    GLOBAL_GROUP_COUNT = collect_ad_groups_table(samba_module, output_dir)
    GLOBAL_SHARE_COUNT = collect_shares_table(samba_module, output_dir)
    GLOBAL_WEBTOP_COUNT = collect_webtop_sharing(webtop_module, samba_module, output_dir)
    
    print()
    
    # Generate summary
    generate_summary_table(output_dir)
    
    print()
    log_success("Report completato!")
    log_info(f"Output: {output_dir}")
    
    # Send email (interactive prompt)
    send_email_interactive(output_dir)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
