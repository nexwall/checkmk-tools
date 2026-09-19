#!/usr/bin/env python3
# Copyright (C) 2026 Nethesis S.r.l.
"""Graphing definitions (metrics + Perf-O-Meter) for check_nv8_status_trunk.py.

Cosmetic only: CheckMK already renders full graphs from raw perfdata without
this file (see script-check-ns8/full/check_nv8_status_trunk.py, v1.5.0+).
This adds the small colored Perf-O-Meter bar in the service list for the
custom "registered" / "registered_trunks" / "total_trunks" metrics emitted
by that local check - CheckMK has no built-in definition for custom metric
names, so without this file the graph works but the mini-bar in the service
list is blank.

Deployment (CheckMK 2.3+ / cmk.graphing.v1 API, verified on 2.5.0p12):
  cp script-check-ns8/full/graphing/nv8_trunk.py \\
     ~/local/lib/python3/cmk_addons/plugins/ns8_checks/graphing/nv8_trunk.py
  omd reload apache   # or restart - reloads the GUI's metrics/perfometer registry
"""

from cmk.graphing.v1 import Title
from cmk.graphing.v1.metrics import Color, DecimalNotation, Metric, Unit
from cmk.graphing.v1.perfometers import Closed, FocusRange, Perfometer

UNIT_COUNT = Unit(DecimalNotation(""))

metric_registered = Metric(
    name="registered",
    title=Title("Trunk registered"),
    unit=UNIT_COUNT,
    color=Color.GREEN,
)
metric_registered_trunks = Metric(
    name="registered_trunks",
    title=Title("Registered trunks"),
    unit=UNIT_COUNT,
    color=Color.GREEN,
)
metric_total_trunks = Metric(
    name="total_trunks",
    title=Title("Total trunks"),
    unit=UNIT_COUNT,
    color=Color.BLUE,
)

# Per-trunk service (NV8.Status.Trunk.<id>): 0/1 gauge, fixed range.
perfometer_nv8_trunk_registered = Perfometer(
    name="nv8_trunk_registered",
    focus_range=FocusRange(Closed(0), Closed(1)),
    segments=["registered"],
)

# Summary service (NV8.Status.Trunks): registered count out of the dynamic
# total (bound to the total_trunks metric, not a fixed number - the trunk
# count varies per NS8 host).
perfometer_nv8_status_trunks = Perfometer(
    name="nv8_status_trunks",
    focus_range=FocusRange(Closed(0), Closed("total_trunks")),
    segments=["registered_trunks"],
)
