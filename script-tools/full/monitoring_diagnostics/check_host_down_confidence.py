#!/usr/bin/env python3
"""check_host_down_confidence.py - OFFLINE HOST reliability diagnosis

Performs multi-layer diagnosis to determine with high confidence
if a host is really turned off vs. transient network problem.

Checks performed (with weight on the "offline" score):
  - DNS resolution +5% (if resolved, exclude DNS cause)
  - ICMP Ping (5x) +25% (if 100% loss)
  - TCP 6556 (CMK Agent) +20% (if timeout)
  - TCP 22 (SSH) +15% (if timeout)
  - TCP 443 (HTTPS) +10% (if timeout)
  - TCP 80 (HTTP) +5% (if timeout)
  - ARP entry absent +15% (only same L2 segment)
  - Traceroute timeout +10% (only if traceroute available)

If any check responds (port open/rejected, ping responds):
  the score is reduced → confidence drops towards 0%.

Interpretation thresholds:
  >= 90% → OFFLINE CONFIRMED
  >= 80% → Most likely offline
  >= 60% → Probably offline
  >= 30% → Uncertain (network vs host)
  < 30% → Host probably active

Exit codes:
  0 = host probably active (confidence < 60%)
  1 = uncertain / probably offline (60% ≤ confidence < threshold)
  2 = offline confirmed (confidence ≥ threshold)

Usage:
  python3 check_host_down_confidence.py 192.0.2.100
  python3 check_host_down_confidence.py ns8.dominio.it --ports 22 6556 443
  python3 check_host_down_confidence.py 10.0.0.50 --no-arp --no-traceroute
  python3 check_host_down_confidence.py 10.0.0.50 --checkmk

Version: 1.0.0"""

import subprocess
import socket
import sys
import re
import errno
import argparse
from typing import List, Tuple

VERSION = "1.0.0"
SCRIPT_NAME = "check_host_down_confidence"

# ─── Weights for each check ───────────────────────── ─────────────────────────

# Positive contributions (score += X → host probably offline)
PING_DOWN_WEIGHT    = 25   # Ping 100% loss
TCP_PORT_WEIGHTS    = {    # Timeout su porta TCP
    6556: 20,              # CheckMK agent
    22:   15,              # SSH
    443:  10,              # HTTPS
    80:    5,              # HTTP
    3389: 10,              # RDP (Windows)
    8080:  5,              # HTTP alternativo
}
DNS_OK_WEIGHT       = 5    # DNS risolve → non è un problema DNS
ARP_MISSING_WEIGHT  = 15   # ARP assente/incompleto → host non visto su L2
TRACE_TIMEOUT_WEIGHT = 10  # Traceroute: tutti * → destinazione irraggiungibile

# Penalty (score -= X → host probably active)
PING_UP_PENALTY     = -50  # Ping risponde → host sicuramente attivo
TCP_UP_PENALTY      = -20  # Porta aperta o rifiutata → host risponde
DNS_FAIL_PENALTY    = -10  # DNS non risolve → forse è problema DNS, non host
ARP_PRESENT_PENALTY = -10  # ARP presente → host visto di recente su L2
TRACE_UP_PENALTY    = -5   # Traceroute raggiunge destinazione → host attivo

# Port names for reports
PORT_NAMES = {
    22:   "SSH",
    6556: "CMK-Agent",
    443:  "HTTPS",
    80:   "HTTP",
    3389: "RDP",
    8080: "HTTP-alt",
    5985: "WinRM",
    5986: "WinRM-SSL",
    135:  "RPC",
    161:  "SNMP",
    162:  "SNMP-trap",
    2222: "SSH-alt",
}


# ─── Check result class ───────────────────────── ─────────────────────────

class DiagResult:
    """Result of a single diagnostic check."""

    STATUS_DOWN    = "down"
    STATUS_UP      = "up"
    STATUS_UNKNOWN = "unknown"
    STATUS_INFO    = "info"

    ICONS = {
        STATUS_DOWN:    "",
        STATUS_UP:      "",
        STATUS_UNKNOWN: "",
        STATUS_INFO:    "ℹ",
    }

    def __init__(self, name, desc, status, msg, score):
        self.name   = name    # nome breve (per CheckMK metric)
        self.desc   = desc    # descrizione leggibile
        self.status = status  # "down" / "up" / "unknown" / "info"
        self.msg    = msg     # messaggio dettaglio
        self.score  = score   # contributo al punteggio finale

    @property
    def icon(self):
        return self.ICONS.get(self.status, "")

    def __repr__(self):
        return "DiagResult({}, {}, score={})".format(self.name, self.status, self.score)


# ─── Funzioni diagnostiche ───────────────────────────────────────────────────

