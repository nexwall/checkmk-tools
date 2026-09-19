#!/usr/bin/env python3
"""sync-python-full-checks.py - Synchronize and deploy Python local checks

Copy Python checks from category_dir/full/*.py to /usr/lib/check_mk_agent/local/
(without .py extension). Category directories are an explicit allowlist
(KNOWN_CATEGORIES below), not a glob pattern - a directory not in that list
(e.g. script-notify-checkmk, manually-deployed notification scripts) is never
touched by this tool, regardless of its name.

Used by install-checkmk-agent-linux.py as STEP 2.

Topics:
  --repo Path local repository (default: /opt/checkmk-tools)
  --target Local checks target directory (default: /usr/lib/check_mk_agent/local)
  --category Specify one category from KNOWN_CATEGORIES, or a comma-separated
                   list declaring the COMPLETE set for this host (enables
                   orphan cleanup, same as auto-detect) (default: auto-detect)
  --all-categories Sync every category in KNOWN_CATEGORIES
  --scripts Specific script names to deploy, separated by commas
                   Ex: check_fail2ban_status,check_disk_space
  --temp-dir Deploy to temp directory instead of --target
                   (preview without real deployment)
  --exclude-file File with script names to exclude (one per line)
                   Default: /etc/checkmk-python-full-sync.exclude

Version: 1.5.0"""

import argparse
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import List, Optional, Set, Tuple

VERSION = "1.5.0"
TEMP_DIR_DEFAULT = "/tmp/checkmk-sync-preview"

REPO_DEFAULT = Path("/opt/checkmk-tools")
TARGET_DEFAULT = "/usr/lib/check_mk_agent/local"
EXCLUDE_FILE_DEFAULT = "/etc/checkmk-python-full-sync.exclude"

# Explicit allowlist of category directories this tool will ever touch - no
# glob pattern anywhere. A directory not in this list (e.g. script-notify-checkmk,
# which holds manually-deployed notification scripts, never auto-synced) is
# invisible to auto-detect, --all-categories, and orphan cleanup, regardless
# of its name or whether it happens to match "script-check-*".
KNOWN_CATEGORIES = [
    "script-check-ns7",
    "script-check-ns8",
    "script-check-nsec8",
    "script-check-proxmox",
    "script-check-tmate-server",
    "script-check-ubuntu",
    "script-check-windows",
    "script-checkmk",
    "script-checkmk-us",
]


# ─── Utilities ────────────────────────────────────────────────────────────────

def set_executable(path: Path) -> None:
    """Makes the file executable (rwxr-xr-x)."""
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def load_exclude_list(exclude_file: Path) -> Set[str]:
    """Load exclude file and return a set of script names to skip.

    The exclude file contains one script name per line.
    Both source filename (check_vpn_tunnels.py) and deployed name
    (check_vpn_tunnels) are supported — the function strips .py
    and normalizes to stem-only for matching.

    Returns an empty set if the file does not exist or is empty.
    """
    if not exclude_file.is_file():
        return set()

    excluded: Set[str] = set()
    try:
        content = exclude_file.read_text().strip()
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Normalize: strip .py extension if present, keep stem
            name = line.replace(".py", "") if line.endswith(".py") else line
            excluded.add(name)
    except OSError:
        print(f"  [WARN] Cannot read exclude file: {exclude_file}", file=sys.stderr)
        return set()

    return excluded


def detect_host_categories() -> List[str]:
    """Detect which KNOWN_CATEGORIES actually apply to this host.

    Unlike a plain OS/distro guess, this picks exactly one base category
    (the host is never simultaneously NethServer 7 and Ubuntu) plus zero or
    more role add-ons (e.g. tmate-server) that can coexist with any base.
    """
    categories: List[str] = []

    # Base OS/platform - checked in order of specificity so that e.g. a
    # Debian-based Proxmox host is not mistaken for plain Ubuntu.
    if shutil.which("pveversion") or Path("/etc/pve").is_dir():
        categories.append("script-check-proxmox")
    elif Path("/etc/openwrt_release").is_file():
        categories.append("script-check-nsec8")
    elif Path("/etc/nethserver-release").is_file():
        # NethServer 7: classic single-file marker, no NS8 module env files.
        categories.append("script-check-ns7")
    elif Path("/etc/nethserver/api-server.env").is_file() or Path("/etc/nethserver/core.env").is_file():
        # NethServer 8: /etc/nethserver exists as a directory of per-module
        # env files instead of the NS7 single release file.
        categories.append("script-check-ns8")
    elif os.name == "nt" or Path("C:/Windows").exists():
        categories.append("script-check-windows")
    elif shutil.which("dpkg") or shutil.which("apt-get"):
        categories.append("script-check-ubuntu")
    # else: unrecognized base - no category guessed, avoid deploying checks
    # for a platform we can't confirm.

    # Role add-ons - independent of the base OS above.
    if shutil.which("tmate-ssh-server"):
        categories.append("script-check-tmate-server")

    return categories


