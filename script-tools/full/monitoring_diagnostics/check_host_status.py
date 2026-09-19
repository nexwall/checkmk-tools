#!/usr/bin/env python3
"""check_host_status.py - CheckMK/Nagios plugin: Host UP/DOWN via multi-probe confidence scoring

Replaces check_icmp with a multi-layer approach that performs ALL checks
in parallel and calculates a confidence score before issuing the verdict.

It does NOT stop at the first result — it runs everything to avoid false positives/negatives
caused by ICMP firewalls, closed ports, or momentary flapping.

Probes run in parallel:
  - ICMP Ping (3x, 1s timeout) → responds → strong UP indicator
  - TCP on configurable ports → open/ref.    → UP indicator
  - ARP table lookup → present → host seen on L2
  (traceroute disabled by default: too slow for continuous checking)

"HOST DOWN" score (0-100):
  Ping 100% loss → +25 Ping responds → -50 (host definitely UP)
  TCP port timeout → +10/15/20 per port → -20 (host responds on TCP)
  ARP absent → +15 ARP present → -10
  DNS resolves → +5 DNS fails → -10

Verdict thresholds:
  score >= warn_threshold (default 60) → WARNING (probably offline / uncertain)
  score >= crit_threshold (default 90) → CRITICAL (offline confirmed)
  score < warn_threshold → OK (host active)

Exit codes (Nagios/CheckMK standard):
  0 = OK (host active)
  1 = WARNING (anomalous, uncertain behavior)
  2 = CRITICAL (confirmed offline host)
  3 = UNKNOWN (plugin error)

Deploy on CheckMK server:
  cp check_host_status.py /omd/sites/monitoring/local/lib/nagios/plugins/check_host_status
  chmod +x /omd/sites/monitoring/local/lib/nagios/plugins/check_host_status

WATO (Host Check Command) configuration:
  Setup → Hosts → Host Check Command → "Use a custom check plugin"
  Plugin: check_host_status
  Arguments: -H $HOSTADDRESS$

Host types (--type):
  server → Server with CheckMK agent. Port 6556: if it answers → ON sure (immediate early exit).
  client → Client/workstation with CheckMK agent. Same server logic.
  switch → Switch/Router. Ping + ARP high weight (no CMK agent).
  generic → Default, backward compatible (balanced weights).

WATO configuration for folders:
  Folder Servers: -H $HOSTADDRESS$ --type server
  Folder Clients: -H $HOSTADDRESS$ --type client
  Folder Network: -H $HOSTADDRESS$ --type switch
  Default (all): -H $HOSTADDRESS$

  Additional options:
  -H $HOSTADDRESS$ --type server --no-arp # Server on different L2
  -H $HOSTADDRESS$ --warn 50 --crit 80 # Custom thresholds

Version: 2.0.0"""

import argparse
import concurrent.futures
import errno
import re
import socket
import subprocess
import sys
import time
from typing import Dict, List, NamedTuple, Optional, Tuple

VERSION = "2.4.0"
SCRIPT_NAME = "check_host_status"

# Nagios exit codes
OK       = 0
WARNING  = 1
CRITICAL = 2
UNKNOWN  = 3

# Readable port names
PORT_NAMES = {
    22:   "SSH",
    6556: "CMK",
    443:  "HTTPS",
    80:   "HTTP",
    3389: "RDP",
    8080: "HTTP-alt",
    5985: "WinRM",
    2222: "SSH-alt",
}

# "Host DOWN" score weights
W_PING_DOWN    = 25   # Ping 100% loss        → host probabilmente offline
W_PING_UP      = -50  # Ping risponde          → host sicuramente attivo
W_TCP_TIMEOUT  = {    # Per porta: timeout     → porta non risponde
    6556: 20,
    22:   15,
    443:  10,
    80:    8,
    3389: 10,
    8080:  5,
    5985:  8,
    2222:  8,
}
W_TCP_DEFAULT  = 8    # Peso default per porte non in lista
W_TCP_UP       = -20  # Porta aperta/rifiutata → host attivo
W_ARP_MISSING  = 15   # ARP assente            → host non visto su L2
W_ARP_PRESENT  = -10  # ARP presente           → host visto di recente
W_DNS_OK       = 5    # DNS risolve            → non è errore DNS
W_DNS_FAIL     = -10  # DNS non risolve        → forse problema DNS, non host

# ─── Profiles by host type ────────────────────────── ───────────────────────────

