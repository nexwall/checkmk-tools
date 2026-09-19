#!/usr/bin/env python3
"""checkmk_download_backup.py - CheckMK Backup Download Tool

Download CheckMK backups from DigitalOcean Spaces using rclone:
- Interactive UI with color output
- Multiple backup selection support (single, range, mixed)
- Support for job00-daily and job01-weekly paths
- Automatic rclone setup if not configured

Version: 1.0.0"""

import sys
import os
import subprocess
import shutil
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional

VERSION = "1.0.0"
RCLONE_REMOTE = os.getenv("RCLONE_REMOTE", "do:testmonbck")
DOWNLOAD_DIR_DEFAULT = "/var/backups/checkmk"

# ANSI Colors
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
CYAN = '\033[0;36m'
NC = '\033[0m'


def log(message: str) -> None:
    """Log message with timestamp."""
    import datetime
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"{BLUE}[{timestamp}]{NC} {message}")


def success(message: str) -> None:
    """Print success message."""
    print(f"{GREEN} {message}{NC}")


def warn(message: str) -> None:
    """Print warning message."""
    print(f"{YELLOW}  {message}{NC}")


def error(message: str) -> None:
    """Print error message and exit."""
    print(f"{RED} {message}{NC}", file=sys.stderr)
    sys.exit(1)


def title(message: str) -> None:
    """Print title with box."""
    print(f"\n{CYAN}╔═══════════════════════════════════════════════════════════════╗{NC}")
    print(f"{CYAN}║ {message}{NC}")
    print(f"{CYAN}╚═══════════════════════════════════════════════════════════════╝{NC}\n")


def confirm(prompt: str, default: str = "n") -> bool:
    """Ask user for confirmation."""
    if default == "y":
        reply = input(f"{prompt} [Y/n] ").strip().lower()
        reply = reply if reply else "y"
    else:
        reply = input(f"{prompt} [y/N] ").strip().lower()
        reply = reply if reply else "n"
    
    return reply in ["y", "yes"]


def check_root() -> None:
    """Check if running as root."""
    if os.geteuid() != 0:
        error("Questo script deve essere eseguito come root")


def run_command(cmd: List[str], check: bool = True, capture_output: bool = False,
                shell: bool = False, timeout: int = 300) -> subprocess.CompletedProcess:
    """Execute a shell command."""
    try:
        if shell:
            return subprocess.run(
                cmd if isinstance(cmd, str) else " ".join(cmd),
                shell=True,
                check=check,
                capture_output=capture_output,
                text=True,
                timeout=timeout
            )
        else:
            return subprocess.run(
                cmd,
                check=check,
                capture_output=capture_output,
                text=True,
                timeout=timeout
            )
    except subprocess.CalledProcessError:
        if check:
            raise
    except subprocess.TimeoutExpired:
        error(f"Command timeout: {' '.join(cmd) if isinstance(cmd, list) else cmd}")


def install_rclone() -> None:
    """Install rclone if not present."""
    title(" Verifica rclone")
    
    if shutil.which("rclone"):
        success("rclone già installato")
        return
    
    warn("rclone non installato")
    if confirm("Vuoi installarlo ora?", "y"):
        log("Installo rclone...")
        try:
            run_command("curl -fsSL https://rclone.org/install.sh | bash", shell=True)
            success("rclone installato")
        except Exception as e:
            error(f"Installazione rclone fallita: {e}")
    else:
        error("rclone necessario per scaricare i backup")


