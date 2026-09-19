#!/usr/bin/env python3
"""check_ns8_container_health.py - CheckMK Local Check for NS8 container health

Monitor NS8 instance containers (runagent + podman):
- count total/running/problematic containers
- report non-running containers in CRITICAL

Version: 1.0.0"""

import subprocess
import sys
from typing import List, Tuple

VERSION = "1.2.0"
SERVICE = "NS8.Containers"
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
        return 1, "", "Command timeout"
    except FileNotFoundError:
        return 127, "", "Command not found"
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


def get_instance_containers(instance: str) -> List[Tuple[str, str]]:
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

    containers = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        name, status = line.split("|", 1)
        containers.append((name.strip(), status.strip()))
    return containers


def status_is_running(status: str) -> bool:
    return status.startswith("Up")


def main() -> int:
    if run_command(["which", "runagent"])[0] != 0:
        print("3 {} - UNKNOWN: runagent not found".format(SERVICE))
        return 0

    instances = get_instances()
    if not instances:
        print("3 {} - UNKNOWN: no NS8 instance found".format(SERVICE))
        return 0

    total = 0
    running = 0
    problems: List[str] = []

    for instance in instances:
        containers = get_instance_containers(instance)
        if not containers:
            problems.append("{}:no-containers".format(instance))
            continue

        for container_name, container_status in containers:
            total += 1
            if status_is_running(container_status):
                running += 1
            else:
                problems.append("{}:{}({})".format(instance, container_name, container_status))

    problem_count = len(problems)

    if problem_count > 0:
        detail = ", ".join(problems[:8])
        if problem_count > 8:
            detail = "{}, ... (+{} altri)".format(detail, problem_count - 8)
        print(
            "2 {} - CRIT: total={} running={} problem={} | {}".format(
                SERVICE, total, running, problem_count, detail
            )
        )
    else:
        print("0 {} - OK: total={} running={} problem=0".format(SERVICE, total, running))

    return 0


if __name__ == "__main__":
    sys.exit(main())