TYPE_PROFILES: Dict[str, dict] = {
    "server": {
        "description":      "Server con agente CheckMK (porta 6556 prioritaria)",
        "ports":            [6556, 22, 443, 80],
        "skip_arp":         True,   # monitoring su VPS: ARP non raggiunge host cross-VLAN
        "early_exit_ports": [6556],   # se risponde → acceso, score=0 immediato
        "w_ping_up":        -70,
        "w_ping_down":       30,
        "w_tcp_up":         -80,
        "w_tcp_timeout":    {6556: 45, 22: 15, 443: 8, 80: 5},
        "w_arp_present":    -25,
        "w_arp_missing":     20,
    },
    "client": {
        "description":      "Client/workstation con agente CheckMK (porta 6556 prioritaria)",
        "ports":            [6556, 3389, 22],
        "skip_arp":         True,   # monitoring su VPS: ARP non raggiunge host cross-VLAN
        "early_exit_ports": [6556],
        "w_ping_up":        -70,
        "w_ping_down":       30,
        "w_tcp_up":         -80,
        "w_tcp_timeout":    {6556: 45, 3389: 12, 22: 10},
        "w_arp_present":    -25,
        "w_arp_missing":     20,
    },
    "switch": {
        "description":      "Switch/Router gestito (ping prioritario, no agente CMK, no ARP cross-VLAN)",
        "ports":            [22, 443, 80],
        "skip_arp":         True,   # monitoring su VPS: ARP non raggiunge host cross-VLAN
        "early_exit_ports": [],
        "w_ping_up":        -80,    # switch risponde ping = certamente acceso
        "w_ping_down":       75,    # senza ARP, ping porta peso maggiore → 75+8+5+5=93% CRIT
        "w_tcp_up":         -20,
        "w_tcp_timeout":    {22: 8, 443: 5, 80: 5},
        "w_arp_present":    -30,
        "w_arp_missing":     25,
    },
    "generic": {
        "description":      "Generico (default, backward compat)",
        "ports":            [22, 6556, 443, 80],
        "skip_arp":         True,   # monitoring su VPS: ARP non raggiunge host cross-VLAN
        "early_exit_ports": [],
        "w_ping_down":       40,    # senza ARP, ping porta peso maggiore → 40+15+20+10+8=93% CRIT
        # other weights use global W_*
    },
}

# ─── Probe result structure ──────────────────────── ────────────────────────

class ProbeResult(NamedTuple):
    name:   str    # identificatore breve
    status: str    # "up" / "down" / "unknown"
    score:  int    # contributo al punteggio finale
    msg:    str    # dettaglio per output


# ─── Probe singole ───────────────────────────────────────────────────────────

def probe_dns(host: str) -> Tuple[ProbeResult, Optional[str]]:
    """Risolve hostname. Ritorna (result, ip_risolto_o_None)."""
    try:
        ip = socket.gethostbyname(host)
        return ProbeResult("dns", "up", W_DNS_OK, f"→ {ip}"), ip
    except socket.gaierror as e:
        return ProbeResult("dns", "unknown", W_DNS_FAIL, f"NXDOMAIN: {e}"), None


def probe_ping(ip: str, count: int = 3, timeout: int = 1,
               w_up: int = W_PING_UP, w_down: int = W_PING_DOWN) -> ProbeResult:
    """ICMP ping multiplo. Analizza packet loss."""
    try:
        r = subprocess.run(
            ["ping", "-c", str(count), "-W", str(timeout), ip],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=count * (timeout + 1) + 3
        )
        out = r.stdout.decode("utf-8", errors="replace")

        m_loss = re.search(r"(\d+)%\s+packet loss", out)
        loss = int(m_loss.group(1)) if m_loss else 100

        if loss == 0:
            m_rtt = re.search(r"rtt \S+ = [\d.]+/([\d.]+)/", out)
            rtt = f"{float(m_rtt.group(1)):.1f}ms" if m_rtt else "ok"
            return ProbeResult("ping", "up", w_up, f"risponde ({rtt})")
        elif loss == 100:
            return ProbeResult("ping", "down", w_down, "100% packet loss")
        else:
            return ProbeResult("ping", "unknown", 0, f"{loss}% loss (instabile)")

    except subprocess.TimeoutExpired:
        return ProbeResult("ping", "down", w_down, "timeout")
    except OSError:
        return ProbeResult("ping", "unknown", 0, "ping non disponibile")
    except Exception as e:
        return ProbeResult("ping", "unknown", 0, str(e))


