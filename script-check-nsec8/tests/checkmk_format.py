#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""Minimal re-implementation of CheckMK's local-check line parser
(cmk/plugins/checkmk/agent_based/local.py: _split_check_result/_parse_perftxt),
used to assert perfdata is actually graphable - not just visually
plausible - directly against the real field-3-only rule instead of a regex
guess. A systemic bug (perfdata placed after free text, silently producing
zero graphed metrics) was found in 7 of the 10 production scripts and fixed
in this same session precisely because "looks right" was not enough.
"""

import re

_LINE_RE = re.compile(
    r"^"
    r"([^ ]+) +"
    r"((\"([^\"']+)\")|('([^\"']+)')|([^ \"']+)) +"
    r"([^ ]+)"
    r"( +(.*))?"
    r"$"
)


def split_check_result(line):
    """Return (state, service, perfdata_field, text) or None if unparseable."""
    match = _LINE_RE.match(line)
    if match is None:
        return None
    g = match.groups()
    return (g[0] or "", g[5] or g[3] or g[1] or "", g[7] or "", g[9])


def _parse_perfentry(entry):
    entry = entry.rstrip(";")
    name, raw_list = entry.split("=", 1)
    raw = raw_list.split(";")
    try:
        value = float(raw[0])
    except ValueError:
        value = float(re.sub(r"[a-zA-Z%/]+$", "", raw[0]))
    return name, value


def parse_perfdata(perf_field):
    """Return the list of (name, value) metrics CheckMK would actually graph."""
    if perf_field == "-" or not perf_field:
        return []
    metrics = []
    for entry in perf_field.split("|"):
        try:
            metrics.append(_parse_perfentry(entry))
        except (ValueError, IndexError):
            pass
    return metrics


def graphed_metric_names(line):
    """Convenience: the set of metric names CheckMK would actually graph for this line."""
    parsed = split_check_result(line)
    assert parsed is not None, f"line did not match the local-check format: {line!r}"
    _, _, perf_field, _ = parsed
    return {name for name, _ in parse_perfdata(perf_field)}