def diag_dns(host):
    """Check DNS resolution of the hostname."""
    try:
        ip = socket.gethostbyname(host)
        return DiagResult(
            "dns", "Risoluzione DNS", DiagResult.STATUS_INFO,
            "Risolve in {}".format(ip),
            DNS_OK_WEIGHT
        )
    except socket.gaierror as e:
        return DiagResult(
            "dns", "Risoluzione DNS", DiagResult.STATUS_UNKNOWN,
            "DNS non risolve: {} — potrebbe essere problema DNS, non host".format(e),
            DNS_FAIL_PENALTY
        )


def diag_ping(host, count=5, timeout_sec=2):
    """ICMP multiple ping with packet loss analysis."""
    desc = "ICMP Ping ({}x, {}s timeout)".format(count, timeout_sec)
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), "-W", str(timeout_sec), host],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=count * (timeout_sec + 1) + 5
        )
        output = result.stdout.decode("utf-8", errors="replace")

        # Estrai percentuale packet loss
        loss_pct = 100
        m = re.search(r"(\d+)%\s+packet loss", output)
        if m:
            loss_pct = int(m.group(1))

        if result.returncode == 0 and loss_pct == 0:
            return DiagResult(
                "ping", desc, DiagResult.STATUS_UP,
                "Risponde! {}/{} pacchetti ricevuti".format(count, count),
                PING_UP_PENALTY
            )
        elif loss_pct == 100:
            return DiagResult(
                "ping", desc, DiagResult.STATUS_DOWN,
                "100% packet loss — nessuna risposta ICMP",
                PING_DOWN_WEIGHT
            )
        else:
            received = count - int(round(count * loss_pct / 100.0))
            return DiagResult(
                "ping", desc, DiagResult.STATUS_UNKNOWN,
                "{}% loss ({}/{} ricevuti) — connessione instabile".format(loss_pct, received, count),
                0
            )

    except subprocess.TimeoutExpired:
        return DiagResult(
            "ping", desc, DiagResult.STATUS_DOWN,
            "Timeout globale dopo {}x tentativi ping".format(count),
            PING_DOWN_WEIGHT
        )
    except OSError as e:
        return DiagResult(
            "ping", desc, DiagResult.STATUS_UNKNOWN,
            "Comando ping non disponibile: {}".format(e),
            0
        )
    except Exception as e:
        return DiagResult(
            "ping", desc, DiagResult.STATUS_UNKNOWN,
            "Errore inatteso: {}".format(e),
            0
        )


def diag_tcp(host, port, timeout_sec=3):
    """TCP connectivity test on specific port."""
    port_label = PORT_NAMES.get(port, "port-{}".format(port))
    desc = "TCP {}/{}".format(port, port_label)
    weight_down = TCP_PORT_WEIGHTS.get(port, 5)

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout_sec)
        err = sock.connect_ex((host, port))
        sock.close()

        if err == 0:
            # Connection successful → host responds
            return DiagResult(
                "tcp_{}".format(port), desc, DiagResult.STATUS_UP,
                "Connessione riuscita → host attivo e servizio in ascolto",
                TCP_UP_PENALTY
            )
        elif err == errno.ECONNREFUSED:
            # Host active but port closed
            return DiagResult(
                "tcp_{}".format(port), desc, DiagResult.STATUS_UP,
                "Porta rifiutata (ECONNREFUSED) → host attivo, servizio non in ascolto",
                TCP_UP_PENALTY
            )
        else:
            # Timeout or other network error → host probably offline
            return DiagResult(
                "tcp_{}".format(port), desc, DiagResult.STATUS_DOWN,
                "Nessuna risposta (errno {}) — timeout TCP".format(err),
                weight_down
            )

    except socket.timeout:
        return DiagResult(
            "tcp_{}".format(port), desc, DiagResult.STATUS_DOWN,
            "Timeout ({}s) — porta non raggiungibile".format(timeout_sec),
            weight_down
        )
    except Exception as e:
        return DiagResult(
            "tcp_{}".format(port), desc, DiagResult.STATUS_UNKNOWN,
            "Errore socket: {}".format(e),
            0
        )