def probe_tcp(ip: str, port: int, timeout: float = 2.0,
              w_up: int = W_TCP_UP, w_timeout: Optional[int] = None) -> ProbeResult:
    """Single port TCP test."""
    name = f"tcp/{PORT_NAMES.get(port, str(port))}"
    weight_down = w_timeout if w_timeout is not None else W_TCP_TIMEOUT.get(port, W_TCP_DEFAULT)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        err = sock.connect_ex((ip, port))
        sock.close()

        if err == 0:
            return ProbeResult(name, "up", w_up, "aperta")
        elif err == errno.ECONNREFUSED:
            # Host active, service not listening on this port
            return ProbeResult(name, "up", w_up, "rifiutata (host attivo)")
        else:
            return ProbeResult(name, "down", weight_down, f"timeout (errno {err})")

    except socket.timeout:
        return ProbeResult(name, "down", weight_down, "timeout")
    except Exception as e:
        return ProbeResult(name, "unknown", 0, str(e))


def probe_arp(ip: str, w_present: int = W_ARP_PRESENT, w_missing: int = W_ARP_MISSING) -> ProbeResult:
    """Check presence of ARP entries in the local table."""
    try:
        r = subprocess.run(
            ["arp", "-n", ip],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5
        )
        out = r.stdout.decode("utf-8", errors="replace")

        if r.returncode != 0 or "no entry" in out.lower():
            return ProbeResult("arp", "down", w_missing, "nessuna entry ARP")
        elif "(incomplete)" in out:
            return ProbeResult("arp", "down", w_missing, "ARP incompleto (no risposta L2)")
        else:
            mac_m = re.search(r"([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})", out)
            mac = mac_m.group(1) if mac_m else "n/a"
            return ProbeResult("arp", "up", w_present, f"MAC {mac}")

    except OSError:
        return ProbeResult("arp", "unknown", 0, "arp non disponibile")
    except Exception as e:
        return ProbeResult("arp", "unknown", 0, str(e))


# ─── Engine principale ────────────────────────────────────────────────────────

def run_all_probes(
    host: str,
    ports: List[int],
    skip_arp: bool,
    tcp_timeout: float,
    profile: Optional[dict] = None,
) -> Tuple[int, List[ProbeResult]]:
    """Runs DNS + all probes in parallel where possible.

    If the profile includes early_exit_ports, test those ports first:
    if they reply → host switched on with certainty (score=0, immediate return).

    Returns:
        (score_0_100, list_ProbeResult)"""
    if profile is None:
        profile = TYPE_PROFILES["generic"]

    results: List[ProbeResult] = []

    # Weights from profile (fallback to global values ​​if not present)
    w_ping_up   = profile.get("w_ping_up",    W_PING_UP)
    w_ping_down = profile.get("w_ping_down",  W_PING_DOWN)
    w_tcp_up    = profile.get("w_tcp_up",     W_TCP_UP)
    w_arp_pres  = profile.get("w_arp_present", W_ARP_PRESENT)
    w_arp_miss  = profile.get("w_arp_missing", W_ARP_MISSING)
    w_tcp_t     = profile.get("w_tcp_timeout", {})  # per-porta overrides

    # ── 1. DNS (blocking: IP is needed for everything else) ──
    dns_result, ip = probe_dns(host)
    results.append(dns_result)

    if ip is None:
        ip = host

    # ── 2. Early exit (server/client): port 6556 responds → ON sure ──
    early_ports = profile.get("early_exit_ports", [])
    already_tested: set = set()
    for port in early_ports:
        wt = w_tcp_t.get(port, W_TCP_TIMEOUT.get(port, W_TCP_DEFAULT))
        r = probe_tcp(ip, port, tcp_timeout, w_up=w_tcp_up, w_timeout=wt)
        already_tested.add(port)
        if r.status == "up":
            # Turned on with certainty: early exit, score=0
            early_r = ProbeResult(r.name, "up", -100, r.msg + " [acceso]")
            return 0, [dns_result, early_r]
        else:
            results.append(r)

    # ── 3. All other probes in parallel ──
    ports_remaining = [p for p in ports if p not in already_tested]

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = []
        futures.append(ex.submit(probe_ping, ip, 3, 1, w_ping_up, w_ping_down))
        for port in ports_remaining:
            wt = w_tcp_t.get(port, W_TCP_TIMEOUT.get(port, W_TCP_DEFAULT))
            futures.append(ex.submit(probe_tcp, ip, port, tcp_timeout, w_tcp_up, wt))
        if not skip_arp:
            futures.append(ex.submit(probe_arp, ip, w_arp_pres, w_arp_miss))

        for f in concurrent.futures.as_completed(futures):
            try:
                results.append(f.result())
            except Exception as e:
                results.append(ProbeResult("unknown", "unknown", 0, str(e)))

    raw = sum(r.score for r in results)
    score = max(0, min(100, raw))
    return score, results