def find_or_create_rclone_config() -> str:
    """Find existing rclone config or create new one."""
    title("  Configurazione rclone")
    
    possible_configs = [
        "/root/.config/rclone/rclone.conf",
        "/opt/omd/sites/monitoring/.config/rclone/rclone.conf"
    ]
    
    # Try to find existing config
    for config_path in possible_configs:
        if Path(config_path).exists():
            success(f"Configurazione rclone trovata: {config_path}")
            
            # Test connection
            log("Test connessione rclone...")
            result = run_command(
                ["rclone", "lsd", RCLONE_REMOTE, f"--config={config_path}", "--s3-no-check-bucket"],
                check=False,
                capture_output=True
            )
            if result.returncode == 0:
                success("Configurazione rclone funzionante")
                return config_path
            else:
                warn("Configurazione rclone non funzionante")
                if confirm("Vuoi riconfigurare rclone?", "y"):
                    return create_rclone_config(config_path)
                else:
                    error(f"Configurazione rclone non funzionante. Correggi manualmente: nano {config_path}")
    
    # No config found, create new
    warn("Configurazione rclone non trovata")
    if confirm("Vuoi configurare rclone ora per DigitalOcean Spaces?", "y"):
        config_path = "/root/.config/rclone/rclone.conf"
        Path(config_path).parent.mkdir(parents=True, exist_ok=True)
        return create_rclone_config(config_path)
    else:
        error("Configurazione rclone necessaria. Configura manualmente: rclone config")


def create_rclone_config(config_path: str) -> str:
    """Create rclone configuration interactively."""
    print("Inserisci le credenziali DigitalOcean Spaces:")
    print("")
    
    access_key = input("Access Key ID: ").strip()
    import getpass
    secret_key = getpass.getpass("Secret Access Key: ").strip()
    region = input("Region [ams3]: ").strip() or "ams3"
    endpoint = input(f"Endpoint [{region}.digitaloceanspaces.com]: ").strip() or f"{region}.digitaloceanspaces.com"
    
    # Extract remote name from RCLONE_REMOTE (e.g., do:testmonbck -> do)
    remote_name = RCLONE_REMOTE.split(":")[0]
    
    log(f"Creo configurazione rclone remote '{remote_name}'...")
    
    # Delete old config if exists
    run_command(["rclone", "config", "delete", remote_name], check=False, capture_output=True)
    
    # Create new config
    try:
        run_command([
            "rclone", "config", "create", remote_name, "s3",
            "provider=DigitalOcean",
            "env_auth=false",
            f"access_key_id={access_key}",
            f"secret_access_key={secret_key}",
            f"region={region}",
            f"endpoint={endpoint}",
            "acl=private"
        ])
        success("Configurazione rclone creata")
        return config_path
    except Exception as e:
        error(f"Configurazione rclone fallita: {e}")


def select_job_paths() -> List[str]:
    """Let user select which job paths to scan."""
    title("  Selezione Job")
    
    print("Quale/i job vuoi visualizzare?")
    print("")
    print("  1)  job00-daily  - Backup compressi giornalieri (1.2M, retention 90)")
    print("  2)  job01-weekly - Backup completi settimanali (362M, retention 5)")
    print("  3)  Entrambi     - Mostra tutti i backup disponibili")
    print("")
    
    choice = input("Selezione [1-3, default: 3]: ").strip() or "3"
    
    if choice == "1":
        log("Visualizzo solo job00-daily")
        return ["checkmk-backups/job00-daily"]
    elif choice == "2":
        log("Visualizzo solo job01-weekly")
        return ["checkmk-backups/job01-weekly"]
    elif choice == "3":
        log("Visualizzo entrambi i job")
        return ["checkmk-backups/job00-daily", "checkmk-backups/job01-weekly"]
    else:
        error("Selezione non valida")