def get_categories(repo: Path, category: str, all_categories: bool) -> List[Path]:
    """Returns list of category directories to process."""
    if all_categories:
        return [repo / name for name in KNOWN_CATEGORIES if (repo / name).is_dir()]

    if category and category != "auto":
        # Comma-separated list: caller is declaring the COMPLETE set of
        # categories for this host in one invocation (see run()'s cleanup
        # gate), not just a partial/ad-hoc selection.
        names = [c.strip() for c in category.split(",") if c.strip()]
        cat_paths = []
        for name in names:
            if name not in KNOWN_CATEGORIES:
                print(f"[ERROR] Categoria non ammessa (non in KNOWN_CATEGORIES): {name}", file=sys.stderr)
                sys.exit(1)
            cat_path = repo / name
            if not cat_path.is_dir():
                print(f"[ERROR] Categoria non trovata: {cat_path}", file=sys.stderr)
                sys.exit(1)
            cat_paths.append(cat_path)
        return cat_paths

    # Auto-detect: only the categories that actually match this host (base
    # OS/platform plus any applicable role add-ons), not every category that
    # happens to exist in the repo.
    detected = detect_host_categories()
    if not detected:
        print("[ERROR] Auto-detect: impossibile determinare la categoria di questo host.", file=sys.stderr)
        sys.exit(1)

    cats = []
    for name in detected:
        cat_path = repo / name
        if cat_path.is_dir() and (cat_path / "full").is_dir():
            print(f"[INFO] Auto-detect: categoria {name}")
            cats.append(cat_path)
        else:
            print(f"[WARN] Auto-detect: categoria {name} rilevata ma non trovata nel repo", file=sys.stderr)
    return cats


def find_launchers(category_dir: Path,
                   scripts_filter: Optional[Set[str]] = None) -> List[Path]:
    """Find check Python in category_dir/full/*.py

    If scripts_filter is specified, returns only checks
    whose stem (name without .py) is present in the set."""
    full_dir = category_dir / "full"
    if not full_dir.is_dir():
        return []
    # Only files starting with "check" → excludes daemons, utilities, etc.
    launchers = sorted(f for f in full_dir.glob("*.py") if f.stem.startswith("check"))
    if scripts_filter:
        launchers = [l for l in launchers if l.stem in scripts_filter]
    return launchers


def all_category_dirs(repo: Path) -> List[Path]:
    """Every category directory this tool recognizes - strictly the
    KNOWN_CATEGORIES allowlist, nothing discovered via pattern matching."""
    return [repo / name for name in KNOWN_CATEGORIES if (repo / name).is_dir()]


def list_all_launchers(repo: Path) -> List[Path]:
    """Returns all checks available in the repo (all categories)."""
    result = []
    for cat in all_category_dirs(repo):
        full_dir = cat / "full"
        if full_dir.is_dir():
            result.extend(sorted(full_dir.glob("*.py")))
    return result


def deploy_name(launcher: Path) -> str:
    """Calculate the destination file name (without .py)."""
    name = launcher.stem  # rimuove .py
    return name


# ─── Deploy ───────────────────────────────────────────────────────────────────

