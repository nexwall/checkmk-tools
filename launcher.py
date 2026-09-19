#!/usr/bin/env python3
"""Interactive Launcher - Run remote scripts from the GitHub repository
Scans all remote folders/ and features interactive menu

Version: 1.0.0"""

import sys
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import json

VERSION = "1.0.0"
REPO_URL = "https://raw.githubusercontent.com/nethesis/checkmk-tools/main"
SCRIPT_DIR = Path(__file__).parent.absolute()
HOME = Path.home()
FAVORITES_FILE = HOME / ".launcher-favorites.json"
STATS_FILE = HOME / ".launcher-stats.json"

# Colori ANSI
class Colors:
    GREEN = '\033[0;32m'
    BLUE = '\033[0;34m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    CYAN = '\033[0;36m'
    MAGENTA = '\033[0;35m'
    NC = '\033[0m'  # No Color


class LauncherData:
    """Manages persistent launcher data."""
    
    def __init__(self):
        self.scripts: List[str] = []
        self.script_paths: List[str] = []
        self.script_descriptions: List[str] = []
        self.script_extensions: List[str] = []
        self.favorites: Dict[str, bool] = {}
        self.stats: Dict[str, int] = {}
        self.categories: Dict[str, List[int]] = {}
        self.category_order: List[str] = []
        self.load_favorites()
        self.load_stats()
    
    def load_favorites(self) -> None:
        """Load bookmarks from JSON file."""
        if FAVORITES_FILE.exists():
            try:
                with open(FAVORITES_FILE, 'r', encoding='utf-8') as f:
                    self.favorites = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.favorites = {}
    
    def save_favorites(self) -> None:
        """Save bookmarks to JSON file."""
        try:
            with open(FAVORITES_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.favorites, f, indent=2)
        except IOError as e:
            print(f"{Colors.RED} Errore salvataggio preferiti: {e}{Colors.NC}")
    
    def load_stats(self) -> None:
        """Load statistics from JSON file."""
        if STATS_FILE.exists():
            try:
                with open(STATS_FILE, 'r', encoding='utf-8') as f:
                    self.stats = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.stats = {}
    
    def save_stats(self) -> None:
        """Save statistics to JSON file."""
        try:
            with open(STATS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.stats, f, indent=2)
        except IOError as e:
            print(f"{Colors.RED} Errore salvataggio statistiche: {e}{Colors.NC}")
    
    def increment_usage(self, idx: str) -> None:
        """Incrementa contatore utilizzo script."""
        count = self.stats.get(idx, 0)
        self.stats[idx] = count + 1
        self.save_stats()
    
    def get_total_runs(self) -> int:
        """Calcola totale esecuzioni."""
        return sum(self.stats.values())

    def build_categories(self) -> None:
        """Constructs the mapping categories -> script indexes."""
        self.categories = {}
        self.category_order = []

        for idx, script in enumerate(self.scripts):
            if '[' in script and ']' in script:
                category = script.split('[', 1)[1].split(']', 1)[0]
            else:
                category = "Altro"

            if category not in self.categories:
                self.categories[category] = []
                self.category_order.append(category)

            self.categories[category].append(idx)


def print_header(data: LauncherData) -> None:
    """Print launcher header."""
    print(f"{Colors.BLUE}═══════════════════════════════════════════════════════════{Colors.NC}")
    print(f"{Colors.GREEN} Interactive Launcher - CheckMK Tools Repository{Colors.NC}")
    print(f"{Colors.CYAN} Preferiti: {len(data.favorites)}{Colors.NC}    {Colors.MAGENTA} Script eseguiti: {data.get_total_runs()}{Colors.NC}")
    print()


def get_script_description(script_path: Path) -> str:
    """Estrae descrizione dallo script leggendo i commenti iniziali.
    
    Args:
        script_path: Path assoluto allo script
        
    Returns:
        Descrizione estratta o fallback"""
    if not script_path.exists():
        return "Script non trovato localmente"
    
    try:
        with open(script_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()[:10]
            
        # Search comment with Description/Desc/Purpose
        for line in lines:
            if line.startswith('# ') and any(keyword in line for keyword in ['Desc:', 'Description:', 'Purpose:']):
                return line.split(':', 1)[1].strip()
        
        # Fallback: seconda riga (solitamente descrizione)
        if len(lines) > 1 and lines[1].startswith('#'):
            return lines[1].lstrip('# ').strip()
        
        return "Nessuna descrizione disponibile"
    
    except IOError:
        return "Errore lettura script"


def scan_remote_scripts(data: LauncherData) -> None:
    """Scan local repository to find COMPLETE scripts (no remote)."""
    print(f"{Colors.YELLOW} Scansione script completi (full/) in corso...{Colors.NC}\n")

    # Find all full scripts in full/ directories
    full_scripts: List[Path] = []

    # Script Python completi
    full_scripts.extend(sorted(SCRIPT_DIR.glob("*/full/*.py")))
    # Complete Bash scripts (for tools not yet converted)
    full_scripts.extend(sorted(SCRIPT_DIR.glob("*/full/*.sh")))

    for script in full_scripts:
        rel_path = script.relative_to(SCRIPT_DIR)
        category = rel_path.parts[0]
        script_name = script.stem

        display_name = script_name

        data.scripts.append(f"[{category}] {display_name}")
        data.script_paths.append(str(rel_path))
        data.script_descriptions.append(get_script_description(script))
        data.script_extensions.append(script.suffix.lower())

    # Constructs the categories -> script mapping
    data.build_categories()

    print(f"{Colors.GREEN} Trovati {len(data.scripts)} script completi{Colors.NC}\n")


def search_scripts(data: LauncherData, query: str) -> None:
    """Search scripts by name or description.
    
    Args:
        data: LauncherData object
        query: Search term"""
    query_lower = query.lower()
    results = []
    
    for i, (script, desc) in enumerate(zip(data.scripts, data.script_descriptions)):
        if query_lower in script.lower() or query_lower in desc.lower():
            results.append(i)
    
    if not results:
        print(f"{Colors.RED} Nessun risultato trovato per: '{query}'{Colors.NC}\n")
        return
    
    print(f"{Colors.GREEN} Risultati ricerca '{query}':{Colors.NC}\n")
    for idx in results:
        star = f"{Colors.YELLOW}{Colors.NC} " if str(idx) in data.favorites else ""
        script_name = data.scripts[idx].split('] ', 1)[1] if '] ' in data.scripts[idx] else data.scripts[idx]
        print(f"  {Colors.BLUE}{idx:3d}){Colors.NC} {star}{script_name}")
    print()


def show_script_details(data: LauncherData, idx: int) -> None:
    """Show details of a script.
    
    Args:
        data: LauncherData object
        idx: Index of the script"""
    if idx < 0 or idx >= len(data.scripts):
        print(f"{Colors.RED} Script non valido!{Colors.NC}\n")
        return
    
    print(f"{Colors.CYAN}╔═══════════════════════════════════════════════════════════╗{Colors.NC}")
    print(f"{Colors.CYAN}║{Colors.NC}   {Colors.GREEN}Dettagli Script{Colors.NC}                                    {Colors.CYAN}║{Colors.NC}")
    print(f"{Colors.CYAN}╠═══════════════════════════════════════════════════════════╣{Colors.NC}")
    print(f"{Colors.CYAN}║{Colors.NC}  {Colors.YELLOW}Nome:{Colors.NC} {data.scripts[idx]}")
    print(f"{Colors.CYAN}║{Colors.NC}  {Colors.YELLOW}Path:{Colors.NC} {data.script_paths[idx]}")
    print(f"{Colors.CYAN}║{Colors.NC}  {Colors.YELLOW}Descrizione:{Colors.NC}")
    print(f"{Colors.CYAN}║{Colors.NC}    {data.script_descriptions[idx]}")
    print(f"{Colors.CYAN}║{Colors.NC}  {Colors.YELLOW}Utilizzi:{Colors.NC} {data.stats.get(str(idx), 0)}")
    if str(idx) in data.favorites:
        print(f"{Colors.CYAN}║{Colors.NC}  {Colors.YELLOW}Preferito:{Colors.NC}  Sì")
    print(f"{Colors.CYAN}╚═══════════════════════════════════════════════════════════╝{Colors.NC}\n")


def show_favorites(data: LauncherData) -> None:
    """Show only favorite scripts."""
    if not data.favorites:
        print(f"{Colors.YELLOW} Nessun preferito salvato{Colors.NC}\n")
        return
    
    print(f"{Colors.YELLOW} Script preferiti:{Colors.NC}\n")
    for idx_str in data.favorites.keys():
        idx = int(idx_str)
        if idx < len(data.scripts):
            script_name = data.scripts[idx].split('] ', 1)[1] if '] ' in data.scripts[idx] else data.scripts[idx]
            print(f"  {Colors.BLUE}{idx:3d}){Colors.NC} {script_name}")
    print()


def toggle_favorite(data: LauncherData, idx: int) -> None:
    """Add/remove scripts from favorites.
    
    Args:
        data: LauncherData object
        idx: Index of the script"""
    idx_str = str(idx)
    
    if idx_str in data.favorites:
        del data.favorites[idx_str]
        print(f"{Colors.GREEN} Rimosso dai preferiti{Colors.NC}")
    else:
        data.favorites[idx_str] = True
        print(f"{Colors.GREEN} Aggiunto ai preferiti {Colors.NC}")
    
    data.save_favorites()


def show_statistics(data: LauncherData) -> None:
    """Show usage statistics."""
    print(f"{Colors.MAGENTA}╔═══════════════════════════════════════════════════════════╗{Colors.NC}")
    print(f"{Colors.MAGENTA}║{Colors.NC}   {Colors.GREEN}Statistiche di Utilizzo{Colors.NC}                          {Colors.MAGENTA}║{Colors.NC}")
    print(f"{Colors.MAGENTA}╠═══════════════════════════════════════════════════════════╣{Colors.NC}")
    print(f"{Colors.MAGENTA}║{Colors.NC}  {Colors.YELLOW}Totale esecuzioni:{Colors.NC} {data.get_total_runs()}")
    print(f"{Colors.MAGENTA}║{Colors.NC}  {Colors.YELLOW}Script più usati:{Colors.NC}")
    
    if data.stats:
        # Top 5 script più usati
        sorted_stats = sorted(data.stats.items(), key=lambda x: x[1], reverse=True)[:5]
        
        for i, (idx_str, count) in enumerate(sorted_stats, start=1):
            idx = int(idx_str)
            if idx < len(data.scripts):
                script_name = data.scripts[idx].split('] ', 1)[1] if '] ' in data.scripts[idx] else data.scripts[idx]
                print(f"{Colors.MAGENTA}║{Colors.NC}    {Colors.BLUE}{i}.{Colors.NC} {script_name} {Colors.CYAN}({count}){Colors.NC}")
    else:
        print(f"{Colors.MAGENTA}║{Colors.NC}    {Colors.YELLOW}Nessuna statistica disponibile{Colors.NC}")
    
    print(f"{Colors.MAGENTA}╚═══════════════════════════════════════════════════════════╝{Colors.NC}\n")


def show_menu(data: LauncherData) -> None:
    """Show main menu with collapsed categories."""
    print(f"{Colors.BLUE}═══════════════════════════════════════════════════════════{Colors.NC}")
    print(f"{Colors.GREEN}Categorie disponibili:{Colors.NC}")
    print(f"{Colors.CYAN}Comandi: {Colors.YELLOW}s){Colors.NC}Cerca {Colors.YELLOW}f){Colors.NC}Preferiti {Colors.YELLOW}i){Colors.NC}Info {Colors.YELLOW}t){Colors.NC}Stats {Colors.YELLOW}*+){Colors.NC}Aggiungi/Rimuovi {Colors.NC}\n")

    if not data.category_order:
        print(f"{Colors.RED} Nessuna categoria trovata{Colors.NC}")
    else:
        for idx, category in enumerate(data.category_order, start=1):
            scripts_idx = data.categories.get(category, [])
            count = len(scripts_idx)
            # Calculate total uses for the category
            total_uses = sum(data.stats.get(str(i), 0) for i in scripts_idx)
            print(f"  {Colors.BLUE}{idx:3d}){Colors.NC} {category} {Colors.CYAN}({count} script, {total_uses} run){Colors.NC}")

    print(f"\n{Colors.BLUE}═══════════════════════════════════════════════════════════{Colors.NC}")
    print(f"  {Colors.RED}0){Colors.NC} Esci  {Colors.YELLOW}s){Colors.NC}Cerca  {Colors.YELLOW}f){Colors.NC}Preferiti  {Colors.YELLOW}i){Colors.NC}Info  {Colors.YELLOW}t){Colors.NC}Stats")
    print(f"{Colors.BLUE}═══════════════════════════════════════════════════════════{Colors.NC}\n")


def show_category_scripts_menu(data: LauncherData, category: str, filter_ext: Optional[str] = None) -> List[int]:
    """Mostra gli script di una singola categoria.

    Restituisce la lista degli indici globali visualizzati (dopo il filtro),
    in modo che il chiamante possa mappare la scelta locale → indice globale."""
    scripts_idx = data.categories.get(category, [])

    # Apply extension filter if required
    if filter_ext:
        filtered_idx = [i for i in scripts_idx if data.script_extensions[i] == filter_ext]
    else:
        filtered_idx = list(scripts_idx)

    print(f"{Colors.BLUE}═══════════════════════════════════════════════════════════{Colors.NC}")
    if filter_ext == '.py':
        suffix_label = "solo Python (.py)"
    elif filter_ext == '.sh':
        suffix_label = "solo Bash (.sh)"
    else:
        suffix_label = "tutti gli script"

    print(f"{Colors.GREEN}Categoria:{Colors.NC} {category} {Colors.CYAN}({len(filtered_idx)} script, {suffix_label}){Colors.NC}")
    print(f"{Colors.CYAN}Comandi: numero script, 0=indietro, p=solo .py, s=solo .sh, a=tutti{Colors.NC}\n")

    for local_idx, global_idx in enumerate(filtered_idx, start=1):
        # Stella se preferito
        star = f"{Colors.YELLOW}{Colors.NC} " if str(global_idx) in data.favorites else ""

        # Number of uses
        uses = ""
        if str(global_idx) in data.stats:
            uses = f" {Colors.CYAN}({data.stats[str(global_idx)]}){Colors.NC}"

        script = data.scripts[global_idx]
        script_name = script.split('] ', 1)[1] if '] ' in script else script

        # Aggiungi estensione visibile
        ext = data.script_extensions[global_idx]

        print(f"  {Colors.BLUE}{local_idx:3d}){Colors.NC} {star}{script_name} {Colors.MAGENTA}[{ext}]{Colors.NC}{uses}")

    print(f"\n{Colors.BLUE}═══════════════════════════════════════════════════════════{Colors.NC}")
    print(f"  {Colors.RED}0){Colors.NC} Torna al menu categorie   {Colors.YELLOW}p){Colors.NC}.py   {Colors.YELLOW}s){Colors.NC}.sh   {Colors.YELLOW}a){Colors.NC}tutti")
    print(f"{Colors.BLUE}═══════════════════════════════════════════════════════════{Colors.NC}\n")

    return filtered_idx


def execute_script(data: LauncherData, selection: int) -> bool:
    """Run selected script by downloading it from GitHub.
    
    Args:
        data: LauncherData object
        selection: Index of the script to execute
        
    Returns:
        True if successful, False otherwise"""
    if selection < 0 or selection >= len(data.scripts):
        print(f"{Colors.RED} Selezione non valida!{Colors.NC}\n")
        return False
    
    script_path = data.script_paths[selection]
    script_name = data.scripts[selection]
    remote_url = f"{REPO_URL}/{script_path}"
    
    # Incrementa statistiche
    data.increment_usage(str(selection))
    
    print(f"\n{Colors.GREEN}▶ Esecuzione:{Colors.NC} {script_name}")
    print(f"{Colors.BLUE}   URL (full script):{Colors.NC} {remote_url}\n")
    
    # Chiedi parametri aggiuntivi
    print(f"{Colors.YELLOW}Parametri aggiuntivi (invio per nessuno):{Colors.NC}")
    params = input().strip()
    
    print(f"\n{Colors.BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}\n")
    
    # Download complete script in temporary file
    try:
        # Determines script type based on extension
        script_suffix = Path(script_path).suffix.lower()

        # Temporary file extension consistent with the script type
        temp_suffix = script_suffix if script_suffix in ['.py', '.sh'] else '.sh'

        with tempfile.NamedTemporaryFile(mode='w', suffix=temp_suffix, delete=False) as temp_file:
            temp_script = temp_file.name

        with urllib.request.urlopen(remote_url, timeout=30) as response:
            script_content = response.read().decode('utf-8')

        with open(temp_script, 'w', encoding='utf-8') as f:
            f.write(script_content)

        # Rendi eseguibile
        os.chmod(temp_script, 0o755)

        # Construct execute command based on type
        if script_suffix == '.py':
            cmd = ['python3', temp_script]
        else:
            cmd = ['bash', temp_script]

        if params:
            cmd.extend(params.split())

        # Determine if sudo/su is needed
        is_root = os.geteuid() == 0 if hasattr(os, 'geteuid') else False
        
        if not is_root:
            # Try sudo
            if os.system('which sudo >/dev/null 2>&1') == 0:
                cmd.insert(0, 'sudo')
            elif os.system('which su >/dev/null 2>&1') == 0:
                cmd = ['su', '-c', ' '.join(cmd)]
        
        result = subprocess.run(cmd)
        exit_code = result.returncode
        
        # Cleanup
        try:
            os.unlink(temp_script)
        except OSError:
            pass
        
        print(f"\n{Colors.BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
        
        if exit_code == 0:
            print(f"{Colors.GREEN} Script completato con successo{Colors.NC}\n")
            return True
        else:
            print(f"{Colors.RED} Script terminato con errore (exit code: {exit_code}){Colors.NC}\n")
            return False
    
    except urllib.error.URLError as e:
        print(f"{Colors.RED} Errore download script: {e}{Colors.NC}\n")
        return False
    except Exception as e:
        print(f"{Colors.RED} Errore esecuzione: {e}{Colors.NC}\n")
        return False
    finally:
        # Pause before returning to the menu
        print(f"{Colors.YELLOW}Premi INVIO per continuare...{Colors.NC}")
        input()


def clear_screen() -> None:
    """Cleans the screen cross-platformly."""
    os.system('clear' if os.name != 'nt' else 'cls')


def main() -> int:
    """Main entry point of the launcher."""
    
    # Check prerequisites
    if os.system('which curl >/dev/null 2>&1') != 0:
        print(f"{Colors.RED} Errore: curl non trovato. Installalo con: apt install curl{Colors.NC}")
        return 1
    
    # Inizializza dati
    data = LauncherData()
    
    # Print headers and scan scripts
    print_header(data)
    scan_remote_scripts(data)
    
    # Loop principale
    while True:
        clear_screen()
        print_header(data)
        show_menu(data)
        
        print(f"{Colors.YELLOW}Seleziona una categoria o comando:{Colors.NC} ", end='')
        selection = input().strip()
        
        # Comandi speciali
        if selection == '0':
            print(f"{Colors.GREEN}Arrivederci! {Colors.NC}")
            return 0
        
        elif selection.lower() in ['s', 'S']:
            print(f"{Colors.CYAN} Cerca script:{Colors.NC} ", end='')
            query = input().strip()
            search_scripts(data, query)
            print(f"{Colors.YELLOW}Premi INVIO per continuare...{Colors.NC}")
            input()
        
        elif selection.lower() in ['f', 'F']:
            show_favorites(data)
            print(f"{Colors.YELLOW}Premi INVIO per continuare...{Colors.NC}")
            input()
        
        elif selection.lower() in ['i', 'I']:
            print(f"{Colors.CYAN} Numero script per info:{Colors.NC} ", end='')
            idx_input = input().strip()
            if idx_input.isdigit():
                show_script_details(data, int(idx_input))
            else:
                print(f"{Colors.RED} Numero non valido{Colors.NC}")
            print(f"{Colors.YELLOW}Premi INVIO per continuare...{Colors.NC}")
            input()
        
        elif selection.lower() in ['t', 'T']:
            show_statistics(data)
            print(f"{Colors.YELLOW}Premi INVIO per continuare...{Colors.NC}")
            input()
        
        elif selection.endswith('+'):
            idx_str = selection[:-1]
            if idx_str.isdigit():
                toggle_favorite(data, int(idx_str))
                import time
                time.sleep(1)
            else:
                print(f"{Colors.RED} Formato: numero+ (es: 57+){Colors.NC}")
                import time
                time.sleep(2)
        
        elif selection.isdigit():
            # Selecting a category from the main menu
            cat_idx = int(selection)

            if 1 <= cat_idx <= len(data.category_order):
                category = data.category_order[cat_idx - 1]

                # Submenu for the chosen category (with filter by extension)
                current_filter: Optional[str] = None  # None=tutti, '.py', '.sh'

                while True:
                    clear_screen()
                    print_header(data)
                    visible_idx = show_category_scripts_menu(data, category, current_filter)

                    print(f"{Colors.YELLOW}Seleziona uno script (0/p/s/a):{Colors.NC} ", end='')
                    script_sel = input().strip().lower()

                    if script_sel == '0':
                        break

                    # Cambia filtro estensione
                    if script_sel == 'p':
                        current_filter = '.py'
                        continue
                    if script_sel == 's':
                        current_filter = '.sh'
                        continue
                    if script_sel == 'a':
                        current_filter = None
                        continue

                    if script_sel.isdigit():
                        local_idx = int(script_sel)

                        if 1 <= local_idx <= len(visible_idx):
                            global_idx = visible_idx[local_idx - 1]
                            execute_script(data, global_idx)
                        else:
                            print(f"{Colors.RED} Numero script non valido{Colors.NC}")
                            import time
                            time.sleep(2)
                    else:
                        print(f"{Colors.RED} Selezione non valida{Colors.NC}")
                        import time
                        time.sleep(2)
            else:
                print(f"{Colors.RED} Categoria non valida{Colors.NC}")
                import time
                time.sleep(2)
        
        else:
            print(f"{Colors.RED} Comando non riconosciuto!{Colors.NC}\n")
            import time
            time.sleep(2)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrotto dall'utente{Colors.NC}")
        sys.exit(130)
    except Exception as e:
        print(f"{Colors.RED} Errore inatteso: {e}{Colors.NC}")
        sys.exit(1)