def list_backups(rclone_config: str, paths: List[str]) -> Dict[int, Dict[str, str]]:
    """List available backups from cloud.
    
    Returns:
        Dictionary mapping index to backup info"""
    title(" Backup Disponibili")
    
    item_map = {}
    index = 1
    
    for rclone_path in paths:
        job_label = ""
        if "job00-daily" in rclone_path:
            job_label = "[job00-daily]"
        elif "job01-weekly" in rclone_path:
            job_label = "[job01-weekly]"
        
        log(f"Scansiono {RCLONE_REMOTE}/{rclone_path}...")
        
        # Test path accessibility
        result = run_command(
            ["rclone", "lsd", f"{RCLONE_REMOTE}/{rclone_path}",
             f"--config={rclone_config}", "--s3-no-check-bucket"],
            check=False,
            capture_output=True
        )
        
        if result.returncode != 0:
            warn(f"Path non accessibile: {rclone_path} (potrebbe non esistere)")
            continue
        
        # List directories (native CheckMK backups)
        dirs = []
        for line in result.stdout.split('\n'):
            if line.strip():
                parts = line.split()
                if len(parts) >= 5:
                    dirs.append(parts[-1])
        dirs.sort(reverse=True)
        
        # Add directories to map
        for dirname in dirs:
            item_map[index] = {
                "name": dirname,
                "type": "dir",
                "path": rclone_path,
                "label": job_label
            }
            print(f"{index:2d})  {dirname:<50} {job_label}")
            index += 1
        
        # List files (custom backups)
        result = run_command(
            ["rclone", "lsf", f"{RCLONE_REMOTE}/{rclone_path}",
             f"--config={rclone_config}", "--s3-no-check-bucket",
             "--files-only", "--max-depth", "1"],
            check=False,
            capture_output=True
        )
        
        if result.returncode == 0:
            files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
            files.sort(reverse=True)
            
            for filename in files:
                item_map[index] = {
                    "name": filename,
                    "type": "file",
                    "path": rclone_path,
                    "label": job_label
                }
                print(f"{index:2d})  {filename:<40} {job_label}")
                index += 1
    
    if not item_map:
        error("Nessun backup trovato nei path selezionati")
    
    success(f"Trovati {len(item_map)} backup")
    return item_map


def parse_selection(selection: str, max_index: int) -> List[int]:
    """Parse user selection (supports single, range, mixed).
    
    Args:
        selection: User input (e.g., "1.3-5.7")
        max_index: Maximum valid index
        
    Returns:
        List of selected indices"""
    selected = []
    
    for part in selection.split(','):
        part = part.strip()
        
        if '-' in part:
            # Range: 3-7
            match = re.match(r'^(\d+)-(\d+)$', part)
            if match:
                start, end = int(match.group(1)), int(match.group(2))
                selected.extend(range(start, end + 1))
            else:
                error(f"Formato non valido: '{part}'")
        elif part.isdigit():
            # Single number
            selected.append(int(part))
        else:
            error(f"Formato non valido: '{part}'")
    
    # Validate all numbers
    for num in selected:
        if num < 1 or num > max_index:
            error(f"Numero fuori range: {num} (validi: 1-{max_index})")
    
    # Remove duplicates and sort
    return sorted(set(selected))


def download_backups(rclone_config: str, selected_indices: List[int],
                     item_map: Dict[int, Dict[str, str]], download_dir: str) -> Tuple[List[str], List[str]]:
    """Download selected backups.
    
    Returns:
        Tuple of (downloaded_items, failed_items)"""
    title("  Download")
    
    # Create download directory
    Path(download_dir).mkdir(parents=True, exist_ok=True)
    
    downloaded = []
    failed = []
    
    for i, num in enumerate(selected_indices, start=1):
        item = item_map[num]
        name = item["name"]
        item_type = item["type"]
        path = item["path"]
        
        print("")
        log(f"[{i}/{len(selected_indices)}] Processing: {name} from {path}")
        
        if item_type == "dir":
            # Download directory
            log(f"  Scarico directory {name}/...")
            result = run_command(
                ["rclone", "copy",
                 f"{RCLONE_REMOTE}/{path}/{name}",
                 f"{download_dir}/{name}",
                 f"--config={rclone_config}",
                 "--s3-no-check-bucket",
                 "--progress"],
                check=False
            )
            
            if result.returncode == 0 and Path(f"{download_dir}/{name}").exists():
                # Get directory size
                try:
                    result = run_command(["du", "-sh", f"{download_dir}/{name}"], capture_output=True)
                    size = result.stdout.split()[0]
                except:
                    size = "N/A"
                success(f"   Directory: {name}/ ({size})")
                downloaded.append(f"{name}/ ({size})")
            else:
                warn(f"    Download fallito: {name}/")
                failed.append(f"{name}/ (download failed)")
        
        else:
            # Download files
            log(f"  Scarico file {name}...")
            result = run_command(
                ["rclone", "copy",
                 f"{RCLONE_REMOTE}/{path}",
                 download_dir,
                 f"--config={rclone_config}",
                 "--s3-no-check-bucket",
                 "--include", name,
                 "--progress"],
                check=False
            )
            
            downloaded_file = Path(download_dir) / name
            if result.returncode == 0 and downloaded_file.exists():
                # Get file size
                try:
                    result = run_command(["du", "-h", str(downloaded_file)], capture_output=True)
                    size = result.stdout.split()[0]
                except:
                    size = "N/A"
                success(f"   File: {name} ({size})")
                downloaded.append(f"{name} ({size})")
            else:
                warn(f"    Download fallito: {name}")
                failed.append(f"{name} (download failed)")
    
    return downloaded, failed


