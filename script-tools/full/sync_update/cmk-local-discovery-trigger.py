#!/usr/bin/env python3
"""cmk-local-discovery-trigger.py

Detect changes in local check services seen by CheckMK (via `cmk -d HOST`) e
launch discovery/reload only when necessary.

Workflow:
1) Read hosts from site (`cmk --list-hosts`) or `--hosts`
2) Extracts the <<<local>>> section of the agent output
3) Compute stable hash of the service name list
4) If hash changed: run `cmk -IIv HOST`
5) If at least one host updated: run a single `cmk -O` (if `--activate`)

Version: 1.3.8"""

import argparse
import fcntl
import hashlib
import json
import os
import pwd
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set

VERSION = "1.3.8"
DEBUG = False
LOG_FILE = Path(os.getenv("CHECKMK_AUTOHEAL_LOG_FILE", "/var/log/checkmk_server_autoheal.log"))


def append_log(level: str, message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [{level}] {message}\n"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not LOG_FILE.exists():
            LOG_FILE.touch(exist_ok=True)
            LOG_FILE.chmod(0o666)
        with LOG_FILE.open("a", encoding="utf-8") as file_obj:
            file_obj.write(line)
    except OSError:
        pass


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [INFO] {message}")
    append_log("INFO", message)


def warn(message: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [WARN] {message}")
    append_log("WARN", message)


def error(message: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] {message}")
    append_log("ERROR", message)


def debug(message: str) -> None:
    if DEBUG:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [DEBUG] {message}")
        append_log("DEBUG", message)


def run_site_cmd(site: str, cmk_command: str, timeout: int = 180) -> subprocess.CompletedProcess:
    site_path = f"/omd/sites/{site}/bin"
    shell_cmd = f"export PATH={site_path}:$PATH; {cmk_command}"
    started = time.monotonic()
    debug(f"run_site_cmd start: site={site} timeout={timeout}s cmd={cmk_command}")

    current_user = ""
    try:
        current_user = pwd.getpwuid(os.geteuid()).pw_name
    except Exception:
        current_user = ""

    if current_user == site:
        result = subprocess.run(
            ["sh", "-lc", shell_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=timeout,
            check=False,
        )
    else:
        result = subprocess.run(
            ["su", "-", site, "-c", shell_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=timeout,
            check=False,
        )

    elapsed = time.monotonic() - started
    debug(
        f"run_site_cmd end: rc={result.returncode} elapsed={elapsed:.2f}s cmd={cmk_command}"
    )
    return result


def default_state_file(site: str) -> Path:
    return Path(f"/opt/omd/sites/{site}/var/check_mk/autodiscovery_local_state.json")


def load_state(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}

    normalized: Dict[str, Dict[str, Any]] = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for host_raw, value in raw.items():
                host = str(host_raw)

                if isinstance(value, dict):
                    host_hash = str(value.get("hash", ""))
                    services_raw = value.get("services", [])
                    if isinstance(services_raw, list):
                        services = sorted({str(service).strip() for service in services_raw if str(service).strip()})
                    else:
                        services = []
                else:
                    host_hash = str(value)
                    services = []

                normalized[host] = {"hash": host_hash, "services": services}
    except Exception:
        return {}

    return normalized


def save_state(path: Path, state: Dict[str, Dict[str, Any]]) -> None:
    serializable: Dict[str, Dict[str, Any]] = {}
    for host, data in state.items():
        host_hash = str(data.get("hash", ""))
        services_raw = data.get("services", [])
        if isinstance(services_raw, list):
            services = sorted({str(service).strip() for service in services_raw if str(service).strip()})
        else:
            services = []

        serializable[str(host)] = {
            "hash": host_hash,
            "services": services,
        }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(serializable, indent=2, sort_keys=True), encoding="utf-8")


def get_host_hash(state: Dict[str, Dict[str, Any]], host: str) -> str:
    data = state.get(host, {})
    return str(data.get("hash", ""))


def get_host_services(state: Dict[str, Dict[str, Any]], host: str) -> List[str]:
    data = state.get(host, {})
    services_raw = data.get("services", [])
    if not isinstance(services_raw, list):
        return []
    return sorted({str(service).strip() for service in services_raw if str(service).strip()})


def set_host_state(state: Dict[str, Dict[str, Any]], host: str, host_hash: str, services: List[str]) -> None:
    state[host] = {
        "hash": str(host_hash),
        "services": sorted({str(service).strip() for service in services if str(service).strip()}),
    }


def parse_hosts(site: str, hosts_arg: str) -> List[str]:
    if hosts_arg.strip():
        return sorted({h.strip() for h in hosts_arg.split(",") if h.strip()})

    for cmd in ("cmk --list-hosts", "cmk -l"):
        result = run_site_cmd(site, cmd, timeout=120)
        if result.returncode != 0:
            warn(f"Host list command failed: '{cmd}' rc={result.returncode}")
            continue

        hosts = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        if hosts:
            log(f"Host list retrieved via '{cmd}' ({len(hosts)} host)")
            return sorted(set(hosts))

    raise RuntimeError("unable to retrieve hosts with both 'cmk --list-hosts' and 'cmk -l'")


def extract_local_services(agent_output: str) -> List[str]:
    in_local = False
    services: Set[str] = set()

    for raw in agent_output.splitlines():
        line = raw.strip()

        if line.startswith("<<<"):
            in_local = line.startswith("<<<local")
            continue

        if not in_local or not line:
            continue

        if line.startswith("cached("):
            closing_idx = line.find(")")
            if closing_idx == -1:
                continue
            line = line[closing_idx + 1 :].strip()
            if not line:
                continue

        first = line[0]
        if first not in "0123":
            continue

        parts = line.split(None, 1)
        if len(parts) < 2:
            continue

        rest = parts[1]
        service_name = ""
        try:
            tokens = shlex.split(rest, posix=True)
            if tokens:
                service_name = tokens[0].strip()
        except Exception:
            service_name = ""

        if not service_name:
            service_name = rest.split(" - ", 1)[0].strip().strip('"')

        if service_name:
            services.add(service_name)

    return sorted(services)


def services_hash(services: List[str]) -> str:
    payload = "\n".join(services)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def discovered_local_services(site: str, host: str) -> Set[str]:
    cmd = f"cmk -D {shlex.quote(host)}"
    result = run_site_cmd(site, cmd, timeout=300)
    if result.returncode != 0:
        debug(f"cmk -D failed for {host} rc={result.returncode}")
        return set()

    discovered: Set[str] = set()
    for raw in (result.stdout or "").splitlines():
        line = raw.rstrip()
        match = re.match(r"^\s*local\s+(.+?)\s+\{", line)
        if not match:
            continue
        service_name = match.group(1).strip()
        if service_name:
            discovered.add(service_name)

    debug(f"Discovered local services on {host}: count={len(discovered)}")

    return discovered


def discover_hosts(site: str, hosts: List[str], dry_run: bool, detect_plugins: str) -> bool:
    if not hosts:
        return True

    plugins_opt = ""
    if detect_plugins.strip():
        plugins_opt = f" --detect-plugins {shlex.quote(detect_plugins.strip())}"

    hosts_part = " ".join(shlex.quote(host) for host in hosts)
    cmd = f"cmk -IIv{plugins_opt} {hosts_part}"

    if dry_run:
        log(f"[DRY-RUN] {cmd}")
        return True

    timeout = min(1800, 240 + (120 * len(hosts)))
    result = run_site_cmd(site, cmd, timeout=timeout)
    if result.returncode == 0:
        for host in hosts:
            log(f"Discovery OK: {host}")
        log("Discovery completata")
        return True

    warn(f"Discovery/Activate FAIL (rc={result.returncode}) hosts={','.join(hosts)}")
    if result.stdout:
        warn(result.stdout.strip())
    return False


def apply_changes(site: str, dry_run: bool) -> bool:
    cmd = "cmk -O"
    if dry_run:
        log(f"[DRY-RUN] {cmd}")
        return True

    result = run_site_cmd(site, cmd, timeout=900)
    if result.returncode == 0:
        log("Activate changes OK")
        return True

    warn(f"Activate changes FAIL (rc={result.returncode})")
    if result.stdout:
        warn(result.stdout.strip())
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trigger discovery CheckMK su cambi local checks")
    parser.add_argument("--site", default="monitoring", help="Nome site OMD")
    parser.add_argument("--hosts", default="", help="Lista host separati da virgola")
    parser.add_argument("--state-file", default="", help="Path file stato JSON")
    parser.add_argument("--dry-run", action="store_true", help="Simula comandi senza eseguirli")
    parser.add_argument(
        "--initialize-state",
        action="store_true",
        help="Inizializza stato corrente senza discovery/reload",
    )
    parser.add_argument(
        "--agent-timeout",
        type=int,
        default=90,
        help="Timeout base in secondi per singolo 'cmk -d <host>' (default: 90, effettivo minimo: 60)",
    )
    parser.add_argument(
        "--detect-plugins",
        default="local",
        help="Plugin discovery target (default: local). Vuoto = tutti i plugin.",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Esegue anche 'cmk -O' a fine ciclo se ci sono discovery riuscite.",
    )
    parser.add_argument(
        "--lock-file",
        default="/tmp/cmk-local-discovery-trigger.lock",
        help="Path lock file per evitare esecuzioni sovrapposte.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Abilita log debug dettagliati per troubleshooting.",
    )
    return parser.parse_args()


def acquire_lock(lock_file: str):
    primary = Path(lock_file)
    fallback = Path(f"/tmp/cmk-local-discovery-trigger.{os.geteuid()}.lock")
    candidates = [primary]
    if fallback != primary:
        candidates.append(fallback)

    for candidate in candidates:
        try:
            handle = open(candidate, "a+", encoding="utf-8")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            handle.seek(0)
            handle.truncate(0)
            handle.write(f"pid={os.getpid()} started={datetime.now().isoformat()}\n")
            handle.flush()
            return handle, str(candidate)
        except BlockingIOError:
            raise
        except PermissionError:
            continue

    raise PermissionError(f"Impossibile scrivere lock file: {primary}")


def main() -> int:
    global DEBUG
    args = parse_args()
    DEBUG = args.debug

    lock_handle = None
    try:
        lock_handle, active_lock = acquire_lock(args.lock_file)
    except BlockingIOError:
        warn(f"Altra esecuzione in corso (lock: {args.lock_file}), skip")
        return 0
    except PermissionError as exc:
        warn(str(exc))
        return 0

    state_path = Path(args.state_file) if args.state_file else default_state_file(args.site)
    state = load_state(state_path)

    log(f"cmk-local-discovery-trigger.py v{VERSION}")
    log(f"Server autoheal log: {LOG_FILE}")
    log(f"Debug mode: {'enabled' if DEBUG else 'disabled'}")
    log(f"Site: {args.site}")
    log(f"State: {state_path}")
    log(f"Lock: {active_lock}")
    debug(f"Args: hosts='{args.hosts}', detect_plugins='{args.detect_plugins}', activate={args.activate}, initialize_state={args.initialize_state}")

    try:
        hosts = parse_hosts(args.site, args.hosts)
    except Exception as exc:
        error(f"Impossibile ottenere host list: {exc}")
        return 1

    if not hosts:
        warn("Nessun host trovato")
        return 0

    log(f"Host totali: {len(hosts)}")
    effective_probe_timeout = max(args.agent_timeout, 60)
    log(
        f"Timeout probe cmk effettivo: {effective_probe_timeout}s (requested: {args.agent_timeout}s)"
    )

    changed_hosts: List[str] = []
    successful_discovery = 0
    pending_discovery: List[str] = []
    vanished_hosts: List[str] = []

    for host in hosts:
        log(f"Probe host: {host}")
        host_quoted = shlex.quote(host)
        probe_cmd = f"timeout -k 15 {effective_probe_timeout}s cmk -d {host_quoted}"
        try:
            result = run_site_cmd(args.site, probe_cmd, timeout=effective_probe_timeout + 60)
        except subprocess.TimeoutExpired:
            warn(f"cmk -d timeout per {host} (> {effective_probe_timeout}s), skip")
            continue

        if result.returncode == 124:
            warn(f"cmk -d timeout (rc=124) per {host} dopo {effective_probe_timeout}s, skip")
            continue

        if result.returncode != 0:
            warn(f"cmk -d fallito per {host} (rc={result.returncode}), skip")
            continue

        log(f"Probe OK: {host} (rc={result.returncode})")

        services = extract_local_services(result.stdout or "")
        current_hash = services_hash(services)
        previous_hash = get_host_hash(state, host)
        previous_services = get_host_services(state, host)
        new_services = sorted(set(services) - set(previous_services))
        vanished_services = sorted(set(previous_services) - set(services))

        if new_services:
            log(f"Nuovi servizi local su {host}: {', '.join(new_services[:10])}{' ...' if len(new_services) > 10 else ''}")
        if vanished_services:
            warn(
                f"Servizi local vanished su {host}: {', '.join(vanished_services[:10])}{' ...' if len(vanished_services) > 10 else ''}"
            )
            vanished_hosts.append(host)

        debug(
            f"Host={host} local_count={len(services)} prev_hash={(previous_hash[:12] if previous_hash else 'none')} curr_hash={current_hash[:12]}"
        )
        if services:
            debug(f"Host={host} local sample: {', '.join(services[:6])}{' ...' if len(services) > 6 else ''}")
        else:
            warn(f"Nessun local service estratto da cmk -d per {host} (payload local vuoto)")

        if previous_hash != current_hash:
            changed_hosts.append(host)
            log(
                f"Cambio local services: {host} (prev={'yes' if previous_hash else 'no'}, now={len(services)}, prev_hash={(previous_hash[:12] if previous_hash else 'none')}, curr_hash={current_hash[:12]})"
            )

            if args.initialize_state:
                set_host_state(state, host, current_hash, services)
                continue

            pending_discovery.append(host)
        else:
            log(f"Nessun cambio: {host}")
            set_host_state(state, host, current_hash, services)

            if vanished_services and not args.initialize_state:
                warn(
                    f"Vanished rilevati su {host} con hash invariato: forzo discovery per rimozione servizi spariti"
                )
                pending_discovery.append(host)

            if services:
                discovered = discovered_local_services(args.site, host)
                missing_services = sorted(set(services) - discovered)
                debug(
                    f"Host={host} discovered_count={len(discovered)} missing_count={len(missing_services)}"
                )
                if missing_services:
                    warn(
                        f"Inventory mismatch su {host}: {len(missing_services)} local service mancanti in discovery, forzo rediscovery"
                    )
                    warn(f"Missing: {', '.join(missing_services[:8])}{' ...' if len(missing_services) > 8 else ''}")
                    pending_discovery.append(host)

    if args.initialize_state:
        save_state(state_path, state)
        log(f"Stato inizializzato per {len(state)} host")
        return 0

    unique_pending = list(dict.fromkeys(pending_discovery))
    unique_vanished_hosts = list(dict.fromkeys(vanished_hosts))
    if unique_pending:
        log(f"Pending discovery: {len(unique_pending)} host")
        debug(f"Pending discovery hosts: {', '.join(unique_pending)}")
        if discover_hosts(args.site, unique_pending, args.dry_run, args.detect_plugins):
            successful_discovery = len(unique_pending)
            for host in unique_pending:
                probe_cmd = f"timeout -k 15 {effective_probe_timeout}s cmk -d {shlex.quote(host)}"
                try:
                    refresh = run_site_cmd(args.site, probe_cmd, timeout=effective_probe_timeout + 60)
                    if refresh.returncode == 0:
                        refreshed_services = extract_local_services(refresh.stdout or "")
                        refreshed_hash = services_hash(refreshed_services)
                        set_host_state(state, host, refreshed_hash, refreshed_services)
                        debug(f"State refreshed: {host} hash={refreshed_hash[:12]} services={len(refreshed_services)}")
                    else:
                        warn(f"State refresh fallito per {host} (rc={refresh.returncode})")
                except Exception:
                    warn(f"State refresh exception per {host}")
    else:
        log("Nessuna discovery richiesta")

    if successful_discovery > 0:
        force_apply_for_vanished = bool(unique_vanished_hosts)
        should_apply = args.activate or force_apply_for_vanished
        if force_apply_for_vanished:
            warn(
                f"Vanished rilevati su {len(unique_vanished_hosts)} host: forzo apply changes dopo discovery"
            )
        if should_apply:
            apply_changes(args.site, args.dry_run)
        else:
            log("Activate disabilitato (skip cmk -O): nessun vanished rilevato")
    else:
        log("Nessuna discovery riuscita: skip cmk -O")

    save_state(state_path, state)
    log(
        f"Completato: changed={len(changed_hosts)}, vanished={len(unique_vanished_hosts)}, discovery_ok={successful_discovery}, unchanged={len(hosts) - len(changed_hosts)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
