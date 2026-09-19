#!/usr/bin/env python3
"""check_ns8_container_resources.py - NS8 container resources for CheckMK

Version: 1.1.0"""

import subprocess
import sys
from typing import List, Tuple

VERSION = "1.3.0"
SERVICE = "NS8.Container.Resources"
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"
CPU_WARN = 80.0
CPU_CRIT = 95.0
MEM_WARN = 80.0
MEM_CRIT = 95.0


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
    result = []
    for i in range(0, len(lines) - 1, 2):
        module_id, module_node = lines[i], lines[i + 1]
        if not node_id or module_node == node_id:
            result.append(module_id)
    return result


def parse_percent(value: str) -> float:
    clean = value.replace("%", "").replace(",", ".").strip()
    try:
        return float(clean)
    except ValueError:
        return 0.0


def get_stats(instance: str) -> List[Tuple[str, float, float, str]]:
    code, out, _ = run_command(
        [
            "runagent",
            "-m",
            instance,
            "podman",
            "stats",
            "--no-stream",
            "--format",
            "{{.Name}}|{{.CPUPerc}}|{{.MemPerc}}|{{.MemUsage}}",
        ]
    )
    if code != 0 or not out:
        return []

    result: List[Tuple[str, float, float, str]] = []
    for line in out.splitlines():
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        name = parts[0].strip()
        cpu = parse_percent(parts[1])
        mem = parse_percent(parts[2])
        usage = parts[3].strip()
        result.append((name, cpu, mem, usage))
    return result


def state_for(cpu: float, mem: float) -> int:
    if cpu >= CPU_CRIT or mem >= MEM_CRIT:
        return 2
    if cpu >= CPU_WARN or mem >= MEM_WARN:
        return 1
    return 0


def label_for(state: int) -> str:
    if state == 2:
        return "CRIT"
    if state == 1:
        return "WARN"
    return "OK"


def top_entries(entries: List[Tuple[str, float]], size: int = 3) -> str:
    if not entries:
        return "n/a"
    ordered = sorted(entries, key=lambda item: item[1], reverse=True)[:size]
    return ", ".join(f"{name}:{value:.1f}%" for name, value in ordered)


def main() -> int:
    if run_command(["which", "runagent"])[0] != 0:
        print(f"3 {SERVICE} - UNKNOWN: runagent not found")
        return 0

    instances = get_instances()
    if not instances:
        print(f"3 {SERVICE} - UNKNOWN: no NS8 instance found")
        return 0

    total = 0
    warn_count = 0
    crit_count = 0
    max_cpu = 0.0
    max_mem = 0.0
    cpu_items: List[Tuple[str, float]] = []
    mem_items: List[Tuple[str, float]] = []

    for instance in instances:
        stats = get_stats(instance)
        for container_name, cpu, mem, usage in stats:
            total += 1
            state = state_for(cpu, mem)
            if state == 2:
                crit_count += 1
            elif state == 1:
                warn_count += 1

            if cpu > max_cpu:
                max_cpu = cpu
            if mem > max_mem:
                max_mem = mem

            cpu_items.append((f"{instance}/{container_name}", cpu))
            mem_items.append((f"{instance}/{container_name}", mem))

    if total == 0:
        print(f"1 {SERVICE} - WARNING: no container metrics available")
        return 0

    overall_state = 2 if crit_count > 0 else 1 if warn_count > 0 else 0
    label = label_for(overall_state)

    top_cpu = top_entries(cpu_items)
    top_mem = top_entries(mem_items)

    print(
        f"{overall_state} {SERVICE} - {label}: total={total} warn={warn_count} crit={crit_count} top_cpu=[{top_cpu}] top_mem=[{top_mem}] | max_cpu={max_cpu:.2f};{CPU_WARN};{CPU_CRIT};0;100 max_mem={max_mem:.2f};{MEM_WARN};{MEM_CRIT};0;100"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