def print_summary(downloaded: List[str], failed: List[str],
                  total: int, download_dir: str) -> int:
    """Print download summary."""
    print("")
    title(" Riepilogo Download")
    
    if downloaded:
        success(f"Download completati: {len(downloaded)}/{total}")
        print("")
        for item in downloaded:
            print(f"   {item}")
    
    if failed:
        print("")
        error(f"Download falliti: {len(failed)}/{total}")
        print("")
        for item in failed:
            print(f"   {item}")
    
    print("")
    if not failed:
        success(" Operazione completata con successo!")
        print("")
        print(f"Tutti i backup scaricati in: {download_dir}/")
        return 0
    else:
        warn("  Operazione completata con errori")
        print("")
        print(f"Percorso download: {download_dir}/")
        return 1


def main() -> int:
    """Main entry point."""
    check_root()
    
    # Banner
    os.system('clear')
    title(" DOWNLOAD BACKUP DA DIGITALOCEAN SPACES")
    
    # Install/verify rclone
    install_rclone()
    
    # Get download directory
    title(" Destinazione Download")
    download_dir = input(f"Directory download [{DOWNLOAD_DIR_DEFAULT}]: ").strip() or DOWNLOAD_DIR_DEFAULT
    Path(download_dir).mkdir(parents=True, exist_ok=True)
    log(f"Directory download: {download_dir}")
    
    # Find/create rclone config
    rclone_config = find_or_create_rclone_config()
    
    # Select job paths
    paths = select_job_paths()
    
    # List backups
    item_map = list_backups(rclone_config, paths)
    
    # User selection
    print("")
    print("Esempi di selezione:")
    print("  - Singolo:  5")
    print("  - Multipli: 1,3,5")
    print("  - Range:    1-5")
    print("  - Misto:    1,3-7,10")
    print("")
    
    selection = input(f"Seleziona numero/i (1-{len(item_map)}) o 'q' per uscire: ").strip()
    
    if selection == "q":
        print("Operazione annullata")
        return 0
    
    selected_indices = parse_selection(selection, len(item_map))
    
    # Show selected items
    print("")
    success(f"Selezionati {len(selected_indices)} backup:")
    for num in selected_indices:
        item = item_map[num]
        icon = "" if item["type"] == "dir" else ""
        name = item["name"] + ("/" if item["type"] == "dir" else "")
        print(f"  [{num}] {icon} {name}")
    
    # Confirm download
    title("  Conferma Download")
    print(f"Stai per scaricare {len(selected_indices)} backup:")
    print("")
    for num in selected_indices:
        item = item_map[num]
        icon = "" if item["type"] == "dir" else ""
        name = item["name"] + ("/" if item["type"] == "dir" else "")
        job_name = "job00-daily" if "job00" in item["path"] else "job01-weekly"
        print(f"  {icon} [{job_name}] {name} → {download_dir}/{item['name']}")
    print("")
    print(f"Da: {RCLONE_REMOTE}/...")
    print(f"A:  {download_dir}/")
    print("")
    
    if not confirm("Vuoi procedere?", "y"):
        print("Operazione annullata")
        return 0
    
    # Download
    downloaded, failed = download_backups(rclone_config, selected_indices, item_map, download_dir)
    
    # Summary
    return print_summary(downloaded, failed, len(selected_indices), download_dir)


if __name__ == "__main__":
    sys.exit(main())
