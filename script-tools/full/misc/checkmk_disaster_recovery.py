#!/usr/bin/env python3
"""checkmk_disaster_recovery.py - CheckMK Disaster Recovery Tool

Complete disaster recovery solution for CheckMK:
1. Lists available backups on cloud (job00-daily or job01-weekly)
2. Downloads selected backup
3. Automatic restore (with decompression if needed)
4. Services verification

Version: 1.0.0"""

import sys
import os
import subprocess
import shutil
import re
from pathlib import Path
from typing import Dict, Tuple, Optional, List

VERSION = "1.0.0"
RCLONE_REMOTE = os.getenv("RCLONE_REMOTE", "do:testmonbck")
DOWNLOAD_DIR = "/var/backups/checkmk/disaster-recovery"

# ANSI Colors
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
CYAN = '\033[0;36m'
NC = '\033[0m'  # No Color


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
    """Ask user for confirmation.
    
    Args:
        prompt: Confirmation prompt
        default: Default answer (y/n)
        
    Returns:
        True if confirmed, False otherwise"""
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
    """Execute a shell command.
    
    Args:
        cmd: Command as list of strings (or string if shell=True)
        check: Raise exception if command fails
        capture_output: Capture stdout/stderr
        shell: Run command in shell
        timeout: Command timeout in seconds
        
    Returns:
        CompletedProcess object"""
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
    except subprocess.CalledProcessError as e:
        if check:
            raise
        return e
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
        error("rclone necessario per disaster recovery")


def find_rclone_config() -> str:
    """Find rclone configuration file.
    
    Returns:
        Path to rclone.conf"""
    title("  Configurazione rclone")
    
    possible_configs = [
        "/root/.config/rclone/rclone.conf",
        "/opt/omd/sites/monitoring/.config/rclone/rclone.conf"
    ]
    
    for config_path in possible_configs:
        if Path(config_path).exists():
            success(f"Configurazione rclone: {config_path}")
            
            # Test connection
            log("Test connessione rclone...")
            result = run_command(
                ["rclone", "lsd", RCLONE_REMOTE, f"--config={config_path}", "--s3-no-check-bucket"],
                check=False,
                capture_output=True
            )
            if result.returncode == 0:
                success("Connessione rclone OK")
                return config_path
    
    error("Configurazione rclone non trovata. Configura prima rclone: rclone config")


def select_job_type() -> Tuple[str, bool]:
    """Let user select backup job type.
    
    Returns:
        Tuple of (rclone_path, is_compressed)"""
    title("  Selezione Job")
    
    print("Quale tipo di backup vuoi ripristinare?")
    print("")
    print("  1)  job00-daily  - Backup compressi giornalieri (1.2M, retention 90)")
    print("  2)  job01-weekly - Backup completi settimanali (362M, retention 5)")
    print("")
    
    choice = input("Selezione [1-2]: ").strip()
    
    if choice == "1":
        log("Selezionato job00-daily (backup compressi)")
        return ("checkmk-backups/job00-daily", True)
    elif choice == "2":
        log("Selezionato job01-weekly (backup completi)")
        return ("checkmk-backups/job01-weekly", False)
    else:
        error("Selezione non valida")


def list_available_backups(rclone_config: str, rclone_path: str) -> Dict[int, str]:
    """List available backups from cloud.
    
    Args:
        rclone_config: Path to rclone config
        rclone_path: Path in rclone remote
        
    Returns:
        Dictionary mapping index to backup name"""
    title(" Backup Disponibili")
    
    log(f"Recupero lista da {RCLONE_REMOTE}/{rclone_path}...")
    
    try:
        result = run_command(
            ["rclone", "lsd", f"{RCLONE_REMOTE}/{rclone_path}", 
             f"--config={rclone_config}", "--s3-no-check-bucket"],
            capture_output=True
        )
    except Exception as e:
        error(f"Errore recupero lista backup: {e}")
    
    # Parse output: extract directory names
    lines = result.stdout.strip().split('\n')
    backup_dirs = []
    for line in lines:
        if line.strip():
            # Format: directory_name at end of line
            parts = line.split()
            if len(parts) >= 5:
                backup_dirs.append(parts[-1])
    
    if not backup_dirs:
        error(f"Nessun backup trovato in {RCLONE_REMOTE}/{rclone_path}")
    
    # Sort by name (reverse, most recent first)
    backup_dirs.sort(reverse=True)
    
    print("")
    print("Backup disponibili (ordinati per data, più recenti prima):")
    print("")
    
    backup_map = {}
    for i, dirname in enumerate(backup_dirs, start=1):
        backup_map[i] = dirname
        
        # Extract timestamp if present
        timestamp = ""
        match = re.search(r'(\d{4}-\d{2}-\d{2}-\d{2}h\d{2})', dirname)
        if match:
            timestamp = f" [{match.group(1)}]"
        
        print(f"{i:2d})  {dirname:<60}{timestamp}")
    
    return backup_map


