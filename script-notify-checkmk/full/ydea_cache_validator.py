#!/usr/bin/env python3
"""ydea_cache_validator.py - Cache Integrity Validator for Ydea Integration

Periodically checks if tickets in the local JSON cache actually exist on Ydea.
Removes "orphan" entries (tickets present in cache but deleted on Ydea).
Prevents cache misalignment issues.

Usage: python3 ydea_cache_validator.py [--dry-run]"""

import os
import sys
import json
import subprocess
import fcntl
import time
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

VERSION = "1.0.3"

# ===== CONFIG (Must match ydea_la.py) =====
YDEA_TOOLKIT_DIR = "/opt/ydea-toolkit"
YDEA_ENV_LA = f"{YDEA_TOOLKIT_DIR}/.env.la"
YDEA_ENV_AG = f"{YDEA_TOOLKIT_DIR}/.env.ag"
YDEA_CACHE_DIR = "/opt/ydea-toolkit/cache"
TICKET_CACHE = f"{YDEA_CACHE_DIR}/ydea_checkmk_tickets.json"
CACHE_LOCK = f"{YDEA_CACHE_DIR}/ydea_cache.lock"
YDEA_TOOLKIT_TIMEOUT = int(os.getenv("YDEA_TOOLKIT_TIMEOUT", "25"))

DRY_RUN = "--dry-run" in sys.argv


def resolve_toolkit_command() -> Optional[List[str]]:
    """Resolve ydea toolkit executable (prefer Python implementation)."""
    python_cmd = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else "python3"
    candidates: List[Tuple[str, List[str]]] = [
        (f"{YDEA_TOOLKIT_DIR}/ydea-toolkit.py", [python_cmd, f"{YDEA_TOOLKIT_DIR}/ydea-toolkit.py"]),
        (f"{YDEA_TOOLKIT_DIR}/rydea-toolkit.py", [python_cmd, f"{YDEA_TOOLKIT_DIR}/rydea-toolkit.py"]),
        (f"{YDEA_TOOLKIT_DIR}/ydea-toolkit.sh", [f"{YDEA_TOOLKIT_DIR}/ydea-toolkit.sh"]),
        (f"{YDEA_TOOLKIT_DIR}/rydea-toolkit.sh", [f"{YDEA_TOOLKIT_DIR}/rydea-toolkit.sh"]),
    ]
    for check_path, cmd in candidates:
        if os.path.exists(check_path):
            return cmd
    return None

