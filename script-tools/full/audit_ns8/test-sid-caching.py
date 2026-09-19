#!/usr/bin/env python3
"""test-sid-caching.py - SID pre-caching test for NS8 debugging

SID → username conversion test with progressive timeout.
Identify checkpoints in SID conversions via wbinfo.

Prerequisite: Run ns8-audit-report-unified.sh first to generate ACL files.

Version: 1.0.0"""

import subprocess
import sys
import re
import time
from pathlib import Path
from typing import Dict, List, Tuple, Optional

VERSION = "1.0.0"


def run_command(cmd: List[str], timeout: int = 10) -> Tuple[int, str, str]:
    """Execute a shell command with timeout.
    
    Args:
        cmd: Command as list of strings
        timeout: Timeout in seconds
        
    Returns:
        Tuple of (exit_code, stdout, stderr)"""
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
        return 124, "", "Timeout expired"
    except FileNotFoundError:
        return 127, "", "Command not found"
    except Exception as e:
        return 1, "", str(e)


def find_samba_module() -> Optional[str]:
    """Find first Samba module in NS8.
    
    Returns:
        Module name (e.g., "samba1") or None if not found"""
    exit_code, stdout, _ = run_command(["runagent", "--list-modules"])
    if exit_code != 0:
        return None
    
    for line in stdout.splitlines():
        if re.match(r'^samba\d+$', line.strip()):
            return line.strip()
    
    return None


def find_latest_acl_dir() -> Optional[Path]:
    """Find latest ACL directory in /tmp/ns8-audit-*.
    
    Returns:
        Path to ACL directory or None if not found"""
    tmp_path = Path("/tmp")
    audit_dirs = sorted(tmp_path.glob("ns8-audit-*"), reverse=True)
    
    for audit_dir in audit_dirs:
        acl_dir = audit_dir / "03_shares" / "acls"
        if acl_dir.is_dir():
            return acl_dir
    
    return None


def extract_unique_sids(acl_dir: Path) -> List[str]:
    """Extract unique SIDs from ACL files.
    
    Args:
        acl_dir: Path to ACL directory
        
    Returns:
        List of unique SIDs"""
    sids = set()
    
    for acl_file in acl_dir.glob("*_acl.txt"):
        try:
            with open(acl_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if "trustee" in line and "S-1" in line:
                        # Extract SID with regex
                        match = re.search(r'(S-1-[\d-]+)', line)
                        if match:
                            sids.add(match.group(1))
        except IOError:
            continue
    
    return sorted(sids)


def is_system_sid(sid: str) -> bool:
    """Check if SID is a well-known system SID.
    
    Args:
        sid: SID string
        
    Returns:
        True if system SID, False otherwise"""
    system_sids = [
        "S-1-5-18",      # Local System
        "S-1-5-32-544",  # Administrators
        "S-1-5-2",       # Network
        "S-1-1-0"        # Everyone
    ]
    return sid in system_sids


def convert_sid_to_name(sid: str, samba_module: str, timeout: int = 5) -> Tuple[bool, str, float]:
    """Convert SID to name using wbinfo.
    
    Args:
        sid: SID to convert
        samba_module: Samba module name
        timeout: Timeout in seconds
        
    Returns:
        Tuple of (success, name, elapsed_time)"""
    start_time = time.time()
    
    cmd = [
        "runagent", "-m", samba_module,
        "podman", "exec", "samba-dc",
        "wbinfo", "--sid-to-name", sid
    ]
    
    exit_code, stdout, stderr = run_command(cmd, timeout)
    elapsed = time.time() - start_time
    
    if exit_code == 0:
        return True, stdout.strip(), elapsed
    else:
        return False, f"Exit {exit_code}: {stderr}", elapsed


def main() -> int:
    """Main test logic.
    
    Returns:
        Exit code"""
    print("=" * 50)
    print("TEST PRE-CACHING SID - DEBUG")
    print("=" * 50)
    print()
    
    # Find Samba module
    samba_module = find_samba_module()
    if not samba_module:
        print("[ERROR] Nessun modulo Samba trovato")
        return 1
    
    print(f"[OK] Modulo Samba: {samba_module}")
    print()
    
    # Find ACL directory
    acl_dir = find_latest_acl_dir()
    if not acl_dir:
        print("[ERROR] Directory ACL non trovata")
        print("Esegui prima ns8-audit-report-unified.sh per raccogliere ACL")
        return 1
    
    print(f"[OK] ACL directory: {acl_dir}")
    print()
    
    # Extract unique SIDs
    print("[INFO] Estrazione SID unici dai file ACL...")
    all_sids = extract_unique_sids(acl_dir)
    sid_count = len(all_sids)
    
    print(f"[OK] Trovati {sid_count} SID unici")
    print()
    
    if sid_count == 0:
        print("[ERROR] Nessun SID trovato nei file ACL")
        return 1
    
    # Show first 3 SIDs
    print("[DEBUG] Primi 3 SID estratti:")
    for sid in all_sids[:3]:
        print(f"  {sid}")
    print()
    
    # Test SID conversion
    print("=" * 50)
    print("TEST CONVERSIONE SID (uno alla volta)")
    print("=" * 50)
    print()
    
    sid_cache: Dict[str, str] = {}
    
    for current, sid in enumerate(all_sids, 1):
        print(f"[{current}/{sid_count}] Testing SID: {sid}")
        
        # Skip system SIDs
        if is_system_sid(sid):
            print("  → SKIP (system SID)")
            sid_cache[sid] = ""
            print()
            continue
        
        # Try with 5s timeout
        print("  → Calling wbinfo (timeout 5s)...")
        success, result, elapsed = convert_sid_to_name(sid, samba_module, timeout=5)
        
        if success:
            print(f"  → SUCCESS: {result} ({elapsed:.1f}s)")
            sid_cache[sid] = result
        else:
            print(f"  → FAILED: {result} ({elapsed:.1f}s)")
            
            # If timeout, retry with 10s
            if "Exit 124" in result:
                print("  → Retry with 10s timeout...")
                success, result, elapsed = convert_sid_to_name(sid, samba_module, timeout=10)
                
                if success:
                    print(f"  → SUCCESS (retry): {result} ({elapsed:.1f}s)")
                    sid_cache[sid] = result
                else:
                    print(f"  → FAILED (retry): {result} ({elapsed:.1f}s)")
                    sid_cache[sid] = "UNKNOWN"
            else:
                sid_cache[sid] = "UNKNOWN"
        
        print()
        
        # Progress every 5 SIDs
        if current % 5 == 0:
            print(f"--- Progress: {current}/{sid_count} SID processati ---")
            print()
    
    # Summary
    print("=" * 50)
    print("RIEPILOGO TEST")
    print("=" * 50)
    print()
    print(f"SID totali:        {sid_count}")
    print(f"Cache popolata:    {len(sid_cache)} entries")
    print()
    print("Contenuto cache:")
    for sid, name in sorted(sid_cache.items()):
        print(f"  {sid} → {name}")
    print()
    print("[OK] Test completato!")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