def select_backup(backup_map: Dict[int, str]) -> str:
    """Let user select a backup from the map.
    
    Args:
        backup_map: Dictionary of backups
        
    Returns:
        Selected backup name"""
    print("")
    max_index = max(backup_map.keys())
    selection = input(f"Seleziona backup da ripristinare [1-{max_index}]: ").strip()
    
    try:
        index = int(selection)
        if index not in backup_map:
            raise ValueError
        selected = backup_map[index]
        success(f"Selezionato: {selected}")
        return selected
    except (ValueError, KeyError):
        error("Selezione non valida")


def extract_site_name(backup_name: str) -> str:
    """Extract site name from backup directory name.
    
    Args:
        backup_name: Backup directory name
        
    Returns:
        Site name"""
    # Format: Check_MK-monitor-monitoring-job00-complete-2026-01-27-16h30
    # Site name: monitoring
    match = re.search(r'Check_MK-[^-]+-([^-]+)-', backup_name)
    if match:
        site_name = match.group(1)
        log(f"Site name rilevato: {site_name}")
        return site_name
    else:
        error(f"Impossibile estrarre site name da: {backup_name}")


def confirm_disaster_recovery(selected_backup: str, rclone_path: str, 
                               is_compressed: bool, site_name: str) -> None:
    """Ask user to confirm disaster recovery operation.
    
    Args:
        selected_backup: Selected backup name
        rclone_path: Rclone path
        is_compressed: Whether backup is compressed
        site_name: Site name"""
    title("  CONFERMA DISASTER RECOVERY")
    
    backup_type = "Backup compresso (job00)" if is_compressed else "Backup completo (job01)"
    
    print("")
    print("ATTENZIONE! Stai per eseguire:")
    print("")
    print(f"   Download:  {selected_backup}")
    print(f"   Da:        {RCLONE_REMOTE}/{rclone_path}/")
    print(f"   Tipo:      {backup_type}")
    print(f"   Site:      {site_name}")
    print("    Azione:   RIMOZIONE e RESTORE completo del site")
    print("")
    warn(f"Il site '{site_name}' verrà COMPLETAMENTE RIMOSSO e RIPRISTINATO!")
    print("")
    
    if not confirm("Confermi disaster recovery?", "n"):
        error("Operazione annullata dall'utente")


def download_backup(rclone_config: str, rclone_path: str, 
                    selected_backup: str) -> Path:
    """Download backup from cloud.
    
    Args:
        rclone_config: Rclone config path
        rclone_path: Rclone remote path
        selected_backup: Selected backup name
        
    Returns:
        Path to downloaded backup tar.gz file"""
    title(" Preparazione Directory Download")
    
    download_path = Path(DOWNLOAD_DIR)
    download_path.mkdir(parents=True, exist_ok=True)
    log(f"Directory download: {DOWNLOAD_DIR}")
    
    # Clean previous downloads
    backup_dir = download_path / selected_backup
    if backup_dir.exists():
        log("Rimuovo download precedente...")
        shutil.rmtree(backup_dir)
    
    title(" Download Backup")
    
    log(f"Scarico {selected_backup}...")
    log("Questo potrebbe richiedere alcuni minuti...")
    
    try:
        run_command([
            "rclone", "copy",
            f"{RCLONE_REMOTE}/{rclone_path}/{selected_backup}",
            str(backup_dir),
            f"--config={rclone_config}",
            "--s3-no-check-bucket",
            "--progress"
        ])
    except Exception as e:
        error(f"Download fallito: {e}")
    
    if not backup_dir.exists():
        error("Directory backup non trovata dopo download")
    
    return backup_dir


def verify_downloaded_backup(backup_dir: Path, site_name: str) -> Path:
    """Verify downloaded backup has required tar.gz file.
    
    Args:
        backup_dir: Downloaded backup directory
        site_name: Site name
        
    Returns:
        Path to tar.gz file"""
    tarfile = backup_dir / f"site-{site_name}.tar.gz"
    if not tarfile.exists():
        error(f"File backup non trovato: {tarfile}")
    
    # Get file size
    size = tarfile.stat().st_size
    size_mb = size / (1024 * 1024)
    success(f"Download completato ({size_mb:.1f} MB)")
    
    return tarfile


