#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""check_firewall_rules.py - CheckMK firewall rules check.

Counts nftables rules, zones, and forwardings using:
  - nft -j (JSON output, if available) for a precise, structured rule count
  - nethsec.utils.get_all_by_type() as a UCI-level fallback for zone/
    forwarding/rule/redirect counts if nft is unavailable
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "1.4.0"
SERVICE = "Firewall.Rules"


def find_nft():
    nft_path = shutil.which("nft")
    if nft_path:
        return nft_path
    for p in ["/usr/sbin/nft", "/usr/bin/nft", "/sbin/nft", "/bin/nft"]:
        if Path(p).exists():
            return p
    return None


def count_nft_rulesets(nft_bin):
    """Use `nft -j list ruleset` (structured JSON) to count tables, chains,
    and rules precisely - avoids fragile text-heuristics that undercount
    real rules (e.g. any rule statement starting with "ct ", such as the
    fw4-generated `ct state vmap { established: accept, ... }` dispatch
    rules present in nearly every real ruleset, was previously never
    counted at all).
    """
    try:
        result = subprocess.run(
            [nft_bin, "-j", "list", "ruleset"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return None, f"nft error: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return None, "nft list ruleset timed out"
    except FileNotFoundError:
        return None, "nft binary not found"

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return None, f"nft JSON parse error: {e}"

    items = data.get("nftables", [])
    table_count = sum(1 for i in items if "table" in i)
    chain_count = sum(1 for i in items if "chain" in i)
    rule_count = sum(1 for i in items if "rule" in i)

    return {
        "tables": table_count,
        "chains": chain_count,
        "rules": rule_count,
    }, None


def count_uci_firewall():
    try:
        from euci import EUci
        from nethsec.utils import get_all_by_type
    except ImportError:
        return None, "nethsec/pyuci not available"
    try:
        with EUci() as u:
            zones = len(get_all_by_type(u, "firewall", "zone"))
            forwardings = len(get_all_by_type(u, "firewall", "forwarding"))
            rules = len(get_all_by_type(u, "firewall", "rule"))
            redirects = len(get_all_by_type(u, "firewall", "redirect"))
    except Exception as e:
        return None, f"UCI error: {e}"
    return {"zones": zones, "forwardings": forwardings, "rules": rules, "redirects": redirects}, None


def main():
    nft_bin = find_nft()
    if nft_bin:
        nft_result, nft_err = count_nft_rulesets(nft_bin)
        if nft_result:
            r = nft_result
            # Perfdata must be the single whitespace-free 3rd field (see
            # check_firewall_traffic.py for why) - it was previously placed
            # after the free text, so CheckMK graphed zero metrics here.
            perfdata = f"tables={r['tables']}|chains={r['chains']}|rules={r['rules']}"
            print(
                f"0 {SERVICE} {perfdata} OK - {r['tables']} tables, {r['chains']} chains, "
                f"{r['rules']} rules (nft)"
            )
            return 0

    # UCI-only fallback
    uci_result, uci_err = count_uci_firewall()
    if uci_result:
        r = uci_result
        perfdata = f"zones={r['zones']}|forwardings={r['forwardings']}|rules={r['rules']}"
        print(
            f"0 {SERVICE} {perfdata} OK - {r['zones']} zones, {r['forwardings']} forwarding, "
            f"{r['rules']} rules (UCI)"
        )
        return 0

    reasons = []
    if nft_err:
        reasons.append(nft_err)
    if uci_err:
        reasons.append(uci_err)
    print(
        f"3 {SERVICE} - Cannot read firewall rules"
        + (f" ({'; '.join(reasons)})" if reasons else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
