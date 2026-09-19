#!/usr/bin/env python3
"""check_ns8_container_inventory.py - NS8 container inventory for CheckMK

Version: 1.0.0"""

import subprocess
import sys
from typing import List, Tuple

VERSION = "1.2.0"
SERVICE = "NS8.Container.Inventory"
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"


def run_command(cmd: List[str], timeout: int = 30) -> Tuple[int, str, str]:
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", "timeout"
    except FileNotFoundError:
        return 127, "", "command not found"
    except Exception as exc:
        return 1, "", str(exc)


def get_local_node_id() -> str:
    """Reads this node's own ID from NODE_AGENT_ENV (AGENT_ID=node/<id>)."""
    try:
        with open(NODE_AGENT_ENV, encoding="utf-8") as f:
            for line in f:
                if line.startswith("AGENT_ID=node/"):
                    return line.strip().split("/", 1)[1]
    except OSError:
        pass
    return ""


def get_instances() -> List[str]:
    """Enumerates module instances actually installed on this node.

    runagent -l only ever lists the cluster/node meta-agents, never real
    module IDs (e.g. traefik1, samba1) - it is not a module inventory
    command. api-cli run list-installed-modules would be the natural
    replacement, but cluster-scoped api-cli actions only work from the
    cluster leader node and fail with an AuthenticationError on workers -
    redis-cli reading cluster/module_node directly works identically on
    every node, leader or worker, with no login required."""
    code, out, _ = run_command(["redis-cli", "--raw", "HGETALL", "cluster/module_node"])
    if code != 0 or not out:
        return []

    lines = out.splitlines()
    node_id = get_local_node_id()
    instances = []
    for i in range(0, len(lines) - 1, 2):
        module_id, module_node = lines[i], lines[i + 1]
        if not node_id or module_node == node_id:
            instances.append(module_id)
    return instances


def get_container_list(instance: str) -> List[Tuple[str, str]]:
    code, out, _ = run_command(
        [
            "runagent",
            "-m",
            instance,
            "podman",
            "ps",
            "-a",
            "--format",
            "{{.Names}}|{{.Status}}",
        ]
    )
    if code != 0 or not out:
        return []

    containers: List[Tuple[str, str]] = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        name, status = line.split("|", 1)
        containers.append((name.strip(), status.strip()))
    return containers


def is_running(status: str) -> bool:
    return status.startswith("Up")


def main() -> int:
    if run_command(["which", "runagent"])[0] != 0:
        print(f"3 {SERVICE} - UNKNOWN: runagent not found")
        return 0

    instances = get_instances()
    if not instances:
        print(f"3 {SERVICE} - UNKNOWN: no NS8 instance found")
        return 0

    total = 0
    running = 0
    stopped = 0
    names: List[str] = []

    for instance in instances:
        for container_name, container_status in get_container_list(instance):
            total += 1
            names.append(f"{instance}:{container_name}")
            if is_running(container_status):
                running += 1
            else:
                stopped += 1

    if total == 0:
        print(f"1 {SERVICE} - WARNING: no containers found")
        return 0

    preview = ", ".join(names[:8])
    if len(names) > 8:
        preview = f"{preview}, ... (+{len(names) - 8} more)"

    state = 0 if stopped == 0 else 1
    state_label = "OK" if state == 0 else "WARNING"

    print(
        f"{state} {SERVICE} - {state_label}: total={total} running={running} stopped={stopped} | total={total} running={running} stopped={stopped}; {preview}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