def remove_existing_site(site_name: str) -> None:
    """Check if site exists and remove it if user confirms.
    
    Args:
        site_name: Site name to check/remove"""
    title(" Verifica Site Esistente")
    
    # Check if site exists
    result = run_command(["omd", "sites"], capture_output=True, check=False)
    site_exists = site_name in result.stdout
    
    if site_exists:
        warn(f"Site '{site_name}' già esistente!")
        print("")
        print("Informazioni site corrente:")
        run_command(["omd", "sites"], check=False)
        print("")
        run_command(["omd", "status", site_name], check=False)
        print("")
        warn("  Per procedere con il restore, il site deve essere rimosso!")
        print("")
        
        if not confirm(f"Vuoi RIMUOVERE il site esistente '{site_name}' e continuare?", "n"):
            error("Operazione annullata. Site esistente non rimosso.")
        
        log("Fermo il site...")
        run_command(["omd", "stop", site_name], check=False)
        
        log("Rimuovo site esistente...")
        try:
            run_command(["omd", "rm", "--kill", site_name])
            success("Site rimosso con successo")
        except Exception as e:
            error(f"Rimozione site fallita: {e}")
    else:
        log("Nessun site esistente, procedo con restore pulito")


def restore_backup(tarfile: Path) -> None:
    """Restore backup using omd restore.
    
    Args:
        tarfile: Path to backup tar.gz file"""
    title(" Restore Backup")
    
    log(f"Ripristino backup da {tarfile}...")
    
    try:
        run_command(["omd", "restore", str(tarfile)])
        success("Backup ripristinato")
    except Exception as e:
        error(f"omd restore fallito: {e}")


def post_restore_compressed(site_name: str) -> None:
    """Post-restore actions for compressed backups (job00-daily).
    
    Args:
        site_name: Site name"""
    title(" Post-Restore: Backup Compresso (job00-daily)")
    
    log("Backup compresso rilevato - creo directory mancanti...")
    
    site_dir = Path(f"/opt/omd/sites/{site_name}")
    
    # Critical directories removed during compression
    required_dirs = [
        site_dir / "var/nagios",
        site_dir / "var/nagios/rrd",
        site_dir / "var/log/apache",
        site_dir / "var/log/nagios",
        site_dir / "var/log/agent-receiver",
        site_dir / "var/check_mk/crashes",
        site_dir / "var/check_mk/inventory_archive",
        site_dir / "var/check_mk/logwatch",
        site_dir / "var/check_mk/wato/snapshots",
        site_dir / "var/check_mk/wato/log",
        site_dir / "var/check_mk/rest_api",
        site_dir / "var/check_mk/precompiled_checks",
        site_dir / "var/tmp",
        site_dir / "tmp",
    ]
    
    for dir_path in required_dirs:
        if not dir_path.exists():
            log(f"   Creo: {dir_path.name}")
            dir_path.mkdir(parents=True, exist_ok=True)
    
    success("Directory mancanti create")
    
    # Fix ownership
    title(" Correzione Ownership e Permessi (job00)")
    
    log("Correggo ownership ricorsivo...")
    run_command(["chown", "-R", f"{site_name}:{site_name}", str(site_dir / "var/log")], check=False)
    run_command(["chown", "-R", f"{site_name}:{site_name}", str(site_dir / "var/nagios")], check=False)
    run_command(["chown", "-R", f"{site_name}:{site_name}", str(site_dir / "var/check_mk")], check=False)
    run_command(["chown", "-R", f"{site_name}:{site_name}", str(site_dir / "var/tmp")], check=False)
    run_command(["chown", "-R", f"{site_name}:{site_name}", str(site_dir / "tmp")], check=False)
    
    log("Correggo permessi directory sensibili...")
    run_command(["chmod", "750", str(site_dir / "var/log/apache")], check=False)
    run_command(["chmod", "755", str(site_dir / "var/log/nagios")], check=False)
    run_command(["chmod", "755", str(site_dir / "var/nagios")], check=False)
    
    success("Ownership e permessi corretti per backup compresso")


def post_restore_full(site_name: str) -> None:
    """Post-restore actions for full backups (job01-weekly).
    
    Args:
        site_name: Site name"""
    title(" Post-Restore: Backup Completo (job01-weekly)")
    
    log("Backup completo rilevato - nessuna directory da ricreare")
    log("Verifico solo ownership base...")
    
    site_dir = Path(f"/opt/omd/sites/{site_name}")
    run_command(["chown", f"{site_name}:{site_name}", str(site_dir)], check=False)
    
    success("Backup completo ripristinato correttamente")


def start_site(site_name: str) -> None:
    """Start the CheckMK site.
    
    Args:
        site_name: Site name"""
    title(" Avvio Site")
    
    log(f"Avvio site '{site_name}'...")
    
    try:
        run_command(["omd", "start", site_name])
        success("Site avviato")
    except Exception as e:
        error(f"Avvio site fallito. Controlla i log in /opt/omd/sites/{site_name}/var/log/")


