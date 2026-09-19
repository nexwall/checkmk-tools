#!/usr/bin/env python3
"""checkmk-periodic-discovery-autoapply.py

Ensures the root-folder "Periodic service discovery" WATO rule
(ruleset periodic_discovery, key inventory_rediscovery) has
add_new_services, remove_vanished_services and activation all enabled,
with check_interval at 120 minutes - so newly discovered/vanished
services get applied automatically, without a manual WATO "Fix all".

Runs locally on the OMD site host (same convention as
checkmk-tuning-interactive.py: SITE env var, default "monitoring").
Backup and edit are performed as the site user (su - <site>), never as
root, because rules.mk lives under conf.d/wato and a root-owned file
there previously caused an EACCES on the backup job's __pycache__
cleanup on srv-monitoring-sp.

Idempotent: re-running when the rule already matches the target does
nothing and exits 0.

Version: 1.0.0
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0"

TARGET = {
    "check_interval": "120.0",
    "add_new_services": "True",
    "remove_vanished_services": "True",
    "activation": "True",
}

FIELD_LABELS = {
    "check_interval": "check_interval (minuti)",
    "add_new_services": "add_new_services",
    "remove_vanished_services": "remove_vanished_services",
    "activation": "activation (auto-apply)",
}


class RuleNotFoundError(RuntimeError):
    """Raised when the root-folder periodic_discovery rule can't be located unambiguously."""


def log(message: str) -> None:
    print(f"[INFO] {message}")


def warn(message: str) -> None:
    print(f"[WARN] {message}")


def die(message: str) -> None:
    print(f"[ERR] {message}", file=sys.stderr)
    raise SystemExit(1)


# --- pure logic (unit-tested, no I/O) ---------------------------------------

def find_target_rule_line(content: str) -> tuple[int, str]:
    """Locate the single root-folder periodic_discovery rule line.

    Root-folder scope means an empty WATO condition (`'condition': {}`).
    `inventory_rediscovery` is a key unique to the periodic_discovery
    ruleset's value dict, so requiring both substrings on the same line
    reliably identifies the rule even though rules.mk aggregates every
    ruleset configured in that WATO folder, not just this one.
    """
    lines = content.splitlines()
    candidates = [
        i
        for i, line in enumerate(lines)
        if "'inventory_rediscovery'" in line and "'condition': {}" in line
    ]
    if len(candidates) != 1:
        raise RuleNotFoundError(
            f"attese 1 regola periodic_discovery a livello root, trovate {len(candidates)}"
        )
    idx = candidates[0]
    return idx, lines[idx]


