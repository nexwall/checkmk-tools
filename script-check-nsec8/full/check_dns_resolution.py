#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""check_dns_resolution.py - CheckMK DNS check.

Sends a raw DNS query directly to 127.0.0.1:53 to test the LOCAL resolver
(dnsmasq) specifically, not whatever upstream the system resolver happens
to be configured with.
"""

import socket
import struct
import sys
import time

VERSION = "1.2.0"
SERVICE = "DNS.Resolution"
TEST_DOMAINS = ["google.com", "cloudflare.com", "dns.google"]
LOCAL_RESOLVER = "127.0.0.1"


def _build_query(domain, txid):
    header = struct.pack(">HHHHHH", txid, 0x0100, 1, 0, 0, 0)
    qname = b"".join(
        struct.pack("B", len(label)) + label.encode("ascii")
        for label in domain.split(".")
    ) + b"\x00"
    question = qname + struct.pack(">HH", 1, 1)  # QTYPE=A, QCLASS=IN
    return header + question


def resolve(domain, timeout_sec=5):
    """Query the local resolver (127.0.0.1:53) directly via a raw UDP DNS
    query - socket.getaddrinfo()'s "port 53" argument is only the sockaddr
    service field, NOT a directive to query a specific server on port 53:
    resolution went through whatever the system resolver/NSS is configured
    with, not necessarily the local dnsmasq the doc claims to test.
    """
    start = time.perf_counter()
    txid = int(time.time() * 1000) & 0xFFFF
    query = _build_query(domain, txid)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout_sec)
        try:
            sock.sendto(query, (LOCAL_RESOLVER, 53))
            data, _ = sock.recvfrom(512)
        finally:
            sock.close()
        elapsed = int((time.perf_counter() - start) * 1000)
        if len(data) < 12:
            return False, elapsed
        resp_id, flags = struct.unpack(">HH", data[:4])
        rcode = flags & 0x000F
        ok = resp_id == txid and rcode == 0
        return ok, elapsed
    except Exception:
        return False, int((time.perf_counter() - start) * 1000)


def main():
    successful = 0
    failed = 0
    times = []
    for domain in TEST_DOMAINS:
        ok, ms = resolve(domain)
        if ok:
            successful += 1
            times.append(ms)
        else:
            failed += 1
    total = len(TEST_DOMAINS)
    avg = int(sum(times) / len(times)) if times else 0
    # Two-tier threshold per doc/check_dns_resolution.md: WARNING >500ms,
    # CRITICAL >1000ms or total failure. The previous code only ever
    # reached WARNING for slow response (avg>1000 -> WARNING), and had no
    # 500ms tier at all - real prolonged slow response never reached the
    # CRITICAL severity the doc promises, and moderate slowness (500-1000ms)
    # was never flagged at all.
    if failed == total:
        st, txt = 2, "CRITICAL - DNS not responding"
    elif failed > 0:
        st, txt = 1, "WARNING - Some tests failed"
    elif avg > 1000:
        st, txt = 2, "CRITICAL - DNS slow response"
    elif avg > 500:
        st, txt = 1, "WARNING - DNS slow response"
    else:
        st, txt = 0, "OK"
    # Perfdata must be the single whitespace-free 3rd field (CheckMK's local
    # check parser never re-scans the free-text field for a later "|") -
    # "successful"/"failed"/"total"/"avg_time_ms" were previously placed
    # after the free text, so only "response_time" was ever actually
    # graphed. "avg_time_ms" is dropped here as a duplicate of
    # "response_time" (same value under a different name).
    perfdata = f"response_time={avg}ms;500;1000|successful={successful}|failed={failed}|total={total}"
    print(f"{st} {SERVICE} {perfdata} Test: {successful}/{total} OK, avg time: {avg}ms - {txt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