def verify_site_status(site_name: str) -> None:
    """Verify site status after restore.
    
    Args:
        site_name: Site name"""
    title(" Verifica Status Finale")
    
    print("")
    run_command(["omd", "status", site_name], check=False)


def change_cmkadmin_password(site_name: str) -> None:
    """Force change of cmkadmin password for security.
    
    Args:
        site_name: Site name"""
    print("")
    title(" Cambio Password cmkadmin (OBBLIGATORIO)")
    
    print("")
    warn("  Per motivi di sicurezza, DEVI cambiare la password di cmkadmin")
    print("")
    log(f"Imposta ora la nuova password per l'utente 'cmkadmin' del site '{site_name}'")
    print("")
    
    try:
        # Run cmk-passwd as site user
        run_command(["su", "-", site_name, "-c", "cmk-passwd cmkadmin"])
        print("")
        success("Password cmkadmin cambiata con successo")
    except Exception as e:
        print("")
        error("Cambio password fallito. Il disaster recovery non può completarsi senza una password sicura.")


def print_final_summary(selected_backup: str, is_compressed: bool, 
                        site_name: str, backup_size_mb: float) -> None:
    """Print final summary of disaster recovery operation.
    
    Args:
        selected_backup: Backup name
        is_compressed: Whether it was compressed
        site_name: Site name
        backup_size_mb: Backup size in MB"""
    print("")
    title(" DISASTER RECOVERY COMPLETATO!")
    
    backup_type = "Compresso (job00-daily)" if is_compressed else "Completo (job01-weekly)"
    hostname = run_command(["hostname"], capture_output=True).stdout.strip()
    
    print("")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║                    RIEPILOGO OPERAZIONE                    ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print("")
    print(f"   Backup:      {selected_backup}")
    print(f"   Tipo:        {backup_type}")
    print(f"   Site:        {site_name}")
    print(f"   Dimensione:  {backup_size_mb:.1f} MB")
    print("   Status:      RUNNING")
    print("")
    print(f"   Web UI:      http://{hostname}/{site_name}/")
    print(f"   Site dir:    /opt/omd/sites/{site_name}")
    print(f"   Logs:        /opt/omd/sites/{site_name}/var/log/")
    print("")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║                      PROSSIMI PASSI                        ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print("")
    print("  1. Accedi alla Web UI e verifica la configurazione")
    print("  2. Controlla che tutti gli host siano monitorati correttamente")
    print("  3. Verifica le notifiche email/telegram")
    print(f"  4. Rimuovi backup temporaneo: rm -rf {DOWNLOAD_DIR}")
    print("")
    
    success("Disaster recovery completato con successo! ")


def main() -> int:
    """Main entry point.
    
    Returns:
        Exit code (0=success, 1=error)"""
    check_root()
    
    # Clear screen and show banner
    os.system('clear')
    title(" CHECKMK DISASTER RECOVERY ")
    
    print("")
    print("Questo script eseguirà:")
    print("  1⃣  Lista backup disponibili su cloud")
    print("  2⃣  Download backup selezionato")
    print("  3⃣  Restore automatico del backup")
    print("  4⃣  Verifica stato servizi CheckMK")
    print("")
    warn("  ATTENZIONE: Questa operazione RIMUOVERÀ il site esistente!")
    print("")
    
    if not confirm("Vuoi procedere con il disaster recovery?", "n"):
        error("Operazione annullata dall'utente")
    
    # Install/verify rclone
    install_rclone()
    
    # Find rclone config
    rclone_config = find_rclone_config()
    
    # Select job type
    rclone_path, is_compressed = select_job_type()
    
    # List and select backup
    backup_map = list_available_backups(rclone_config, rclone_path)
    selected_backup = select_backup(backup_map)
    
    # Extract site name
    site_name = extract_site_name(selected_backup)
    
    # Confirm operation
    confirm_disaster_recovery(selected_backup, rclone_path, is_compressed, site_name)
    
    # Download backups
    backup_dir = download_backup(rclone_config, rclone_path, selected_backup)
    
    # Verify downloaded backup
    tarfile = verify_downloaded_backup(backup_dir, site_name)
    backup_size_mb = tarfile.stat().st_size / (1024 * 1024)
    
    # Remove existing site if present
    remove_existing_site(site_name)
    
    # Restore backup
    restore_backup(tarfile)
    
    # Post-restore actions
    if is_compressed:
        post_restore_compressed(site_name)
    else:
        post_restore_full(site_name)
    
    # Start site
    start_site(site_name)
    
    # Verify status
    verify_site_status(site_name)
    
    # Change cmkadmin password
    change_cmkadmin_password(site_name)
    
    # Print final summary
    print_final_summary(selected_backup, is_compressed, site_name, backup_size_mb)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
