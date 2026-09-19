#!/usr/bin/env python3
"""network_scan_to_folder.py - Network scan and CheckMK folder creation

Phase 1: Ping sweep subnet → collects active IPs
Step 2: Reverse DNS for each IP → collect hostnames
Step 3: Create WATO folder with all hosts found (ping-only, hardcoded IP)

Usage:
  python3 network_scan_to_folder.py --subnet 192.168.32.0/23 --dry-run
  python3 network_scan_to_folder.py --subnet 192.168.32.0/23 --folder scan
  python3 network_scan_to_folder.py --subnet 192.168.32.0/23 --subnet 10.0.0.0/24 --folder scan

Version: 1.0.0"""

import argparse
import ipaddress
import subprocess
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

VERSION = "1.1.5"

WATO_BASE = "/omd/sites/monitoring/etc/check_mk/conf.d/wato"


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

def ping(ip: str) -> bool:
    r = subprocess.run(["ping", "-c1", "-W1", ip], capture_output=True)
    return r.returncode == 0


def reverse_dns(ip: str) -> Optional[str]:
    """Reverse DNS via resolvectl (use systemd-resolved, works with AD).
    
    resolvectl output format: "IP: HOSTNAME.domain -- link: iface""""
    try:
        r = subprocess.run(
            ["resolvectl", "query", ip],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                # Formato: "10.x.x.x: HOSTNAME.domain.  -- link: iface"
                m = re.match(r'\s*[\d\.]+:\s+(\S+)', line)
                if m:
                    name = m.group(1).rstrip('.')
                    return name.split('.')[0].upper()
    except Exception:
        pass
    return None


def scan_subnet(subnet: str, max_workers: int = 50) -> list:
    """Parallel ping sweep. Returns active IP list."""
    network = ipaddress.ip_network(subnet, strict=False)
    host_list = list(network.hosts())
    print(f"  Scansione {subnet}: {len(host_list)} IP...")

    live = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(ping, str(ip)): str(ip) for ip in host_list}
        done = 0
        for future in as_completed(futures):
            done += 1
            ip = futures[future]
            if future.result():
                live.append(ip)
            if done % 100 == 0:
                print(f"    {done}/{len(host_list)} testati, {len(live)} attivi...")

    print(f"  → {len(live)} host attivi in {subnet}")
    return live


def resolve_all(live_ips: list) -> list:
    """For each active IP resolves hostname, returns list of dicts."""
    results = []
    seen_names = {}  # name → count, per deduplicazione

    for ip in sorted(live_ips, key=lambda x: ipaddress.ip_address(x)):
        hostname = reverse_dns(ip)

        if hostname:
            # Deduplication: if name already seen, add suffix
            if hostname in seen_names:
                seen_names[hostname] += 1
                cmk_name = f"{hostname}-{seen_names[hostname]}"
            else:
                seen_names[hostname] = 1
                cmk_name = hostname
            src = "DNS"
        else:
            # No DNS → use IP as name (e.g. 192_168_32_105)
            cmk_name = "IP-" + ip.replace(".", "_")
            src = "IP "

        results.append({"ip": ip, "hostname": hostname, "name": cmk_name, "src": src})
        print(f"  {ip:<20} {src}  → {cmk_name}")

    return results


# ---------------------------------------------------------------------------
# CheckMK WATO helpers
# ---------------------------------------------------------------------------

def sanitize(name: str) -> str:
    """Valid characters for CheckMK hostname."""
    return re.sub(r'[^a-zA-Z0-9._-]', '-', name)


def get_site_name() -> str:
    """Get the OMD site name from the WATO_BASE."""
    m = re.match(r'/omd/sites/([^/]+)/', WATO_BASE)
    return m.group(1) if m else "monitoring"