def diag_arp(host_ip):
    """Check presence of ARP entry (same L2 segment only)."""
    try:
        result = subprocess.run(
            ["arp", "-n", host_ip],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5
        )
        output = result.stdout.decode("utf-8", errors="replace")

        if result.returncode != 0 or "no entry" in output.lower():
            return DiagResult(
                "arp", "ARP table (L2)", DiagResult.STATUS_DOWN,
                "Nessuna entry ARP → host non visto di recente sul segmento L2",
                ARP_MISSING_WEIGHT
            )
        elif "(incomplete)" in output:
            return DiagResult(
                "arp", "ARP table (L2)", DiagResult.STATUS_DOWN,
                "ARP incompleto → host non risponde a livello L2",
                ARP_MISSING_WEIGHT
            )
        else:
            # Prova a estrarre MAC address
            mac_m = re.search(r"([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})", output)
            mac = mac_m.group(1) if mac_m else "N/A"
            return DiagResult(
                "arp", "ARP table (L2)", DiagResult.STATUS_UP,
                "MAC presente: {} → host visto di recente su L2".format(mac),
                ARP_PRESENT_PENALTY
            )

    except OSError:
        return DiagResult(
            "arp", "ARP table (L2)", DiagResult.STATUS_UNKNOWN,
            "Comando 'arp' non disponibile su questo sistema",
            0
        )
    except Exception as e:
        return DiagResult(
            "arp", "ARP table (L2)", DiagResult.STATUS_UNKNOWN,
            "Errore: {}".format(e),
            0
        )


def diag_traceroute(host, max_hops=15):
    """Traceroute: Check if the destination is reachable."""
    try:
        result = subprocess.run(
            ["traceroute", "-n", "-w", "2", "-m", str(max_hops), host],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max_hops * 3 + 10
        )
        output = result.stdout.decode("utf-8", errors="replace")

        # Filter only rows with numbered hops
        hop_lines = []
        for line in output.strip().split("\n"):
            line = line.strip()
            if line and line[0].isdigit():
                hop_lines.append(line)

        if not hop_lines:
            return DiagResult(
                "traceroute", "Traceroute", DiagResult.STATUS_UNKNOWN,
                "Nessun output utile da traceroute",
                0
            )

        last = hop_lines[-1]
        parts = last.split()
        # parts[0] is hop number, parts[1:] are replies (IP or *)
        hop_responses = parts[1:4] if len(parts) >= 4 else parts[1:]
        all_stars = all(p == "*" for p in hop_responses)

        if all_stars:
            hop_num = parts[0]
            return DiagResult(
                "traceroute", "Traceroute", DiagResult.STATUS_DOWN,
                "Ultima risposta: hop {} — destinazione non raggiungibile (* * *)".format(hop_num),
                TRACE_TIMEOUT_WEIGHT
            )
        else:
            return DiagResult(
                "traceroute", "Traceroute", DiagResult.STATUS_UP,
                "Destinazione raggiunta via traceroute",
                TRACE_UP_PENALTY
            )

    except subprocess.TimeoutExpired:
        return DiagResult(
            "traceroute", "Traceroute", DiagResult.STATUS_DOWN,
            "Timeout globale traceroute — destinazione irraggiungibile",
            TRACE_TIMEOUT_WEIGHT
        )
    except OSError:
        return DiagResult(
            "traceroute", "Traceroute", DiagResult.STATUS_UNKNOWN,
            "Comando 'traceroute' non disponibile (installare inetutils-traceroute o traceroute)",
            0
        )
    except Exception as e:
        return DiagResult(
            "traceroute", "Traceroute", DiagResult.STATUS_UNKNOWN,
            "Errore: {}".format(e),
            0
        )


# ─── Motore diagnosi principale ──────────────────────────────────────────────

def run_all_checks(host, ports, skip_arp, skip_trace):
    """Performs all diagnostic checks and calculates the confidence score.

    Returns:
        (confidence_percentage, list_of_DiagResult)"""
    results = []

    # 1. DNS check — also to resolve the IP for subsequent checks
    dns_result = diag_dns(host)
    results.append(dns_result)

    try:
        resolved_ip = socket.gethostbyname(host)
    except socket.gaierror:
        resolved_ip = host  # Usa direttamente, potrebbe essere già un IP

    # 2. Ping
    ping_result = diag_ping(resolved_ip)
    results.append(ping_result)

    # Optimization: if ping responds clearly → host is UP, skip TCP
    if ping_result.status == DiagResult.STATUS_UP:
        raw = sum(r.score for r in results)
        return max(0, min(100, raw)), results

    # 3. TCP ports
    for port in ports:
        results.append(diag_tcp(resolved_ip, port))

    # 4. ARP (optional, same L2 only)
    if not skip_arp:
        results.append(diag_arp(resolved_ip))

    # 5. Traceroute (opzionale, lento)
    if not skip_trace:
        results.append(diag_traceroute(resolved_ip))

    # Calcolo confidenza finale
    raw = sum(r.score for r in results)
    confidence = max(0, min(100, raw))

    return confidence, results


# ─── Output formatting ────────────────────────── ──────────────────────────

