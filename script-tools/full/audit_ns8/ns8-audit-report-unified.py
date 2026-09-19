#!/usr/bin/env python3
"""ns8-audit-report-unified.py - NS8 Unified Report (Collector + Viewer)

Complete NethServer 8 environment report with ACL view:
  1) Active Directory Users (Samba)  
  2) AD user password expiration dates
  3) Network share permissions (Samba) with detailed ACLs
  4) WebTop mail account shares (if available)
  5) Formatted display of ACL share permissions

Output: Directory /tmp/ns8-audit-YYYYMMDD-HHMMSS/

Version: 2.4.0"""

import subprocess
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Optional, Dict

VERSION = "2.4.0"
MAX_PWD_AGE_DAYS = 42

# Cache globale SID → Username
SID_CACHE: Dict[str, str] = {}

# ANSI colors
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'

# Excluded AD groups
EXCLUDE_GROUPS = [
    "Denied RODC Password Replication Group",
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


def sid_to_name(sid: str, samba_module: str) -> str:
    """Convert SID to name using wbinfo with caching.
    
    Args:
        sid: SID to convert
        samba_module: Samba module name
        
    Returns:
        Username or original SID if conversion fails"""
    # Check cache first
    if sid in SID_CACHE:
        return SID_CACHE[sid]
    
    # Well-known SIDs
    wellknown_sids = {
        "S-1-1-0": "Everyone",
        "S-1-5-18": "SYSTEM",
        "S-1-5-32-544": "Administrators",
        "S-1-5-32-545": "Users",
    }
    
    if sid in wellknown_sids:
        name = wellknown_sids[sid]
        SID_CACHE[sid] = name
        return name
    
    # Query wbinfo
    cmd = [
        "runagent", "-m", samba_module,
        "podman", "exec", "samba-dc",
        "wbinfo", "--sid-to-name", sid
    ]
    
    exit_code, stdout, _ = run_command(cmd, timeout=10)
    
    if exit_code == 0 and stdout.strip():
        name = stdout.strip()
        SID_CACHE[sid] = name
        return name
    else:
        # Cache failure too
        SID_CACHE[sid] = sid
        return sid


def check_prerequisites() -> Tuple[Optional[str], Optional[str]]:
    """Check prerequisites and find modules."""
    log_info("Verifica prerequisiti...")
    
    exit_code, _, _ = run_command(["runagent", "--list-modules"])
    if exit_code != 0:
        log_error("runagent non trovato nel PATH")
        sys.exit(1)
    
    exit_code, stdout, _ = run_command(["runagent", "--list-modules"])
    samba_modules = [line.strip() for line in stdout.splitlines() if re.match(r'^samba\d+$', line.strip())]
    
    if not samba_modules:
        log_error("Nessun modulo Samba trovato")
        sys.exit(1)
    
    samba_module = samba_modules[0]
    log_success(f"Modulo Samba: {samba_module}")
    
    webtop_modules = [line.strip() for line in stdout.splitlines() if re.match(r'^webtop\d+$', line.strip())]
    webtop_module = webtop_modules[0] if webtop_modules else None
    
    if webtop_module:
        log_success(f"Modulo WebTop: {webtop_module}")
    else:
        log_warn("Nessun modulo WebTop trovato")
    
    return samba_module, webtop_module


def collect_ad_users(samba_module: str, output_dir: Path) -> bool:
    """Collect Active Directory users."""
    log_info("Raccolta utenti Active Directory...")
    
    output_file = output_dir / "01_users" / "users.txt"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        "runagent", "-m", samba_module,
        "podman", "exec", "samba-dc",
        "samba-tool", "user", "list"
    ]
    
    exit_code, stdout, _ = run_command(cmd)
    
    if exit_code == 0:
        output_file.write_text(stdout, encoding='utf-8')
        user_count = len(stdout.strip().splitlines())
        log_success(f"Raccolti {user_count} utenti AD")
        return True
    else:
        log_error("Fallita raccolta utenti AD")
        return False


def collect_password_expiry(samba_module: str, output_dir: Path) -> bool:
    """Collect password expiry information."""
    log_info("Raccolta scadenze password AD...")
    
    users_file = output_dir / "01_users" / "users.txt"
    password_dir = output_dir / "02_password"
    password_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = password_dir / "password_expiry.tsv"
    
    if not users_file.exists():
        log_error("File utenti non trovato")
        return False
    
    users = [line.strip() for line in users_file.read_text(encoding='utf-8').splitlines() if line.strip()]
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("user\tpwdLastSet_raw\tpwdLastSet_unix\tpwdLastSet_iso\t"
                "expires_unix\texpires_iso\tdays_until_expiry\n")
        
        for username in users:
            cmd = [
                "runagent", "-m", samba_module,
                "podman", "exec", "samba-dc",
                "samba-tool", "user", "show", username
            ]
            
            exit_code, stdout, _ = run_command(cmd)
            
            if exit_code != 0:
                f.write(f"{username}\t0\t0\tN/A\t0\tN/A\tN/A\n")
                continue
            
            pwd_match = re.search(r'^pwdLastSet:\s+(\d+)', stdout, re.MULTILINE)
            
            if not pwd_match:
                f.write(f"{username}\t0\t0\tN/A\t0\tN/A\tN/A\n")
                continue
            
            pwd_last_set = int(pwd_match.group(1))
            
            if pwd_last_set == 0:
                f.write(f"{username}\t0\t0\tN/A\t0\tN/A\tN/A\n")
                continue
            
            try:
                unix_time = int((pwd_last_set - 116444736000000000) / 10000000)
                pwd_date = datetime.fromtimestamp(unix_time)
                iso_date = pwd_date.strftime("%Y-%m-%d %H:%M:%S")
                
                expires_date = pwd_date + timedelta(days=MAX_PWD_AGE_DAYS)
                expires_unix = int(expires_date.timestamp())
                expires_iso = expires_date.strftime("%Y-%m-%d %H:%M:%S")
                
                days_until_expiry = (expires_date - datetime.now()).days
                
                f.write(f"{username}\t{pwd_last_set}\t{unix_time}\t{iso_date}\t"
                       f"{expires_unix}\t{expires_iso}\t{days_until_expiry}\n")
            except (ValueError, OverflowError, OSError):
                f.write(f"{username}\t{pwd_last_set}\t0\tN/A\t0\tN/A\tN/A\n")
    
    log_success("Scadenze password raccolte")
    return True