def create_wato_folder(folder_name: str, hosts: list, subnets: list, dry_run: bool = False):
    """Create directory + .wato + hosts.mk in CheckMK 2.x format."""
    folder_path = os.path.join(WATO_BASE, folder_name)
    wato_file  = os.path.join(folder_path, ".wato")
    hosts_file = os.path.join(folder_path, "hosts.mk")

    # Check if folder already exists
    if os.path.exists(hosts_file) and not dry_run:
        backup = f"{hosts_file}.backup_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
        try:
            os.rename(hosts_file, backup)
            print(f"  Backup hosts.mk esistente → {backup}")
        except Exception:
            pass
        # Cleans old backups: keep only the last 3
        try:
            import glob
            old_backups = sorted(glob.glob(f"{hosts_file}.backup_*"))
            for old in old_backups[:-3]:
                os.remove(old)
                print(f"  Rimosso backup vecchio: {os.path.basename(old)}")
        except Exception:
            pass

    wato_content = (
        f"{{'title': u'{folder_name}', 'attributes': {{}}, "
        f"'num_hosts': {len(hosts)}, 'lock': False}}\n"
    )

    site = get_site_name()
    now_ts = datetime.now().timestamp()

    # Costruisce righe hosts.mk formato CMK 2.x
    all_hosts_lines = []
    host_tags_lines = []
    host_labels_lines = []
    host_attrs_lines  = []

    for h in hosts:
        name = sanitize(h["name"])
        ip   = h["ip"]

        all_hosts_lines.append(f'"{name}"')

        tags = {
            "site": site,
            "address_family": "ip-v4-only",
            "ip-v4": "ip-v4",
            "agent": "no-agent",
            "piggyback": "auto-piggyback",
            "snmp_ds": "no-snmp",
            "criticality": "prod",
            "networking": "lan",
            "ping": "ping",
        }
        host_tags_lines.append(f'"{name}": {repr(tags)}')
        host_labels_lines.append(f'"{name}": {{}}')
        host_attrs_lines.append(
            f'"{name}": {{"ipaddress": "{ip}", '
            f'"meta_data": {{"created_at": {now_ts:.1f}, '
            f'"created_by": "network_scan", "updated_at": {now_ts:.1f}}}}}'
        )

    subnet_comment = ", ".join(subnets)
    hosts_mk = (
        f"# Generato da network_scan_to_folder.py v{VERSION}\n"
        f"# Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"# Subnet scansionate: {subnet_comment}\n"
        f"# Host totali: {len(hosts)} "
        f"({sum(1 for h in hosts if h['src'] == 'DNS')} con DNS, "
        f"{sum(1 for h in hosts if h['src'] == 'IP ')} IP-only)\n"
        f"# Created by HostStorage\n\n"
        f"all_hosts += [{', '.join(all_hosts_lines)}]\n\n"
        f"host_tags.update({{{', '.join(host_tags_lines)}}})\n\n"
        f"host_labels.update({{{', '.join(host_labels_lines)}}})\n\n"
        f"# Host attributes (needed for WATO)\n"
        f"host_attributes.update({{{', '.join(host_attrs_lines)}}})\n\n"
        f"folder_attributes.update({{}})\n"
    )

    if dry_run:
        print(f"\n[DRY RUN] Folder: {folder_path}")
        print(f"[DRY RUN] {len(all_hosts_lines)} host")
        print(f"\n--- hosts.mk preview ---")
        for line in hosts_mk.splitlines()[:30]:
            print(f"  {line}")
        if hosts_mk.count('\n') > 30:
            print(f"  ... ({hosts_mk.count(chr(10)) - 30} righe omesse)")
        return

    os.makedirs(folder_path, exist_ok=True)
    with open(wato_file, "w") as f:
        f.write(wato_content)
    with open(hosts_file, "w") as f:
        f.write(hosts_mk)

    # Fix ownership: CheckMK must run as OMD user, not root
    site = get_site_name()
    try:
        import pwd
        pw = pwd.getpwnam(site)
        uid, gid = pw.pw_uid, pw.pw_gid
        for dirpath, dirnames, filenames in os.walk(WATO_BASE):
            os.chown(dirpath, uid, gid)
            for fname in filenames:
                os.chown(os.path.join(dirpath, fname), uid, gid)
        print(f"  Permessi: chown -R {site}:{site} {WATO_BASE}")
    except Exception as e:
        print(f"  Permessi: skip ({e})")

    print(f"  Folder:   {folder_path}")
    print(f"  .wato:    OK")
    print(f"  hosts.mk: {len(all_hosts_lines)} host scritti")