def read_current_values(line: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for key in TARGET:
        match = re.search(rf"'{key}':\s*([A-Za-z0-9_.]+)", line)
        if not match:
            raise RuleNotFoundError(f"campo '{key}' non trovato nella regola")
        values[key] = match.group(1)
    return values


def compute_diff(current: dict[str, str], target: dict[str, str]) -> dict[str, tuple[str, str]]:
    return {key: (current[key], target[key]) for key in target if current[key] != target[key]}


def patch_field(line: str, key: str, target_repr: str) -> str:
    pattern = re.compile(rf"'{key}':\s*([A-Za-z0-9_.]+)")
    matches = list(pattern.finditer(line))
    if len(matches) != 1:
        raise RuleNotFoundError(
            f"atteso 1 occorrenza di '{key}' sulla riga, trovate {len(matches)}"
        )
    start, end = matches[0].span(1)
    return line[:start] + target_repr + line[end:]


def apply_patches(line: str, diff: dict[str, tuple[str, str]]) -> str:
    for key, (_current, target_repr) in diff.items():
        line = patch_field(line, key, target_repr)
    return line


# --- I/O (needs a real OMD site as root; not unit-tested) -------------------

def require_root() -> None:
    if os.geteuid() != 0:
        die("eseguire come root (sudo)")


def site_rules_mk(site: str) -> Path:
    path = Path(f"/omd/sites/{site}/etc/check_mk/conf.d/wato/rules.mk")
    if not path.is_file():
        die(f"file non trovato: {path}")
    return path


def su_run(site: str, command: str, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["su", "-", site, "-c", command],
        input=input_text,
        text=True,
        capture_output=True,
    )


def stat_owner_mode(path: Path) -> str:
    result = subprocess.run(
        ["stat", "-c", "%U:%G %a", str(path)], text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def backup_rules_mk(site: str, rules_mk: Path) -> Path:
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = rules_mk.with_name(f"rules.mk.bak-periodicdiscovery-{timestamp}")
    result = su_run(site, f"cp -p {shlex.quote(str(rules_mk))} {shlex.quote(str(backup_path))}")
    if result.returncode != 0:
        die(f"backup fallito: {result.stderr.strip()}")
    return backup_path


def write_rules_mk(site: str, rules_mk: Path, content: str) -> None:
    result = su_run(site, f"cat > {shlex.quote(str(rules_mk))}", input_text=content)
    if result.returncode != 0:
        die(f"scrittura fallita: {result.stderr.strip()}")


def run_cmk_o(site: str) -> subprocess.CompletedProcess:
    return su_run(site, "cmk -O")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", default=None, help="Nome sito OMD (default: env SITE o 'monitoring')")
    parser.add_argument("--dry-run", action="store_true", help="Mostra solo le differenze, non modifica nulla")
    parser.add_argument("-y", "--yes", action="store_true", help="Applica senza chiedere conferma")
    parser.add_argument("--version", action="store_true", help="Stampa la versione ed esce")
    args = parser.parse_args()

    if args.version:
        print(VERSION)
        return 0

    site = args.site or os.environ.get("SITE", "monitoring")

    require_root()
    rules_mk = site_rules_mk(site)
    content = rules_mk.read_text(encoding="utf-8")

    try:
        idx, line = find_target_rule_line(content)
        current = read_current_values(line)
    except RuleNotFoundError as exc:
        die(str(exc))
        return 1  # unreachable, keeps type-checkers happy

    diff = compute_diff(current, TARGET)

    print(f"Sito: {site}")
    print(f"File: {rules_mk}")
    print()

    if not diff:
        log("Configurazione gia' conforme al target, nessuna modifica necessaria.")
        return 0

    print("Differenze trovate (attuale -> target):")
    for key, (cur, tgt) in diff.items():
        print(f"  {FIELD_LABELS[key]:35s} {cur:>8s} -> {tgt}")
    print()

    if args.dry_run:
        log("Dry-run: nessuna modifica applicata.")
        return 1

    if not args.yes:
        confirm = input("Applicare queste modifiche? [y/N]: ").strip().lower() or "n"
        if confirm != "y":
            log("Annullato")
            return 0

    baseline_stat = stat_owner_mode(rules_mk)

    backup_path = backup_rules_mk(site, rules_mk)
    log(f"Backup creato: {backup_path}")

    lines = content.splitlines(keepends=True)
    original_line_with_ending = lines[idx]
    ending = original_line_with_ending[len(original_line_with_ending.rstrip("\n")):]
    lines[idx] = apply_patches(line, diff) + ending
    new_content = "".join(lines)

    write_rules_mk(site, rules_mk, new_content)
    log("Regola aggiornata.")

    for target_path in (rules_mk, backup_path):
        after_stat = stat_owner_mode(target_path)
        if after_stat != baseline_stat:
            warn(f"permessi inattesi su {target_path}: {after_stat} (atteso {baseline_stat})")

    log("Esecuzione 'cmk -O' (rigenera config core + reload)...")
    result = run_cmk_o(site)
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        die(f"'cmk -O' ha restituito un errore (exit {result.returncode})")

    final_content = rules_mk.read_text(encoding="utf-8")
    _, final_line = find_target_rule_line(final_content)
    final_values = read_current_values(final_line)
    if compute_diff(final_values, TARGET):
        die("verifica finale fallita: alcuni campi non risultano ancora conformi")

    log(f"Completato. Backup: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