# ─── Nagios output formatting ─────────────────────── ───────────────────────

def format_output(
    host: str,
    score: int,
    results: List[ProbeResult],
    warn: int,
    crit: int,
) -> Tuple[int, str]:
    """Calculate exit code and compose the Nagios output string.

    Returns:
        (exit_code, output_string)"""
    # Verdetto
    if score >= crit:
        code   = CRITICAL
        status = "CRITICAL"
        verb   = f"SPENTO {score}%"
    elif score >= warn:
        code   = WARNING
        status = "WARNING"
        verb   = f"OFFLINE {score}% di problemi con connettività"
    else:
        code   = OK
        status = "OK"
        verb   = "attivo"

    # Probe summary for output text
    up_probes   = [r.name for r in results if r.status == "up"]
    down_probes = [r.name for r in results if r.status == "down"]

    # Performance data
    perf = f"confidence={score}%;{warn};{crit}"

    output = f"{status} - {host} {verb} | {perf}"
    return code, output


# ─── Entry point ─────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog=SCRIPT_NAME,
        description=f"CheckMK active check: host ACCESO/SPENTO via multi-probe confidence v{VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Priority host and probe types:
  server → early exit on port 6556 (CMK agent): if it responds → ON sure
  client → early exit on port 6556 (CMK agent): if it responds → ON sure
  switch → high weight ping: respond → ON; no response → probably OFF
  generic → balanced weights (backward compact, default)

Examples:
  check_host_status -H 192.0.2.100 --type server
  check_host_status -H 192.168.32.55 --type client
  check_host_status -H 192.168.1.1 --type switch
  check_host_status -H host.domain.it --type server --no-arp
  check_host_status -H 10.0.0.50 --warn 50 --crit 80

Thresholds (host confidence OFF):
  confidence >= --crit (default 90) → CRITICAL (host turned off)
  confidence >= --warn (default 60) → WARNING (uncertain)
  confidence < --warn → OK (host on)"""
    )
    parser.add_argument("-H", "--host", required=True,
                        help="Hostname o IP da controllare")
    parser.add_argument("--type", choices=list(TYPE_PROFILES.keys()), default="generic",
                        metavar="TYPE",
                        help=f"Tipo host: {', '.join(TYPE_PROFILES.keys())} (default: generic)")
    parser.add_argument("--ports", nargs="+", type=int, default=None,
                        help="Porte TCP da testare (default: dipende da --type)")
    parser.add_argument("--no-arp", action="store_true",
                        help="Salta ARP (host su segmento L2 diverso)")
    parser.add_argument("--timeout", type=float, default=2.0,
                        help="Timeout TCP per porta in secondi (default: 2)")
    parser.add_argument("--warn", type=int, default=60,
                        help="Soglia WARNING (default: 60)")
    parser.add_argument("--crit", type=int, default=90,
                        help="Soglia CRITICAL (default: 90)")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {VERSION}")
    args = parser.parse_args()

    if args.warn >= args.crit:
        print(f"UNKNOWN - --warn ({args.warn}) deve essere < --crit ({args.crit})")
        return UNKNOWN

    # Profile of the chosen host type
    profile = TYPE_PROFILES[args.type]

    # Ports: Use explicit ones or profile ones
    ports = args.ports if args.ports is not None else profile["ports"]

    # skip_arp: flag esplicito sovrascrive profilo
    skip_arp = args.no_arp or profile.get("skip_arp", False)

    score, results = run_all_probes(
        args.host,
        ports,
        skip_arp=skip_arp,
        tcp_timeout=args.timeout,
        profile=profile,
    )

    code, output = format_output(args.host, score, results, args.warn, args.crit)
    print(output)
    return code


if __name__ == "__main__":
    sys.exit(main())