def sync_category(category_dir: Path, target_dir: Path,
                  scripts_filter: Optional[Set[str]] = None,
                  exclude_set: Optional[Set[str]] = None) -> Tuple[int, int, int, int]:
    """Sync launchers in a category.

    Args:
        category_dir: One of the KNOWN_CATEGORIES directories
        target_dir: Deployment target (real or temp)
        scripts_filter: If specified, deploy only scripts in the set
        exclude_set: If specified, skip scripts whose stem is in this set

    Returns:
        (deployed, updated, skipped, excluded)"""
    launchers = find_launchers(category_dir, scripts_filter)
    if not launchers:
        return 0, 0, 0, 0

    deployed = 0
    updated = 0
    skipped = 0
    excluded = 0

    for launcher in launchers:
        dest_name = deploy_name(launcher)
        dest_path = target_dir / dest_name

        # Check exclude list — skip if the script stem is excluded
        if exclude_set and launcher.stem in exclude_set:
            print(f"  [EXCLUDED] {launcher.name} (in exclude list)")
            excluded += 1
            continue

        # Leggi contenuto sorgente
        try:
            src_content = launcher.read_bytes()
        except OSError as e:
            print(f"  [WARN] Impossibile leggere {launcher.name}: {e}")
            skipped += 1
            continue

        # If destination exists, check if it is identical
        if dest_path.exists():
            try:
                dest_content = dest_path.read_bytes()
                if src_content == dest_content:
                    skipped += 1
                    continue
            except OSError:
                pass
            # Different content → update
            try:
                dest_path.write_bytes(src_content)
                set_executable(dest_path)
                print(f"  [UPDATED] {launcher.name} → {dest_path}")
                updated += 1
            except OSError as e:
                print(f"  [ERROR] {launcher.name}: {e}")
                skipped += 1
        else:
            # Does not exist → deploy only if a deployed check with the same prefix already exists
            # (to respect the rule: deploy only if bash check is already present)
            # In sync mode (not first deploy) we copy directly
            try:
                dest_path.write_bytes(src_content)
                set_executable(dest_path)
                print(f"  [DEPLOYED] {launcher.name} → {dest_path}")
                deployed += 1
            except OSError as e:
                print(f"  [ERROR] {launcher.name}: {e}")
                skipped += 1

    return deployed, updated, skipped, excluded


def remove_orphans(repo: Path, target_dir: Path, deployed_stems: Set[str],
                    exclude_set: Set[str]) -> int:
    """Remove stale local checks left behind by a previous, wrongly-broad
    sync (e.g. the auto-detect bug that used to deploy every category).

    Only removes a file if its name matches a KNOWN check stem from ANY
    KNOWN_CATEGORIES category - files unrelated to this sync tool
    are never touched. Anything in exclude_set is also left alone.
    """
    known_stems = {deploy_name(l) for l in list_all_launchers(repo)}
    removed = 0
    for entry in sorted(target_dir.iterdir()):
        if not entry.is_file():
            continue
        if entry.name in deployed_stems or entry.name in exclude_set:
            continue
        if entry.name not in known_stems:
            continue
        try:
            entry.unlink()
            print(f"  [REMOVED] {entry.name} (categoria non pertinente a questo host)")
            removed += 1
        except OSError as e:
            print(f"  [WARN] Impossibile rimuovere {entry.name}: {e}")
    return removed