def apply_checkmk(dry_run: bool = False):
    if dry_run:
        print("[DRY RUN] Salterebbe: cmk -R")
        return
    print("\nApplicazione CheckMK (cmk -R)...")
    # Prova direttamente (siamo già nel contesto OMD)
    try:
        r = subprocess.run(["cmk", "-R"], capture_output=True, text=True)
        if r.returncode == 0:
            print("cmk -R: OK")
            return
    except FileNotFoundError:
        pass
    # Fallback: su - SITE -c "cmk -R"
    site = get_site_name()
    try:
        r = subprocess.run(["su", "-", site, "-c", "cmk -R"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            print(f"cmk -R: OK (via su - {site})")
        else:
            print(f"cmk -R WARNING:\n{r.stderr[:500]}")
    except Exception as e:
        print(f"cmk -R: impossibile eseguire ({e})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _prompt_subnet() -> list:
    """Queries subnets interactively until the line is empty."""
    print("Inserisci le subnet da scansionare (una per riga, INVIO vuoto per terminare):")
    subnets = []
    while True:
        val = input(f"  subnet{len(subnets)+1}: ").strip()
        if not val:
            if not subnets:
                print("  Devi inserire almeno una subnet.")
                continue
            break
        # Validazione minimale formato CIDR
        try:
            import ipaddress
            ipaddress.ip_network(val, strict=False)
            subnets.append(val)
        except ValueError:
            print(f"  '{val}' non è un CIDR valido (es: 192.168.1.0/24). Riprova.")
    return subnets


def _prompt_folder() -> str:
    """Asks for the WATO folder name interactively."""
    while True:
        val = input("Nome folder WATO [scansione]: ").strip()
        if not val:
            return "scansione"
        # Only safe characters for directory name
        if re.match(r'^[\w\-]+$', val):
            return val
        print("  Usa solo lettere, numeri, underscore e trattino.")


def main():
    parser = argparse.ArgumentParser(
        description=f"Network scan → CheckMK folder v{VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Interactive mode (requires subnet and folder)
  python3 network_scan_to_folder.py

  # Preview without writing
  python3 network_scan_to_folder.py --subnet 192.168.32.0/23 --dry-run

  # Create "scan" folder (default)
  python3 network_scan_to_folder.py --subnet 192.168.32.0/23

  # Multiple subnets, custom folder name
  python3 network_scan_to_folder.py --subnet 192.168.32.0/24 --subnet 192.168.33.0/24 --folder scan_lab""")
    parser.add_argument("--subnet", action="append", default=None,
                        metavar="CIDR",
                        help="Subnet da scansionare (ripetibile: --subnet A --subnet B)")
    parser.add_argument("--folder", default=None,
                        help="Nome folder WATO (default: chiede interattivamente)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview senza scrivere nulla")
    parser.add_argument("--workers", type=int, default=50,
                        help="Thread paralleli per ping (default: 50)")
    args = parser.parse_args()

    print(f"Network Scan → CheckMK Folder v{VERSION}")
    print("=" * 60)

    # Interactive input if not passed by CLI
    if not args.subnet:
        args.subnet = _prompt_subnet()
    if args.folder is None:
        args.folder = _prompt_folder()

    print(f"\nSubnet:  {', '.join(args.subnet)}")
    print(f"Folder:  {args.folder}")
    print(f"Dry-run: {args.dry_run}")
    print("=" * 60)

    # Phase 1: Ping sweep across all subnets
    print("\n[Fase 1] Ping sweep...")
    all_live = []
    for subnet in args.subnet:
        live = scan_subnet(subnet, args.workers)
        all_live.extend(live)

    # Deduplicazione nel caso subnet si sovrappongano
    all_live = list(set(all_live))
    print(f"\nTotale IP attivi: {len(all_live)}")

    if not all_live:
        print("Nessun host trovato. Uscita.")
        sys.exit(0)

    # Fase 2: Risoluzione DNS inversa
    print("\n[Fase 2] Risoluzione DNS inversa...")
    hosts = resolve_all(all_live)

    named   = sum(1 for h in hosts if h["src"] == "DNS")
    ip_only = len(hosts) - named
    print(f"\nRiepilogo: {len(hosts)} host | {named} con nome DNS | {ip_only} IP-only")

    # Fase 3: Crea folder WATO
    print(f"\n[Fase 3] Creazione folder WATO '{args.folder}'...")
    create_wato_folder(args.folder, hosts, args.subnet, args.dry_run)

    # Applica
    apply_checkmk(args.dry_run)

    # Report finale
    if not args.dry_run:
        print("\n=== REPORT FINALE ===")
        print(f"{'NOME CMK':<32} {'IP':<20} {'DNS originale'}")
        print("-" * 70)
        for h in sorted(hosts, key=lambda x: x["name"]):
            dns_orig = h["hostname"] or "-"
            print(f"{sanitize(h['name']):<32} {h['ip']:<20} {dns_orig}")
        print("-" * 70)
        print(f"Totale: {len(hosts)} host nella folder '{args.folder}'")


if __name__ == "__main__":
    main()