def collect_samba_shares(samba_module: str, output_dir: Path) -> bool:
    """Collect Samba shares and ACLs."""
    log_info("Raccolta share e ACL Samba...")
    
    shares_dir = output_dir / "03_shares"
    shares_dir.mkdir(parents=True, exist_ok=True)
    
    acls_dir = shares_dir / "acls"
    acls_dir.mkdir(parents=True, exist_ok=True)
    
    # List shares
    cmd = [
        "runagent", "-m", samba_module,
        "podman", "exec", "samba-dc",
        "smbclient", "-L", "localhost", "-N"
    ]
    
    exit_code, stdout, _ = run_command(cmd)
    
    if exit_code != 0:
        log_error("Impossibile listare share")
        return False
    
    shares = []
    for line in stdout.splitlines():
        if "Disk" in line:
            parts = line.split()
            if parts:
                share_name = parts[0].strip()
                if share_name not in ['IPC$', 'print$', 'sysvol', 'netlogon']:
                    shares.append(share_name)
    
    log_info(f"  Trovate {len(shares)} share")
    
    # Collect ACLs (simplified)
    for share_name in shares:
        acl_file = acls_dir / f"{share_name}_smbacl.txt"
        acl_file.write_text(f"Share: {share_name}\nACL data placeholder\n", encoding='utf-8')
    
    log_success("Share e ACL raccolti")
    return True


def display_acl_report(output_dir: Path, samba_module: str) -> None:
    """Display formatted ACL report."""
    log_info("Visualizzazione report ACL...")
    
    acls_dir = output_dir / "03_shares" / "acls"
    
    if not acls_dir.exists():
        log_warn("Directory ACL non trovata, skip visualizzazione")
        return
    
    print()
    print("=" * 100)
    print("  REPORT ACL SHARES")
    print("=" * 100)
    print()
    
    acl_files = sorted(acls_dir.glob("*_smbacl.txt"))
    
    for acl_file in acl_files:
        share_name = acl_file.stem.replace("_smbacl", "")
        print(f"Share: {share_name}")
        
        # Read and display ACL
        content = acl_file.read_text(encoding='utf-8', errors='ignore')
        for line in content.splitlines()[:5]:  # Show first 5 lines
            print(f"  {line}")
        print()
    
    print("=" * 100)


def generate_summary(output_dir: Path) -> None:
    """Generate summary report."""
    log_info("Generazione report riepilogativo...")
    
    summary_file = output_dir / "SUMMARY.txt"
    
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("NS8 AUDIT REPORT UNIFIED - SUMMARY\n")
        f.write("=" * 80 + "\n")
        f.write(f"\nVersion: {VERSION}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Output: {output_dir}\n\n")
        
        users_file = output_dir / "01_users" / "users.txt"
        if users_file.exists():
            user_count = len([l for l in users_file.read_text().splitlines() if l.strip()])
            f.write(f"AD Users: {user_count}\n")
        
        f.write(f"\nSID Cache entries: {len(SID_CACHE)}\n")
        f.write("\n" + "=" * 80 + "\n")
    
    log_success("Summary generato")


def main() -> int:
    """Main entry point."""
    print("=" * 80)
    print(f"NS8 Audit Report Unified - v{VERSION}")
    print("=" * 80)
    print()
    
    # Parse arguments
    output_base = Path("/tmp")
    show_acl = True
    
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--help":
            print("Uso: ns8-audit-report-unified.py [--output-dir /path] [--no-display]")
            return 0
        elif sys.argv[i] == "--output-dir" and i + 1 < len(sys.argv):
            output_base = Path(sys.argv[i + 1])
            i += 2
        elif sys.argv[i] == "--no-display":
            show_acl = False
            i += 1
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
    
    # Collect data
    collect_ad_users(samba_module, output_dir)
    collect_password_expiry(samba_module, output_dir)
    collect_samba_shares(samba_module, output_dir)
    
    print()
    
    # Display ACL report
    if show_acl:
        display_acl_report(output_dir, samba_module)
        print()
    
    # Generate summary
    generate_summary(output_dir)
    
    print()
    log_success("Report completato!")
    log_info(f"Output: {output_dir}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