def run(repo: Path, target_dir: Path, category: str, all_categories: bool,
        scripts_filter: Optional[Set[str]] = None,
        temp_dir: Optional[Path] = None,
        exclude_file: Optional[Path] = None) -> int:
    """Main entry point.

    Args:
        scripts_filter: If specified, deploy only scripts in the set
        temp_dir: If specified, deploy to this dir (preview)
        exclude_file: If specified, load exclude list from this file"""
    # Destinazione effettiva
    effective_target = temp_dir if temp_dir is not None else target_dir
    is_temp = temp_dir is not None

    # Carica exclude list
    exclude_set = load_exclude_list(exclude_file) if exclude_file else set()
    if exclude_set:
        print(f"  Exclude: {', '.join(sorted(exclude_set))}")

    print(f"=== sync-python-full-checks v{VERSION} ===")
    print(f"  Repo:   {repo}")
    if is_temp:
        print(f"  Target: {effective_target}  [ANTEPRIMA - non deploy reale]")
    else:
        print(f"  Target: {effective_target}")
    if scripts_filter:
        print(f"  Script: {', '.join(sorted(scripts_filter))}")
    print()

    if not repo.is_dir():
        print(f"[ERROR] Repository non trovato: {repo}", file=sys.stderr)
        return 1

    if not effective_target.is_dir():
        print(f"[INFO] Creo directory: {effective_target}")
        try:
            effective_target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"[ERROR] Impossibile creare target dir: {e}", file=sys.stderr)
            return 1

    # If scripts_filter specified → searches all categories ignoring --category
    if scripts_filter:
        categories = get_categories(repo, "auto", all_categories=True)
    else:
        categories = get_categories(repo, category, all_categories)

    if not categories:
        print("[WARN] Nessuna categoria trovata.")
        return 0

    total_deployed = 0
    total_updated = 0
    total_skipped = 0
    total_excluded = 0
    current_stems: Set[str] = set()

    for cat_dir in categories:
        cat_name = cat_dir.name
        current_stems.update(deploy_name(l) for l in find_launchers(cat_dir, scripts_filter))
        d, u, s, e = sync_category(cat_dir, effective_target, scripts_filter, exclude_set)
        total_deployed += d
        total_updated += u
        total_skipped += s
        total_excluded += e
        if d > 0 or u > 0:
            print()  # separatore visivo tra categorie con output

    # Cleanup: for a real (non-preview) auto-detect run, or an explicit
    # comma-separated --category list (the caller is declaring the COMPLETE
    # category set for this host in one invocation, same trust level as
    # auto-detect). A single bare --category stays additive-only, since that
    # is commonly used for partial/ad-hoc/testing deploys.
    total_removed = 0
    is_full_explicit_set = category not in ("auto", "") and "," in category
    if not is_temp and not scripts_filter and not all_categories and (category == "auto" or is_full_explicit_set):
        total_removed = remove_orphans(repo, effective_target, current_stems, exclude_set)

    print("─" * 40)
    if is_temp:
        print(f"[OK] Anteprima in: {effective_target}")
        print(f"     Per deployare davvero: cp {effective_target}/* {target_dir}/")
    print(f"[OK] Riepilogo: {total_deployed} deployati, {total_updated} aggiornati, {total_skipped} invariati, {total_excluded} esclusi, {total_removed} rimossi")
    return 0


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=f"sync-python-full-checks v{VERSION} - Deploy Python local checks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Deploy all categories
  sync-python-full-checks.py --all-categories

  # Deploy specific scripts only
  sync-python-full-checks.py --scripts rssh_fail2ban_status,rssh_disk_usage

  # Preview (temp dir) without real deployment
  sync-python-full-checks.py --all-categories --temp-dir /tmp/preview

  # List of available scripts
  sync-python-full-checks.py --list""",
    )
    p.add_argument("--repo", default=str(REPO_DEFAULT),
                   help=f"Path repository locale (default: {REPO_DEFAULT})")
    p.add_argument("--target", default=TARGET_DEFAULT,
                   help=f"Directory destinazione (default: {TARGET_DEFAULT})")
    p.add_argument("--category", default="auto",
                   help="Categoria da KNOWN_CATEGORIES, 'auto', oppure una lista separata da "
                        "virgole che dichiara l'insieme completo di categorie per l'host "
                        "(abilita la pulizia orfani, come auto-detect)")
    p.add_argument("--all-categories", action="store_true",
                   help="Sincronizza tutte le categorie")
    p.add_argument("--scripts",
                   help="Script specifici da deployare (nomi separati da virgola, senza .py)")
    p.add_argument("--temp-dir", default=None,
                   help=f"Deploy in directory temp invece di --target (anteprima)")
    p.add_argument("--exclude-file", default=EXCLUDE_FILE_DEFAULT,
                   help=f"File con lista di script da escludere (default: {EXCLUDE_FILE_DEFAULT})")
    p.add_argument("--list", action="store_true",
                   help="Mostra tutti gli script disponibili nel repo ed esce")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    repo = Path(args.repo)
    target = Path(args.target)

    # --list: mostra script disponibili ed esce
    if args.list:
        launchers = list_all_launchers(repo)
        if not launchers:
            print("[WARN] Nessuno script trovato.")
            return 0
        print(f"Script disponibili ({len(launchers)}):\n")
        for l in launchers:
            cat = l.parent.parent.name
            print(f"  {l.stem:<45} [{cat}]")
        return 0

    scripts_filter: Optional[Set[str]] = None
    if args.scripts:
        scripts_filter = {s.strip() for s in args.scripts.split(",") if s.strip()}

    temp_dir: Optional[Path] = None
    if args.temp_dir:
        temp_dir = Path(args.temp_dir)

    exclude_file: Optional[Path] = None
    if args.exclude_file:
        exclude_file = Path(args.exclude_file)

    return run(repo, target, args.category, args.all_categories,
               scripts_filter=scripts_filter, temp_dir=temp_dir,
               exclude_file=exclude_file)


if __name__ == "__main__":
    sys.exit(main())