def log(msg: str):
    """Log message to stderr."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", file=sys.stderr)

def toolkit_cmd(args: List[str], timeout: Optional[int] = None, env_file: Optional[str] = None) -> Tuple[int, str, str]:
    """Execute ydea-toolkit command with environment loaded from YDEA_ENV."""
    if timeout is None:
        timeout = YDEA_TOOLKIT_TIMEOUT
    
    # Load environment variables from selected env file
    env = os.environ.copy()
    selected_env = env_file or YDEA_ENV_LA
    if os.path.exists(selected_env):
        try:
            with open(selected_env, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        line = line.replace('export ', '', 1).strip()
                        key, value = line.split('=', 1)
                        value = value.strip().strip('"').strip("'")
                        value = value.replace('${HOME}', os.path.expanduser('~'))
                        env[key.strip()] = value
        except Exception as e:
            log(f"WARNING: Failed to load {selected_env}: {e}")
    
    base_cmd = resolve_toolkit_command()
    if not base_cmd:
        log(
            "ERROR: Ydea toolkit not found "
            f"(checked: {YDEA_TOOLKIT_DIR}/ydea-toolkit.py, {YDEA_TOOLKIT_DIR}/rydea-toolkit.py, "
            f"{YDEA_TOOLKIT_DIR}/ydea-toolkit.sh, {YDEA_TOOLKIT_DIR}/rydea-toolkit.sh)"
        )
        return 127, "", "Command not found"

    cmd = base_cmd + args
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=env
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        log(f"ERROR: toolkit command timeout after {timeout}s")
        return 124, "", "Timeout"
    except Exception as e:
        log(f"ERROR: toolkit command failed: {e}")
        return 1, "", str(e)

def atomic_cache_write(cache_file: str, content: str) -> bool:
    """Atomic cache write with flock."""
    if DRY_RUN:
        log("[DRY-RUN] Would write cache file")
        return True

    cache_path = Path(cache_file)
    cache_dir = cache_path.parent
    
    # Check permissions
    if not os.access(cache_dir, os.W_OK):
        try:
            # Try to fix permissions if we are root/owner
            os.chmod(cache_file, 0o666)
        except:
            pass
        if not os.access(cache_dir, os.W_OK):
            log(f"ERROR: No write permission on {cache_dir}")
            return False
    
    temp_file = f"{cache_file}.tmp.{os.getpid()}"
    lock_file = Path(CACHE_LOCK)
    
    try:
        lock_file.touch(mode=0o666, exist_ok=True)
        
        with open(lock_file, 'r') as lock_fd:
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except IOError:
                # Wait for lock
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            
            with open(temp_file, 'w') as f:
                f.write(content)
            os.chmod(temp_file, 0o666)
            os.sync()
            
            os.replace(temp_file, cache_file)
            os.chmod(cache_file, 0o666)
            os.sync()
            
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        
        return True
        
    except Exception as e:
        log(f"ERROR: atomic_cache_write failed: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False

def iter_env_files() -> List[Optional[str]]:
    """Return env files to test in order (LA then AG if present)."""
    envs: List[Optional[str]] = []
    if os.path.exists(YDEA_ENV_LA):
        envs.append(YDEA_ENV_LA)
    if os.path.exists(YDEA_ENV_AG) and YDEA_ENV_AG not in envs:
        envs.append(YDEA_ENV_AG)
    if not envs:
        envs.append(None)
    return envs


def is_not_found_output(output_lower: str) -> bool:
    """Detect not-found responses across Ydea toolkit variants.

    NOTE: 'non trovato' / 'ticket non trovato' are intentionally excluded.
    The toolkit resolves ticket existence via GET /tickets?limit=100 (list search),
    not via GET /tickets/{id}. A ticket outside the first 100 results returns
    'Ticket non trovato' even when it actually exists, causing false cache
    invalidation. Only explicit HTTP 404 responses are a reliable signal.
    """
    return (
        '404' in output_lower
        or 'not found' in output_lower
    )


def check_ticket_exists(ticket_id: int) -> bool:
    """Verify if ticket exists on Ydea API."""
    saw_not_found = False

    for env_file in iter_env_files():
        exitcode, stdout, stderr = toolkit_cmd(['get', str(ticket_id)], env_file=env_file)

        if exitcode == 0:
            return True

        output_lower = (stdout + stderr).lower()
        if is_not_found_output(output_lower):
            saw_not_found = True
            continue

        # Other errors (500, timeout, auth) -> assume exists to be safe
        source = env_file if env_file else "process-env"
        log(f"WARN: API check failed for #{ticket_id} via {source} (code {exitcode}), assuming valid.")
        return True

    return not saw_not_found

def main():
    log("Starting Ydea Cache Validation...")
    if DRY_RUN:
        log("Running in DRY-RUN mode (no changes will be applied)")

    if not os.path.exists(TICKET_CACHE):
        log("No cache file found. Exiting.")
        return

    try:
        with open(TICKET_CACHE, 'r') as f:
            data = json.load(f)
    except Exception as e:
        log(f"ERROR: Failed to load cache: {e}")
        return

    tickets_to_remove = []
    total_tickets = len(data)
    log(f"Found {total_tickets} tickets in cache.")

    for i, (key, info) in enumerate(data.items(), 1):
        ticket_id = info.get('ticket_id')
        if not ticket_id:
            continue
            
        print(f"[{i}/{total_tickets}] Checking {key} -> #{ticket_id}... ", end='', flush=True)
        
        if check_ticket_exists(ticket_id):
            print("OK")
        else:
            print("MISSING (404)")
            tickets_to_remove.append(key)
        
        # Small sleep to be nice to the API
        time.sleep(1)

    if not tickets_to_remove:
        log("Cache is healthy. No changes needed.")
        return

    log(f"Found {len(tickets_to_remove)} invalid tickets. Cleaning up...")
    
    for key in tickets_to_remove:
        log(f"Removing invalid entry: {key} (Ticket #{data[key]['ticket_id']})")
        del data[key]

    if atomic_cache_write(TICKET_CACHE, json.dumps(data)):
        log("Cache updated successfully.")
    else:
        log("Failed to update cache file.")

if __name__ == "__main__":
    main()