def get_verdict(confidence):
    """Restituisce (label_verdetto, testo_dettaglio)."""
    if confidence >= 90:
        return " OFFLINE CONFERMATO",        "L'host è quasi certamente spento o irraggiungibile"
    elif confidence >= 80:
        return " MOLTO PROBABILMENTE OFFLINE", "Alta probabilità che l'host sia spento"
    elif confidence >= 60:
        return " PROBABILMENTE OFFLINE",        "Possibile problema host, ma potrebbe essere transitorio"
    elif confidence >= 30:
        return " INCERTO",                      "Difficile distinguere tra problema host e problema di rete"
    else:
        return " HOST PROBABILMENTE ATTIVO",    "Almeno un servizio risponde — host probabilmente attivo"


def format_human(host, confidence, results):
    """Readable output for operators."""
    SEP  = "=" * 64
    SEP2 = "─" * 64

    lines = [
        SEP,
        "  DIAGNOSI HOST OFFLINE",
        "  Host: {}".format(host),
        "  Script: {} v{}".format(SCRIPT_NAME, VERSION),
        SEP,
        "",
    ]

    max_desc = max(len(r.desc) for r in results)
    for r in results:
        if r.score > 0:
            score_str = "[+{}%]".format(r.score)
        elif r.score < 0:
            score_str = "[{}%]".format(r.score)
        else:
            score_str = "[±0%]"
        lines.append("  {}  {:<{}}  {:>7}  {}".format(
            r.icon, r.desc, max_desc, score_str, r.msg
        ))

    lines += [
        "",
        SEP2,
    ]

    verdict, detail = get_verdict(confidence)
    lines += [
        "  CONFIDENZA OFFLINE:  {}%".format(confidence),
        "  VERDETTO:            {}".format(verdict),
        "  NOTA:                {}".format(detail),
        SEP,
    ]

    return "\n".join(lines)


def format_checkmk(host, confidence, results):
    """Output in CheckMK local check format for OMD integration."""
    state = 2 if confidence >= 90 else (1 if confidence >= 60 else 0)
    metric = "confidence={}%;60;90".format(confidence)
    safe_host = re.sub(r"[^a-zA-Z0-9_]", "_", host)
    verdict, _ = get_verdict(confidence)
    # Includes check details as part of the performance text
    check_summary = ", ".join(
        "{}:{}".format(r.name, r.status) for r in results
    )
    return "{} HostOfflineConfidence_{} {} {}% offline confidence for {} | {}".format(
        state, safe_host, metric, confidence, host, check_summary
    )


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog=SCRIPT_NAME,
        description="{} v{} — Diagnosi affidabilita HOST OFFLINE".format(SCRIPT_NAME, VERSION),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s 192.0.2.100
  %(prog)s ns8.dominio.it --ports 22 6556 443 3389
  %(prog)s 10.0.0.50 --no-arp --no-traceroute --threshold 80
  %(prog)s 10.0.0.50 --checkmk

Notes on maximum achievable weights:
  Without --no-arp and --no-traceroute → max 105% (capped 100%)
  With just --no-traceroute → max 95%
  With just --no-arp → max 90%
  With --no-arp --no-traceroute → max 80% (use --threshold 80)"""
    )
    parser.add_argument(
        "host",
        help="Hostname o indirizzo IP da diagnosticare"
    )
    parser.add_argument(
        "--ports", nargs="+", type=int, default=[22, 6556, 443, 80],
        help="Porte TCP da verificare (default: 22 6556 443 80)"
    )
    parser.add_argument(
        "--no-arp", action="store_true",
        help="Salta check ARP (usa se host NON e' sullo stesso segmento L2)"
    )
    parser.add_argument(
        "--no-traceroute", action="store_true",
        help="Salta traceroute (piu' veloce, traceroute e' lento ~30sec)"
    )
    parser.add_argument(
        "--threshold", type=int, default=90,
        help="Soglia %% confidenza per exit code 2 = offline confermato (default: 90)"
    )
    parser.add_argument(
        "--checkmk", action="store_true",
        help="Output in formato CheckMK local check (STATE SERVICE metric message)"
    )
    parser.add_argument(
        "--version", action="version",
        version="{} {}".format(SCRIPT_NAME, VERSION)
    )

    args = parser.parse_args()

    confidence, results = run_all_checks(
        args.host,
        args.ports,
        skip_arp=args.no_arp,
        skip_trace=args.no_traceroute,
    )

    if args.checkmk:
        print(format_checkmk(args.host, confidence, results))
    else:
        print(format_human(args.host, confidence, results))

    # Exit codes
    if confidence >= args.threshold:
        return 2   # Offline confermato
    elif confidence >= 60:
        return 1   # Probabilmente offline / incerto
    return 0       # Host probabilmente attivo


if __name__ == "__main__":
    sys.exit(main())
