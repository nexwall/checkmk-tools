#!/usr/bin/env python3
"""
notification-limiter-report.py — Checkmk notification limiter report generator.

Reads JSON Lines diagnostic logs from M@il-20 and Telegram-20 and produces
a human-readable email report showing exactly how the notification limiter
behaved over a selected time window.

Usage:
  # Default: last 24 hours, dry-run to stdout
  python3 notification-limiter-report.py --dry-run

  # With sample/copied logs
  python3 notification-limiter-report.py \\
    --mail-log /path/to/mail-20.log \\
    --telegram-log /path/to/telegram-20.log \\
    --since-hours 24 --dry-run

  # Send email via sendmail
  python3 notification-limiter-report.py --to-email admin@example.com

  # Cron: 13:00 report (previous 19 hours)
  python3 notification-limiter-report.py \\
    --since-hours 19 \\
    --to-email admin@example.com \\
    --subject-prefix "[Checkmk] Notification limiter report 18-13"

  # Cron: 18:00 report (previous 5 hours)
  python3 notification-limiter-report.py \\
    --since-hours 5 \\
    --to-email admin@example.com \\
    --subject-prefix "[Checkmk] Notification limiter report 13-18"
"""

import argparse
import datetime
import json
import gzip
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_VERSION = "1.0.0"
SCRIPT_NAME = "notification-limiter-report"

DEFAULT_LOG_PATHS = {
    "mail": "/omd/sites/monitoring/var/log/notifications/mail-20.log",
    "telegram": "/omd/sites/monitoring/var/log/notifications/telegram-20.log",
}

DEFAULT_DETAIL_LIMIT = 200
DEFAULT_SINCE_HOURS = 24
DEFAULT_PATTERN_HISTORY_DAYS = 7
DEFAULT_FROM_EMAIL = "srv-monitoring-us@nethesis.it"


# ---------------------------------------------------------------------------
# Archive discovery helpers
# ---------------------------------------------------------------------------


def _discover_log_files(base_path):
    """Discover all active and rotated log files for a given channel base path.

    Returns a sorted list of Path objects (oldest first) including the active
    log file and any rotated/compressed archives.
    """
    base = Path(base_path)
    parent = base.parent
    stem = base.name
    files = set()

    # Active log
    if base.exists():
        files.add(base)

    # Rotated files: stem.N and stem.N.gz
    if parent.is_dir():
        for p in parent.iterdir():
            name = p.name
            if name == stem:
                continue
            if name.startswith(stem + "."):
                rest = name[len(stem) + 1:]
                # stem.N  or  stem.N.gz
                if rest.isdigit():
                    files.add(p)
                elif "." in rest:
                    num_part, ext = rest.rsplit(".", 1)
                    if num_part.isdigit() and ext == "gz":
                        files.add(p)

    # Sort from oldest (highest rotation number) to newest (active file)
    def _sort_key(p):
        name = p.name
        rest = name[len(stem) + 1:]
        num_str = rest.split(".")[0]
        if num_str.isdigit():
            return -int(num_str)  # negative -> descending -> oldest first
        return 0  # active file goes last

    return sorted(files, key=_sort_key)


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


_LOG_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})")


def _parse_log_line_ts(line):
    """Extract the ISO-ish timestamp from a log line prefix.

    Returns a datetime.datetime or None.
    """
    m = _LOG_TS_RE.match(line)
    if m:
        try:
            return datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return None


def _parse_record_ts(rec):
    """Try to extract a datetime from a record's timestamp field.

    Supports ISO strings and Unix epoch integers.
    Returns a datetime.datetime or None.
    """
    ts = rec.get("timestamp")
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(ts)
        except (OSError, ValueError):
            return None
    if isinstance(ts, str):
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
        ):
            try:
                return datetime.datetime.strptime(ts, fmt)
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# JSON Lines parsing
# ---------------------------------------------------------------------------


class LogFileStats:
    """Tracks per-file parse statistics."""

    def __init__(self, name):
        self.name = name
        self.total_lines = 0
        self.bad_json = 0
        self.records = []  # list of parsed dicts
        self.unknown_events = Counter()

    @property
    def total_records(self):
        return len(self.records)


def _open_log_file(path):
    """Open a log file for reading — supports plain text and gzip."""
    p = Path(path)
    if p.suffix == ".gz":
        return gzip.open(p, "rt", encoding="utf-8", errors="replace")
    return open(p, "r", encoding="utf-8", errors="replace")


def parse_log_file(path, label, logger):
    """Parse a JSON Lines log file (plain text or gzip compressed).

    Returns a LogFileStats object.  Never raises — bad lines are counted.
    """
    stats = LogFileStats(label)
    pp = Path(path)
    if not pp.exists():
        logger.missing_files.append(str(path))
        return stats

    logger.files_read.append(str(path))

    f = _open_log_file(path)
    try:
        for line in f:
            stats.total_lines += 1
            # Find the JSON part after NOTIFY_EVENT marker
            if "NOTIFY_EVENT " not in line:
                continue
            raw = line.split("NOTIFY_EVENT ", 1)[1]
            try:
                rec = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                stats.bad_json += 1
                continue

            # Attach the log-line timestamp as a fallback
            log_ts = _parse_log_line_ts(line)
            if log_ts is not None and "timestamp" not in rec:
                rec["_log_ts"] = log_ts

            rec["_source"] = label
            rec["_raw_line"] = line
            stats.records.append(rec)
    finally:
        f.close()

    logger.total_raw_lines += stats.total_lines
    return stats


def parse_log_channel(base_path, label, logger):
    """Discover all rotated archives for a notification channel and parse them.

    Returns a LogFileStats object aggregating all discovered files.
    Never raises — missing directories or files are silently skipped.
    """
    files = _discover_log_files(base_path)
    if not files:
        logger.missing_files.append(base_path)
        return LogFileStats(label)

    combined = LogFileStats(label)
    for f in files:
        fs = parse_log_file(str(f), label, logger)
        combined.total_lines += fs.total_lines
        combined.bad_json += fs.bad_json
        combined.records.extend(fs.records)
        combined.unknown_events += fs.unknown_events

    return combined


# ---------------------------------------------------------------------------
# Data quality logger
# ---------------------------------------------------------------------------


class DataQuality:
    """Collects data-quality statistics during report generation."""

    def __init__(self):
        self.files_read = []
        self.missing_files = []
        self.total_raw_lines = 0
        self.bad_json_records = 0
        self.outside_period = 0
        self.unknown_events = Counter()
        self.missing_host = 0
        self.missing_category = 0
        self.missing_execution_id = 0

    def add_bad_json(self, count):
        self.bad_json_records += count

    def record_event(self, status):
        if status not in _KNOWN_EVENTS:
            self.unknown_events[status] += 1


_KNOWN_EVENTS = frozenset({
    "INVOKED", "ACCEPTED", "DECISION", "DELIVERING", "DELIVERED",
    "COMPLETE", "FAILED", "ERROR",
    "COOLDOWN_DECISION", "WOULD_SUPPRESS_COOLDOWN", "SUPPRESSED_COOLDOWN",
    "COOLDOWN_BYPASS_RECOVERY", "ADAPTIVE_COOLDOWN_RECOMMENDATION",
    "SUPPRESSED", "WOULD_SUPPRESS", "AUDIT_NOT_SUPPRESSED",
})


# ---------------------------------------------------------------------------
# Time window filtering
# ---------------------------------------------------------------------------


def in_window(rec, window_start, window_end):
    """Check if a record falls within the time window."""
    ts = _parse_record_ts(rec)
    if ts is None:
        ts = rec.get("_log_ts")
    if ts is None:
        return True  # no timestamp — include by default
    # Make naive if needed
    if ts.tzinfo is not None:
        ts = ts.replace(tzinfo=None)
    return window_start <= ts <= window_end


def get_event_ts(rec):
    """Return the best available timestamp for a record."""
    ts = _parse_record_ts(rec)
    if ts is None:
        ts = rec.get("_log_ts")
    if ts is None:
        return "no timestamp"
    if ts.tzinfo is not None:
        ts = ts.replace(tzinfo=None)
    return ts.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Report engine
# ---------------------------------------------------------------------------


# Minimum width for report separators (fallback if content is shorter)
MIN_REPORT_WIDTH = 72

# Maximum width for report separators (cap to prevent excessively wide lines)
MAX_REPORT_WIDTH = 160

class ReportEngine:
    """Processes parsed records and produces the report using execution-based aggregation."""

    def __init__(self, all_records, args, dq=None, pattern_engine=None):
        self.records = all_records
        self.args = args
        self.dq = dq or DataQuality()
        self.executions = []        # list of normalized execution dicts
        self.adaptive_records = []  # ADAPTIVE_COOLDOWN_RECOMMENDATION records
        self.error_count = 0
        self._build_executions()

        # Store reference to pattern history engine (built externally, used by section 9.6)
        self.pattern_history_execs = []
        if pattern_engine:
            self.pattern_history_execs = [
                e for e in pattern_engine.executions if not e.get("_skip")
            ]

    def _build_executions(self):
        """Group records into normalized execution objects.

        Two-phase approach:
        1. Build main executions from records WITH execution_id.
        2. Enrich/dedicated executions from records WITHOUT execution_id
           (DECISION, COOLDOWN_BYPASS_RECOVERY, SUPPRESSED_COOLDOWN)
           by matching on (script, host) to the nearest main execution.
        """
        # Phase 1: Process records WITH execution_id
        eid_groups = {}
        orphan_records = []  # records without execution_id
        for rec in self.records:
            eid = rec.get("execution_id") or ""
            if eid:
                eid_groups.setdefault(eid, []).append(rec)
            else:
                orphan_records.append(rec)

        for eid, recs in eid_groups.items():
            exec_obj = self._normalize_execution(eid, recs)
            if not exec_obj.get("_skip"):
                self.executions.append(exec_obj)

        # Phase 2: Match orphan records (no execution_id) to existing executions
        for rec in orphan_records:
            status = rec.get("status", "")
            if status == "ADAPTIVE_COOLDOWN_RECOMMENDATION":
                self.adaptive_records.append(rec)
                continue

            if status in ("FAILED", "ERROR"):
                self.error_count += 1

            # Try to match by (script, host) to an existing execution
            src = rec.get("_source", "")
            host = rec.get("host") or rec.get("host_name", "") or ""
            cat = rec.get("category", "") or ""

            match = None
            if host and src:
                for e in self.executions:
                    if e.get("script") == src and e.get("host") == host:
                        match = e
                        break

            if match:
                # Enrich the matched execution with orphan data
                self._enrich_execution(match, rec)
            else:
                # Create a standalone execution for this orphan
                synthetic_eid = f"orphan_{src}_{status}_{host}_{cat}_{rec.get('old_state','?')}_{rec.get('new_state','?')}"
                eo = self._normalize_execution(synthetic_eid, [rec])
                if not eo.get("_skip"):
                    self.executions.append(eo)

    def _normalize_execution(self, eid, recs):
        """Build one normalized execution dict from all records sharing the same execution_id."""
        exec_obj = {
            "execution_id": eid,
            "script": None,
            "host": None,
            "service": None,
            "category": None,
            "old_state": None,
            "new_state": None,
            "notification_type": None,
            "final_result": None,
            "delivered": False,
            "suppressed": False,
            "recovery_bypass": False,
            "cooldown_seconds": None,
            "elapsed_seconds": None,
            "timestamps": [],
            "statuses_seen": set(),
            "reason": None,
        }

        for rec in recs:
            self._enrich_execution(exec_obj, rec)

        # If all records were adaptive recommendations, skip (not a notification execution)
        if exec_obj["statuses_seen"] == {"ADAPTIVE_COOLDOWN_RECOMMENDATION"}:
            exec_obj["_skip"] = True
            return exec_obj

        # Fallback for host/category
        if not exec_obj["host"]:
            exec_obj["host"] = "unknown"
        if not exec_obj["category"]:
            # If host is known but category is not, try to infer from old/new state
            if exec_obj["host"] != "unknown":
                old = exec_obj.get("old_state")
                new = exec_obj.get("new_state")
                if old == "DOWN" or new == "UP":
                    exec_obj["category"] = "host_state"
                else:
                    exec_obj["category"] = "service_state_ping"

        return exec_obj

    def _enrich_execution(self, exec_obj, rec):
        """Apply a single record's data to an execution object (in-place)."""
        status = rec.get("status", "")
        exec_obj["statuses_seen"].add(status)

        # Adaptive recommendations are collected but never enrich executions
        if status == "ADAPTIVE_COOLDOWN_RECOMMENDATION":
            self.adaptive_records.append(rec)
            return

        # Script name
        src = rec.get("_source", "")
        if src and not exec_obj["script"]:
            exec_obj["script"] = src

        # Host
        host = rec.get("host") or rec.get("host_name", "") or ""
        if host not in ("", "N/A", "$HOSTNAME$", "unknown"):
            exec_obj["host"] = host

        # Service
        svc = rec.get("service", "") or ""
        if svc and svc != "$SERVICEDESC$" and not exec_obj["service"]:
            exec_obj["service"] = svc

        # Category
        cat = rec.get("category", "") or ""
        if cat not in ("", "N/A", "?", "unknown"):
            exec_obj["category"] = cat

        # Old/new state
        old = rec.get("old_state", "") or ""
        new = rec.get("new_state", "") or ""
        if old:
            exec_obj["old_state"] = old
        if new:
            exec_obj["new_state"] = new

        # Notification type
        nt = rec.get("notification_type", "") or ""
        if nt:
            exec_obj["notification_type"] = nt

        # Reason
        reason = rec.get("reason", "") or ""
        if reason:
            exec_obj["reason"] = reason

        # Timestamps
        ts = _parse_record_ts(rec) or rec.get("_log_ts")
        if ts:
            exec_obj["timestamps"].append(ts)

        # Cooldown seconds from DECISION
        if status == "DECISION":
            cd = rec.get("cooldown_seconds")
            if cd is not None:
                exec_obj["cooldown_seconds"] = cd

        # Duration from COMPLETE
        if status == "COMPLETE":
            dur = rec.get("duration_ms")
            if dur is not None:
                exec_obj["elapsed_seconds"] = round(dur / 1000, 1)
            result = rec.get("result", "")
            exec_obj["final_result"] = result
            if result == "DELIVERED":
                exec_obj["delivered"] = True
            elif result in ("SUPPRESSED",):
                exec_obj["suppressed"] = True

        # DELIVERED without COMPLETE
        if status == "DELIVERED" and exec_obj["final_result"] is None:
            exec_obj["delivered"] = True
            exec_obj["final_result"] = "DELIVERED"

        # SUPPRESSED_COOLDOWN — count once
        if status == "SUPPRESSED_COOLDOWN" and not exec_obj["suppressed"]:
            exec_obj["suppressed"] = True
            if exec_obj["final_result"] is None:
                exec_obj["final_result"] = "SUPPRESSED"

        # WOULD_SUPPRESS_COOLDOWN (audit mode)
        if status == "WOULD_SUPPRESS_COOLDOWN":
            if exec_obj["final_result"] is None:
                exec_obj["final_result"] = "WOULD_SUPPRESS"

        # COOLDOWN_BYPASS_RECOVERY
        if status == "COOLDOWN_BYPASS_RECOVERY":
            exec_obj["recovery_bypass"] = True
            if exec_obj["final_result"] is None:
                exec_obj["final_result"] = "RECOVERY_BYPASS"

        # FAILED / ERROR
        if status in ("FAILED", "ERROR"):
            self.error_count += 1

    # ------------------------------------------------------------------
    # Aggregation helpers
    # ------------------------------------------------------------------

    @property
    def delivered_count(self):
        return sum(1 for e in self.executions if e.get("delivered") and not e.get("_skip"))

    @property
    def suppressed_count(self):
        return sum(1 for e in self.executions if e.get("suppressed") and not e.get("_skip"))

    @property
    def would_suppress_count(self):
        return sum(1 for e in self.executions if e.get("final_result") == "WOULD_SUPPRESS" and not e.get("_skip"))

    @property
    def recovery_count(self):
        return sum(1 for e in self.executions if e.get("recovery_bypass") and not e.get("_skip"))

    @property
    def total_executions(self):
        return sum(1 for e in self.executions if not e.get("_skip"))

    def _executions_for(self, field, value):
        """Filter executions where field == value."""
        return [e for e in self.executions if e.get(field) == value and not e.get("_skip")]

    def _get_ts(self, e):
        """Return formatted first timestamp or ''."""
        if e.get("timestamps"):
            ts = e["timestamps"][0]
            if hasattr(ts, "strftime"):
                return ts.strftime("%Y-%m-%d %H:%M:%S")
            return str(ts)
        return ""


    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _make_separator(self, title=""):
        sep = "=" * 72
        if title:
            return f"{sep}\n  {title}\n{sep}"
        return sep

    def _make_sub_separator(self, title=""):
        sep = "-" * 60
        if title:
            return f"{sep}\n  {title}\n{sep}"
        return sep

    def _append_detail_lines(self, lines, prefix, full_value, display_limit):
        """visual shortening in summary row, non-destructive because the full value available at this rendering point is preserved immediately below"""
        if len(str(full_value)) > display_limit:
            lines.append(f"    -> {prefix}: {full_value}")

    # --- Section 1: Executive summary ---

    def section_executive_summary(self):
        lines = []
        lines.append(self._make_separator("1. EXECUTIVE SUMMARY"))
        lines.append("")

        # Verdict line
        enforce_status = "active" if self.suppressed_count > 0 else "not triggered"
        verdict = (f"Verdict: ENFORCE {enforce_status} — {self.delivered_count} delivered, "
                   f"{self.suppressed_count} suppressed, {self.error_count} errors")
        lines.append(f"  {verdict}")
        lines.append("")

        lines.append(f"  Report period:         {self.args.window_start.strftime('%Y-%m-%d %H:%M')}"
                     f" — {self.args.window_end.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"  Log records parsed:    {len(self.records)}")
        lines.append(f"  Notification executions: {self.total_executions}")
        lines.append("")
        lines.append(f"  Delivered:             {self.delivered_count}")
        lines.append(f"  Would suppress (audit):  {self.would_suppress_count}")
        lines.append(f"  Suppressed (enforce):    {self.suppressed_count}")
        lines.append(f"  Recovery bypasses:     {self.recovery_count}")
        lines.append("")
        lines.append(f"  Cooldown decisions:    {self.suppressed_count + self.would_suppress_count}")
        lines.append(f"  Transition decisions:  {self.total_executions}")
        lines.append(f"  Errors/failures:       {self.error_count}")
        lines.append(f"  Malformed JSON lines:  {self.dq.bad_json_records}")
        lines.append("")
        return "\n".join(lines)

    # --- Section 2: Per-script summary ---

    def section_per_script(self):
        lines = []
        lines.append(self._make_separator("2. PER-SCRIPT SUMMARY"))
        lines.append("")
        lines.append(f"  {'Script':<20} {'Input':>8} {'Deliv.':>8} {'Would-Sup':>10} "
                     f"{'Sup.':>8} {'Recov.':>8} {'Errors':>8} {'BadJSON':>8}")
        lines.append(f"  {'-'*20} {'-'*8} {'-'*8} {'-'*10} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

        for label in sorted(set(e["script"] for e in self.executions if not e.get("_skip") and e.get("script"))):
            execs = self._executions_for("script", label)
            input_n = len(execs)
            deliv = sum(1 for e in execs if e["delivered"])
            would_sup = sum(1 for e in execs if e.get("final_result") == "WOULD_SUPPRESS")
            suppressed = sum(1 for e in execs if e["suppressed"])
            recovery = sum(1 for e in execs if e["recovery_bypass"])
            errors = self.error_count  # global (not perfect but same as before)
            bad = self.dq.bad_json_records

            lines.append(f"  {label:<20} {input_n:>8} {deliv:>8} "
                         f"{would_sup:>10} {suppressed:>8} {recovery:>8} "
                         f"{errors:>8} {bad:>8}")

        lines.append("")
        return "\n".join(lines)

    # --- Section 3: Per-host summary ---

    def section_per_host(self):
        lines = []
        lines.append(self._make_separator("3. PER-HOST SUMMARY"))
        lines.append("")
        lines.append(f"  {'Host':<30} {'Total':>6} {'Deliv.':>8} {'Would-Sup':>10} "
                     f"{'Sup.':>8} {'Recov.':>8} {'Top Cat.':>20} {'Last Event':>20}")
        lines.append(f"  {'-'*30} {'-'*6} {'-'*8} {'-'*10} {'-'*8} {'-'*8} {'-'*20} {'-'*20}")

        for host in sorted(set(e["host"] for e in self.executions if not e.get("_skip"))):
            execs = [e for e in self.executions if e["host"] == host and not e.get("_skip")]
            total = len(execs)
            deliv = sum(1 for e in execs if e["delivered"])
            would_sup = sum(1 for e in execs if e.get("final_result") == "WOULD_SUPPRESS")
            suppressed = sum(1 for e in execs if e["suppressed"])
            recovery = sum(1 for e in execs if e["recovery_bypass"])
            cat_counter = Counter(e.get("category", "unknown") for e in execs)
            top_cat = cat_counter.most_common(1)[0][0] if cat_counter else "?"
            last_ts = ""
            for e in reversed(execs):
                ts = self._get_ts(e)
                if ts:
                    last_ts = ts
                    break

            lines.append(f"  {host:<30} {total:>6} {deliv:>8} "
                         f"{would_sup:>10} {suppressed:>8} {recovery:>8} "
                         f"{top_cat[:20]:>20} {last_ts[:20]:>20}")

        lines.append("")
        return "\n".join(lines)

    # --- Section 4: Per-category summary ---

    def section_per_category(self):
        lines = []
        lines.append(self._make_separator("4. PER-CATEGORY SUMMARY"))
        lines.append("")
        lines.append(f"  {'Category':<25} {'Total':>6} {'Deliv.':>8} {'Would-Sup':>10} "
                     f"{'Sup.':>8} {'Recov.':>8}")
        lines.append(f"  {'-'*25} {'-'*6} {'-'*8} {'-'*10} {'-'*8} {'-'*8}")

        for cat in sorted(set(e["category"] for e in self.executions if not e.get("_skip"))):
            execs = [e for e in self.executions if e["category"] == cat and not e.get("_skip")]
            total = len(execs)
            deliv = sum(1 for e in execs if e["delivered"])
            would_sup = sum(1 for e in execs if e.get("final_result") == "WOULD_SUPPRESS")
            suppressed = sum(1 for e in execs if e["suppressed"])
            recovery = sum(1 for e in execs if e["recovery_bypass"])
            lines.append(f"  {cat:<25} {total:>6} {deliv:>8} "
                         f"{would_sup:>10} {suppressed:>8} {recovery:>8}")

        lines.append("")
        return "\n".join(lines)

    # --- Section 5: Detailed event table ---

    def section_detailed_events(self):
        limit = self.args.detail_limit
        # Sort executions by first timestamp
        sorted_execs = sorted(
            [e for e in self.executions if not e.get("_skip")],
            key=lambda e: (self._get_ts(e) or "", e["execution_id"])
        )

        lines = []
        lines.append(self._make_separator("5. DETAILED EVENT TABLE"))
        lines.append("")
        lines.append(f"  Showing {min(len(sorted_execs), limit)} of {len(sorted_execs)} executions")

        if len(sorted_execs) > limit:
            lines.append(f"  (truncated to {limit} — use --detail-limit to increase)")
            sorted_execs = sorted_execs[-limit:]

        lines.append("")
        header = (f"  {'Timestamp':<20} {'Script':<12} {'Host':<25} {'Category':<20} "
                  f"{'State':<12} {'Result':<20} {'EID':<12}")
        lines.append(header)
        lines.append(f"  {'-'*20} {'-'*12} {'-'*25} {'-'*20} {'-'*12} {'-'*20} {'-'*12}")

        for e in sorted_execs:
            ts = self._get_ts(e)[:20]
            src = (e.get("script") or "?")[:12]
            full_host = e.get("host") or "?"
            host = full_host[:25]
            cat = (e.get("category") or "?")[:20]
            old = e.get("old_state") or ""
            new = e.get("new_state") or ""
            state = f"{old}->{new}"[:12] if old and new else (new or old or "?")[:12]
            result = e.get("final_result") or e.get("notification_type") or "?"
            result_str = str(result)[:20]
            eid = e["execution_id"][:12]
            lines.append(f"  {ts:<20} {src:<12} {host:<25} {cat:<20} "
                         f"{state:<12} {result_str:<20} {eid:<12}")
            self._append_detail_lines(lines, "Full Host", full_host, 25)

        lines.append("")
        return "\n".join(lines)

    # --- Section 6: Blocked/would-blocked details ---

    def section_blocked(self):
        blocked = [e for e in self.executions if not e.get("_skip") and
                   (e["suppressed"] or e.get("final_result") == "WOULD_SUPPRESS")]
        if not blocked:
            return ""

        limit = self.args.detail_limit
        blocked.sort(key=lambda e: (self._get_ts(e) or "", e["execution_id"]))

        lines = []
        lines.append(self._make_separator("6. BLOCKED / WOULD-BLOCK DETAILS"))
        lines.append("")
        lines.append(f"  Showing {min(len(blocked), limit)} of {len(blocked)} executions")

        if len(blocked) > limit:
            lines.append(f"  (truncated to {limit})")
            blocked = blocked[-limit:]

        lines.append("")
        header = (f"  {'Timestamp':<20} {'Script':<12} {'Host':<25} {'Category':<20} "
                  f"{'Result':<22} {'Cdwn(s)':<8} {'Elapsed':<8} {'EID':<12}")
        lines.append(header)
        lines.append(f"  {'-'*20} {'-'*12} {'-'*25} {'-'*20} {'-'*22} {'-'*8} {'-'*8} {'-'*12}")

        for e in blocked:
            ts = self._get_ts(e)[:20]
            src = (e.get("script") or "?")[:12]
            full_host = e.get("host") or "?"
            host = full_host[:25]
            cat = (e.get("category") or "?")[:20]
            result = str(e.get("final_result") or "?")[:22]
            cd_sec = e.get("cooldown_seconds")
            cd_str = str(cd_sec) if cd_sec is not None else "N/A"
            elapsed = e.get("elapsed_seconds")
            elapsed_str = str(elapsed) if elapsed is not None else "N/A"
            eid = e["execution_id"][:12]
            lines.append(f"  {ts:<20} {src:<12} {host:<25} {cat:<20} "
                         f"{result:<22} {cd_str:<8} {elapsed_str:<8} {eid:<12}")
            self._append_detail_lines(lines, "Full Host", full_host, 25)

        lines.append("")
        return "\n".join(lines)

    # --- Section 7: Recovery bypass details ---

    def section_recovery(self):
        recov = [e for e in self.executions if not e.get("_skip") and e["recovery_bypass"]]
        if not recov:
            return ""

        limit = self.args.detail_limit
        recov.sort(key=lambda e: (self._get_ts(e) or "", e["execution_id"]))

        lines = []
        lines.append(self._make_separator("7. RECOVERY BYPASS DETAILS"))
        lines.append("")
        lines.append(f"  Showing {min(len(recov), limit)} of {len(recov)} records")

        if len(recov) > limit:
            lines.append(f"  (truncated to {limit})")
            recov = recov[-limit:]

        lines.append("")
        header = (f"  {'Timestamp':<20} {'Script':<12} {'Host':<25} {'Category':<20} "
                  f"{'Old':<8} {'New':<8} {'EID':<12}")
        lines.append(header)
        lines.append(f"  {'-'*20} {'-'*12} {'-'*25} {'-'*20} {'-'*8} {'-'*8} {'-'*12}")

        for e in recov:
            ts = self._get_ts(e)[:20]
            src = (e.get("script") or "?")[:12]
            full_host = e.get("host") or "?"
            host = full_host[:25]
            cat = (e.get("category") or "?")[:20]
            old = (e.get("old_state") or "?")[:8]
            new = (e.get("new_state") or "?")[:8]
            eid = e["execution_id"][:12]
            lines.append(f"  {ts:<20} {src:<12} {host:<25} {cat:<20} "
                         f"{old:<8} {new:<8} {eid:<12}")
            self._append_detail_lines(lines, "Full Host", full_host, 25)

        lines.append("")
        return "\n".join(lines)

    # --- Section 8: Adaptive recommendation summary ---

    def section_adaptive(self):
        lines = []
        lines.append(self._make_separator("8. ADAPTIVE COOLDOWN RECOMMENDATION"))
        lines.append("")

        if not self.adaptive_records:
            lines.append("  No adaptive cooldown recommendation found in the selected period.")
            lines.append("")
            return "\n".join(lines)

        lines.append(f"  {'Script':<12} {'Category':<20} {'Curr.Cdwn':<12} {'Rec.Cdwn':<12} "
                     f"{'Reduc.%':<10} {'Samples':<10} {'Days':<8}")
        lines.append(f"  {'-'*12} {'-'*20} {'-'*12} {'-'*12} {'-'*10} {'-'*10} {'-'*8}")

        for rec in self.adaptive_records:
            src = rec.get("_source", "?")[:12]
            cat = rec.get("category", "?")[:20]
            best = rec.get("best_candidate", "?")
            reduction = rec.get("expected_reduction", "?")
            samples = rec.get("samples", "?")
            days = rec.get("learning_days", "?")

            lines.append(f"  {src:<12} {cat:<20} {'3600s':<12} {str(best):<12} "
                         f"{str(reduction):<10} {str(samples):<10} {str(days):<8}")

        lines.append("")
        return "\n".join(lines)


    # --- Section 9: Recurring pattern analysis ---

    def section_recurring_patterns(self):
        """Section 9: Recurring pattern analysis across the selected period."""
        lines = []
        lines.append(self._make_separator("9. RECURRING PATTERN ANALYSIS"))
        lines.append("")

        valid_execs = [e for e in self.executions if not e.get("_skip")]
        has_current_period_execs = bool(valid_execs)

        if not has_current_period_execs:
            lines.append("  No executions in the current report period; "
                         "running pattern history analysis only.")
            lines.append("")

        any_pattern = False

        # ------------------------------------------------------------------
        # 9.1 Top noisy hosts
        # ------------------------------------------------------------------
        lines.append("")
        lines.append(self._make_sub_separator("9.1 Top Noisy Hosts"))
        lines.append("")

        host_counter = Counter()
        host_delivered = Counter()
        host_suppressed = Counter()
        host_recovery = Counter()
        host_cat = {}
        host_last_ts = {}

        for e in valid_execs:
            h = e.get("host", "unknown")
            host_counter[h] += 1
            if e.get("delivered"):
                host_delivered[h] += 1
            if e.get("suppressed"):
                host_suppressed[h] += 1
            if e.get("recovery_bypass"):
                host_recovery[h] += 1
            cat = e.get("category", "?")
            if h not in host_cat:
                host_cat[h] = cat
            if e.get("timestamps"):
                ts = e["timestamps"][0]
                if h not in host_last_ts or ts > host_last_ts[h]:
                    host_last_ts[h] = ts

        top_hosts = host_counter.most_common(15)
        if top_hosts:
            any_pattern = True
            lines.append(f"  {'Host':<30} {'Total':>6} {'Deliv.':>7} {'Suppr.':>7} "
                         f"{'Recov.':>7} {'Top Cat.':>20} {'Last Event':>20}")
            lines.append(f"  {'-'*30} {'-'*6} {'-'*7} {'-'*7} {'-'*7} {'-'*20} {'-'*20}")
            for host, cnt in top_hosts:
                if cnt < 2:
                    continue
                d = host_delivered.get(host, 0)
                s = host_suppressed.get(host, 0)
                r = host_recovery.get(host, 0)
                cat = host_cat.get(host, "?")[:20]
                last_ts = host_last_ts.get(host)
                last_ts_str = last_ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(last_ts, "strftime") else str(last_ts)[:20] if last_ts else ""
                lines.append(f"  {host:<30} {cnt:>6} {d:>7} {s:>7} {r:>7} "
                             f"{cat:>20} {last_ts_str[:20]:>20}")
        else:
            lines.append("  No hosts with significant activity found.")

        # ------------------------------------------------------------------
        # 9.2 Recurring transition candidates
        # ------------------------------------------------------------------
        lines.append("")
        lines.append(self._make_sub_separator("9.2 Recurring Transition Candidates"))
        lines.append("")
        lines.append("  These are repeated state transitions in the selected report period;")
        lines.append("  they are recurrence candidates, not necessarily Checkmk flapping events.")
        lines.append("")

        # Define opposite transition pairs
        OPPOSITE_MAP = {
            ("UP", "DOWN"): ("DOWN", "UP"),
            ("DOWN", "UP"): ("UP", "DOWN"),
            ("OK", "CRIT"): ("CRIT", "OK"),
            ("CRIT", "OK"): ("OK", "CRIT"),
            ("WARN", "OK"): ("OK", "WARN"),
            ("OK", "WARN"): ("WARN", "OK"),
            ("UP", "CRIT"): ("CRIT", "UP"),
            ("CRIT", "UP"): ("UP", "CRIT"),
        }

        # Group by (host, category) and sort by timestamp
        flap_groups = defaultdict(list)
        for e in valid_execs:
            h = e.get("host", "unknown")
            cat = e.get("category", "unknown")
            old = e.get("old_state")
            new = e.get("new_state")
            if old and new:
                key = (h, cat)
                ts = None
                if e.get("timestamps"):
                    ts = e["timestamps"][0]
                flap_groups[key].append((ts, old, new, e.get("script", "?"), e["execution_id"]))

        flap_results = []  # (host, cat, transition_count, examples)
        for (h, cat), transitions in flap_groups.items():
            # Sort by timestamp
            transitions.sort(key=lambda x: x[0] if x[0] else datetime.datetime.min)
            opp_count = 0
            examples = []
            for i in range(1, len(transitions)):
                prev = (transitions[i-1][1], transitions[i-1][2])
                curr = (transitions[i][1], transitions[i][2])
                if prev in OPPOSITE_MAP and OPPOSITE_MAP[prev] == curr:
                    opp_count += 1
                    if len(examples) < 3:
                        ts_str = transitions[i-1][0].strftime("%m-%d %H:%M") if transitions[i-1][0] else "?"
                        examples.append(f"{ts_str} {prev[0]}->{prev[1]} / {curr[0]}->{curr[1]}")

            if opp_count >= 2:
                flap_results.append((opp_count, h, cat, examples))

        flap_results.sort(key=lambda x: x[0], reverse=True)

        if flap_results:
            any_pattern = True
            lines.append(f"  {'Host':<30} {'Category':<20} {'Transitions':>11} {'Examples':<45}")
            lines.append(f"  {'-'*30} {'-'*20} {'-'*11} {'-'*45}")
            for cnt, h, cat, examples in flap_results[:10]:
                full_ex = "; ".join(examples)
                ex_str = full_ex[:45]
                lines.append(f"  {h:<30} {cat[:20]:<20} {cnt:>11} {ex_str:<45}")
                self._append_detail_lines(lines, "Full Examples", full_ex, 45)
        else:
            lines.append("  No recurring transition candidates detected in this period.")

        # ------------------------------------------------------------------
        # 9.3 Burst detection
        # ------------------------------------------------------------------
        lines.append("")
        lines.append(self._make_sub_separator("9.3 Burst Detection (5-minute window)"))
        lines.append("")

        BURST_WINDOW_MINUTES = 5

        # Collect all executions with their first timestamp
        timed_execs = []
        for e in valid_execs:
            ts = None
            if e.get("timestamps"):
                ts = e["timestamps"][0]
            if ts:
                timed_execs.append((ts, e))

        timed_execs.sort(key=lambda x: x[0])

        bursts = []
        if timed_execs:
            i = 0
            while i < len(timed_execs):
                window_start = timed_execs[i][0]
                window_end = window_start + datetime.timedelta(minutes=BURST_WINDOW_MINUTES)
                window_execs = []
                j = i
                while j < len(timed_execs) and timed_execs[j][0] <= window_end:
                    window_execs.append(timed_execs[j][1])
                    j += 1

                # Deduplicate hosts in this window
                hosts_in_window = set()
                cat_counter = Counter()
                deliv_in_window = 0
                suppr_in_window = 0
                recov_in_window = 0
                for we in window_execs:
                    h = we.get("host", "unknown")
                    hosts_in_window.add(h)
                    cat_counter[we.get("category", "unknown")] += 1
                    if we.get("delivered"):
                        deliv_in_window += 1
                    if we.get("suppressed"):
                        suppr_in_window += 1
                    if we.get("recovery_bypass"):
                        recov_in_window += 1

                num_hosts = len(hosts_in_window)
                if num_hosts >= 2:
                    dom_cat = cat_counter.most_common(1)[0][0] if cat_counter else "?"
                    host_examples = sorted(hosts_in_window)[:5]
                    bursts.append({
                        "window_start": window_start,
                        "window_end": window_end,
                        "hosts": num_hosts,
                        "dominant_cat": dom_cat,
                        "delivered": deliv_in_window,
                        "suppressed": suppr_in_window,
                        "recovery": recov_in_window,
                        "host_examples": host_examples,
                    })

                i = j

        if bursts:
            any_pattern = True
            # Merge overlapping bursts (where end of one overlaps start of next)
            # Actually, let's just deduplicate by sliding window more carefully
            merged_bursts = []
            for b in bursts:
                if not merged_bursts:
                    merged_bursts.append(b)
                else:
                    last = merged_bursts[-1]
                    if b["window_start"] <= last["window_end"]:
                        # Merge: extend the window, combine stats
                        last["window_end"] = b["window_end"]
                        last["hosts"] = max(last["hosts"], b["hosts"])
                        # Pick dominant cat from the larger window
                        # Recompute would be best, but just keep the larger
                        if b["hosts"] > last["hosts"]:
                            last["dominant_cat"] = b["dominant_cat"]
                        last["delivered"] += b["delivered"]
                        last["suppressed"] += b["suppressed"]
                        last["recovery"] += b["recovery"]
                        last["host_examples"] = sorted(set(last["host_examples"] + b["host_examples"]))[:5]
                    else:
                        merged_bursts.append(b)

            lines.append(f"  {'Window Start':<20} {'Window End':<20} {'Hosts':>6} "
                         f"{'Dom.Cat':<20} {'Deliv.':>7} {'Suppr.':>7} {'Recov.':>7} {'Examples':<30}")
            lines.append(f"  {'-'*20} {'-'*20} {'-'*6} "
                         f"{'-'*20} {'-'*7} {'-'*7} {'-'*7} {'-'*30}")
            for mb in merged_bursts[:10]:
                ws = mb["window_start"].strftime("%Y-%m-%d %H:%M")
                we = mb["window_end"].strftime("%Y-%m-%d %H:%M")
                full_ex = ", ".join(mb["host_examples"])
                ex = full_ex[:30]
                lines.append(f"  {ws:<20} {we:<20} {mb['hosts']:>6} "
                             f"{mb['dominant_cat'][:20]:<20} {mb['delivered']:>7} "
                             f"{mb['suppressed']:>7} {mb['recovery']:>7} {ex:<30}")
                self._append_detail_lines(lines, "Full Examples", full_ex, 30)
        else:
            lines.append("  No burst clusters detected in this period.")

        # ------------------------------------------------------------------
        # 9.4 Suppression-heavy hosts
        # ------------------------------------------------------------------
        lines.append("")
        lines.append(self._make_sub_separator("9.4 Suppression-Heavy Hosts"))
        lines.append("")

        # Group by host
        host_data = defaultdict(lambda: {"delivered": 0, "suppressed": 0, "category": "?"})
        for e in valid_execs:
            h = e.get("host", "unknown")
            host_data[h]["delivered"] += 1 if e.get("delivered") else 0
            host_data[h]["suppressed"] += 1 if e.get("suppressed") else 0
            cat = e.get("category", "?")
            if host_data[h]["category"] == "?" or cat != "?":
                host_data[h]["category"] = cat

        sup_heavy = []
        for h, data in host_data.items():
            d = data["delivered"]
            s = data["suppressed"]
            if s > 0 and d > 0:
                ratio = s / d
                sup_heavy.append((ratio, s, d, h, data["category"]))

        sup_heavy.sort(key=lambda x: x[0], reverse=True)

        if sup_heavy:
            any_pattern = True
            lines.append(f"  {'Host':<30} {'Category':<20} {'Suppressed':>10} {'Delivered':>10} {'Ratio':>8}")
            lines.append(f"  {'-'*30} {'-'*20} {'-'*10} {'-'*10} {'-'*8}")
            for ratio, s, d, h, cat in sup_heavy[:10]:
                lines.append(f"  {h:<30} {cat[:20]:<20} {s:>10} {d:>10} {ratio:>7.1f}x")
        else:
            lines.append("  No suppression-heavy hosts detected (need both suppressed and delivered > 0).")

        # ------------------------------------------------------------------
        # 9.5 Recovery-heavy hosts
        # ------------------------------------------------------------------
        lines.append("")
        lines.append(self._make_sub_separator("9.5 Recovery-Heavy Hosts"))
        lines.append("")

        # Group by host
        host_recovery_data = defaultdict(lambda: {"recovery": 0, "delivered": 0, "suppressed": 0, "category": "?"})
        for e in valid_execs:
            h = e.get("host", "unknown")
            host_recovery_data[h]["recovery"] += 1 if e.get("recovery_bypass") else 0
            host_recovery_data[h]["delivered"] += 1 if e.get("delivered") else 0
            host_recovery_data[h]["suppressed"] += 1 if e.get("suppressed") else 0
            cat = e.get("category", "?")
            if host_recovery_data[h]["category"] == "?" or cat != "?":
                host_recovery_data[h]["category"] = cat

        recov_heavy = []
        for h, data in host_recovery_data.items():
            r = data["recovery"]
            if r > 0:
                recov_heavy.append((r, h, data["category"], data["delivered"], data["suppressed"]))

        recov_heavy.sort(key=lambda x: x[0], reverse=True)

        if recov_heavy:
            any_pattern = True
            lines.append(f"  {'Host':<30} {'Category':<20} {'Recov.':>7} {'Deliv.':>7} {'Suppr.':>7}")
            lines.append(f"  {'-'*30} {'-'*20} {'-'*7} {'-'*7} {'-'*7}")
            for r, h, cat, d, s in recov_heavy[:10]:
                lines.append(f"  {h:<30} {cat[:20]:<20} {r:>7} {d:>7} {s:>7}")
        else:
            lines.append("  No recovery-heavy hosts detected in this period.")

        # ------------------------------------------------------------------
        # 9.6 Time-of-Day Recurrence Insights
        # ------------------------------------------------------------------
        lines.append("")
        lines.append(self._make_sub_separator("9.6 Time-of-Day Recurrence Insights"))
        lines.append("")

        history_execs = getattr(self, "pattern_history_execs", [])
        phs = self.args.pattern_history_start
        phe = self.args.window_end
        lines.append(f"  Pattern history period: {phs.strftime('%Y-%m-%d %H:%M')} — "
                     f"{phe.strftime('%Y-%m-%d %H:%M')} "
                     f"({self.args.pattern_history_days} days, "
                     f"{len(history_execs)} total executions)")
        lines.append("")

        def _half_hour_bucket(dt):
            """Round timestamp to nearest half-hour (±15 min tolerance)."""
            if dt.minute < 15:
                return dt.replace(minute=0, second=0, microsecond=0)
            elif dt.minute < 45:
                return dt.replace(minute=30, second=0, microsecond=0)
            else:
                return (dt + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

        # Collect time-of-day patterns from history executions
        # key = (host, category, transition, bucket) -> set of day strings
        pattern_days = defaultdict(set)
        pattern_timestamps = defaultdict(list)

        for e in history_execs:
            if not e.get("timestamps"):
                continue
            ts = e["timestamps"][0]
            if not hasattr(ts, "strftime"):
                continue
            h = e.get("host", "unknown")
            cat = e.get("category", "unknown")
            old = e.get("old_state", "")
            new = e.get("new_state", "")
            if not old or not new:
                continue
            transition = f"{old}->{new}"
            bucket = _half_hour_bucket(ts)
            day_key = ts.strftime("%Y-%m-%d")
            key = (h, cat, transition, bucket)
            pattern_days[key].add(day_key)
            if ts not in pattern_timestamps[key]:
                pattern_timestamps[key].append(ts)

        # Separate confirmed (>= 2 days) from insufficient (single day)
        confirmed = {}
        insufficient = {}
        for key, days in pattern_days.items():
            if len(days) >= 2:
                confirmed[key] = {
                    "days": days,
                    "timestamps": pattern_timestamps[key],
                }
            else:
                insufficient[key] = {
                    "days": days,
                    "timestamps": pattern_timestamps[key],
                }

        # Helper: convert bucket (datetime) to time string
        def _bucket_time(bucket):
            return bucket.strftime("%H:%M")

        # Helper: interpret transition
        INTERPRETATION_MAP = {
            "UP->DOWN": "possible scheduled shutdown",
            "DOWN->UP": "possible startup after scheduled downtime",
            "OK->CRIT": "possible unstable connectivity",
            "CRIT->OK": "possible recovery after incident",
            "OK->WARN": "possible performance degradation pattern",
            "WARN->OK": "possible recovery from degraded state",
            "UP->CRIT": "possible device reboot or power issue",
            "CRIT->UP": "possible recovery after reboot",
        }

        def _interpret(transition):
            return INTERPRETATION_MAP.get(transition, "possible recurring state change")

        # -- confirmed patterns --
        lines.append("")
        lines.append("  Confirmed recurring patterns (same host/category/transition "
                     "at same time on ≥ 2 different days):")
        lines.append("")

        if confirmed:
            any_pattern = True
            # Sort: most days first, then most total observations
            sorted_confirmed = sorted(
                confirmed.items(),
                key=lambda x: (len(x[1]["days"]), len(x[1]["timestamps"])),
                reverse=True,
            )

            lines.append(
                f"  {'Host':<28} {'Category':<22} {'Transition':<16} "
                f"{'Time':>8} {'Days':>5} {'Obs.':>5} {'Conf.':>10} "
                f"{'First':<12} {'Last':<12} {'Interpretation':<35}"
            )
            lines.append(
                f"  {'-'*28} {'-'*22} {'-'*16} "
                f"{'-'*8} {'-'*5} {'-'*5} {'-'*10} "
                f"{'-'*12} {'-'*12} {'-'*35}"
            )

            for (h, cat, transition, bucket), info in sorted_confirmed:
                day_count = len(info["days"])
                all_ts = sorted(info["timestamps"])
                obs_count = len(all_ts)
                if day_count >= 5:
                    confidence = "high"
                elif day_count >= 3:
                    confidence = "medium"
                else:
                    confidence = "low"
                first_seen = all_ts[0].strftime("%Y-%m-%d")
                last_seen = all_ts[-1].strftime("%Y-%m-%d")
                btime = _bucket_time(bucket)
                interp = _interpret(transition)

                lines.append(
                    f"  {h:<28} {cat[:22]:<22} {transition:<16} "
                    f"{btime:>8} {day_count:>5} {obs_count:>5} {confidence:>10} "
                    f"{first_seen:<12} {last_seen:<12} {interp:<35}"
                )
        else:
            lines.append("  No confirmed recurring patterns found in the historical period.")
        lines.append("")

        # -- operational recurring candidates from current report period --
        lines.append("")
        lines.append("  Operational recurring candidates (host/category/transition in current "
                     "report period, insufficient evidence yet):")
        lines.append("")

        # Build set of already-confirmed (host, category, transition) to exclude candidates
        confirmed_set = set()
        for (h, cat, transition, _bucket), _info in confirmed.items():
            confirmed_set.add((h, cat, transition))

        candidates = []
        for e in valid_execs:
            if not e.get("timestamps"):
                continue
            ts = e["timestamps"][0]
            if not hasattr(ts, "strftime"):
                continue
            h = e.get("host", "unknown")
            cat = e.get("category", "unknown")
            old = e.get("old_state", "")
            new = e.get("new_state", "")
            if not old or not new:
                continue
            transition = f"{old}->{new}"
            pattern_key = (h, cat, transition)
            if pattern_key in confirmed_set:
                continue  # already reported as confirmed
            bucket = _half_hour_bucket(ts)
            hist_key = (h, cat, transition, bucket)
            hist_days = pattern_days.get(hist_key, set())
            candidates.append({
                "host": h,
                "category": cat,
                "transition": transition,
                "timestamp": ts,
                "hist_days": len(hist_days),
            })

        if candidates:
            any_pattern = True
            # Deduplicate: keep the most recent timestamp per (host, cat, transition)
            seen_candidates = {}
            for c in candidates:
                ck = (c["host"], c["category"], c["transition"])
                if ck not in seen_candidates or c["timestamp"] > seen_candidates[ck]["timestamp"]:
                    seen_candidates[ck] = c
            unique_candidates = sorted(
                seen_candidates.values(),
                key=lambda x: x["timestamp"],
                reverse=True,
            )

            lines.append(
                f"  {'Host':<28} {'Category':<22} {'Transition':<16} "
                f"{'Timestamp':<20} {'Hist.Days':>9} {'Status':<12} {'Interpretation':<35}"
            )
            lines.append(
                f"  {'-'*28} {'-'*22} {'-'*16} "
                f"{'-'*20} {'-'*9} {'-'*12} {'-'*35}"
            )

            for c in unique_candidates[:15]:
                interp = _interpret(c["transition"])
                lines.append(
                    f"  {c['host']:<28} {c['category'][:22]:<22} {c['transition']:<16} "
                    f"{c['timestamp'].strftime('%Y-%m-%d %H:%M'):<20} "
                    f"{c['hist_days']:>9} {'candidate':<12} {interp:<35}"
                )
        else:
            lines.append("  No operational recurring candidates observed in the current report period.")
        lines.append("")

        # -- insufficient evidence summary --
        if insufficient:
            any_pattern = True
            lines.append("")
            lines.append("  Patterns with insufficient evidence (single day in history, "
                         "not in current report period):")
            lines.append("")
            sorted_insuff = sorted(
                insufficient.items(),
                key=lambda x: len(x[1]["timestamps"]),
                reverse=True,
            )
            for (h, cat, transition, bucket), info in sorted_insuff[:5]:
                btime = _bucket_time(bucket)
                obs = len(info["timestamps"])
                day_str = ", ".join(sorted(info["days"]))
                lines.append(
                    f"    {h:<28} {cat[:22]:<22} {transition:<16} "
                    f"{btime:>8}  {obs} obs on {day_str}"
                )
            lines.append("")

        # Summary verdict for 9.6
        confirmed_count = len(confirmed)
        candidate_count = len([c for c in candidates if (c['host'], c['category'], c['transition']) not in confirmed_set])
        insufficient_count = len(insufficient)
        lines.append("")
        lines.append(f"  9.6 Summary: {confirmed_count} confirmed recurring, "
                     f"{candidate_count} operational candidates, {insufficient_count} insufficient-evidence patterns")
        lines.append("")

        # If no patterns at all
        if not any_pattern:
            lines.append("")
            lines.append("  No confirmed recurring patterns detected yet.")
            lines.append("  Operational recurring candidates require more historical days for confirmation.")

        lines.append("")
        return "\n".join(lines)

        # --- Section 10: Data quality ---

    def section_data_quality(self):
        lines = []
        lines.append(self._make_separator("10. DATA QUALITY"))
        lines.append("")

        # Files read
        lines.append(f"  Files read ({len(self.dq.files_read)} total):")
        if self.dq.files_read:
            for f in self.dq.files_read:
                lines.append(f"    ✓ {f}")
        else:
            lines.append("    (none)")
        lines.append("")

        # Files missing
        lines.append(f"  Files missing ({len(self.dq.missing_files)} total):")
        if self.dq.missing_files:
            for f in self.dq.missing_files:
                lines.append(f"    ✗ {f}")
        else:
            lines.append("    (none)")
        lines.append("")

        # Parse statistics
        lines.append("  Parse statistics:")
        lines.append(f"    • Malformed JSON lines:    {self.dq.bad_json_records}")
        lines.append(f"    • Records outside period:  {self.dq.outside_period}")
        lines.append(f"    • Unknown event types:     {len(self.dq.unknown_events)}")
        if self.dq.unknown_events:
            for ev, cnt in self.dq.unknown_events.most_common():
                lines.append(f"      - {ev}: {cnt}")
        lines.append("")

        # Execution statistics
        lines.append("  Execution normalization:")
        exec_host_unknown = sum(1 for e in self.executions if e.get("host") == "unknown" and not e.get("_skip"))
        exec_cat_unknown = sum(1 for e in self.executions if e.get("category") == "unknown" and not e.get("_skip"))
        exec_missing_eid = sum(1 for e in self.executions if e["execution_id"].startswith("noeid_"))
        lines.append(f"    • Executions with unknown host:     {exec_host_unknown}")
        lines.append(f"    • Executions with unknown category: {exec_cat_unknown}")
        lines.append(f"    • Executions with synthetic EID:    {exec_missing_eid}")
        lines.append("")

        return "\n".join(lines)

    # --- Assemble full report ---

    def _calculate_report_width(self, lines):
        """Calculate the maximum visible line width in the report.

        Returns the bounded width: min(MAX_REPORT_WIDTH, max(MIN_REPORT_WIDTH, max_content_width))
        """
        max_width = MIN_REPORT_WIDTH
        for line in lines:
            # Ignore separator lines (all = or all -)
            if line and set(line) in ({"="}, {"-"}):
                continue
            # Calculate visible length (without trailing newline)
            visible_len = len(line.rstrip())
            max_width = max(max_width, visible_len)
        # Apply bounded width formula
        return min(MAX_REPORT_WIDTH, max(MIN_REPORT_WIDTH, max_width))

    def _adjust_separators_to_computed_width(self, report_text):
        """Replace separator lines with dynamic width based on actual report content."""
        lines = report_text.split("\n")

        # Compute maximum content width (excluding separator lines)
        computed_width = self._calculate_report_width(lines)

        # Replace separator lines with correct width
        adjusted_lines = []
        for line in lines:
            # Check if line is a pure separator (all = or all -)
            if line and set(line) == {"="}:
                # Main separator
                adjusted_lines.append("=" * computed_width)
            elif line and set(line) == {"-"}:
                # Subsection separator
                adjusted_lines.append("-" * computed_width)
            else:
                # Regular content line
                adjusted_lines.append(line)

        return "\n".join(adjusted_lines)

    def generate_text(self):
        parts = [
            self.section_executive_summary(),
            self.section_per_script(),
            self.section_per_host(),
            self.section_per_category(),
            self.section_detailed_events(),
            self.section_blocked(),
            self.section_recovery(),
            self.section_adaptive(),
            self.section_recurring_patterns(),
            self.section_data_quality(),
        ]
        report_text = "\n".join(parts)
        return self._adjust_separators_to_computed_width(report_text)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Checkmk notification limiter report generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Log paths
    parser.add_argument("--mail-log", default=None,
                        help="Path to mail-20.log (default: production path)")
    parser.add_argument("--telegram-log", default=None,
                        help="Path to telegram-20.log (default: production path)")

    # Time window
    parser.add_argument("--since-hours", type=float, default=DEFAULT_SINCE_HOURS,
                        help="Hours to look back from --to or now (default: %(default)s)")
    parser.add_argument("--from", dest="from_ts", default=None,
                        help="Explicit window start: YYYY-MM-DDTHH:MM:SS")
    parser.add_argument("--to", dest="to_ts", default=None,
                        help="Explicit window end: YYYY-MM-DDTHH:MM:SS (default: now)")

    # Pattern history
    parser.add_argument("--pattern-history-days", type=int, default=DEFAULT_PATTERN_HISTORY_DAYS,
                        help="Days to look back for time-of-day recurrence analysis in section 9.6 "
                             "(default: %(default)s, range 1-30)")

    # Email
    parser.add_argument("--to-email", default=None,
                        help="Recipient email address")
    parser.add_argument("--from-email", default=None,
                        help="Sender email address (default: %(default)s)")
    parser.add_argument("--subject-prefix", default=None,
                        help="Subject line prefix (default: [Checkmk] Notification limiter report)")

    # Output
    parser.add_argument("--detail-limit", type=int, default=DEFAULT_DETAIL_LIMIT,
                        help="Max rows in detail tables (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print report to stdout, don't send email")
    parser.add_argument("--output", default=None,
                        help="Write report to file")
    parser.add_argument("--format", choices=("text", "json"), default="text",
                        help="Report format (default: %(default)s)")

    args = parser.parse_args(argv)

    # Resolve log paths
    if args.mail_log is None:
        args.mail_log = DEFAULT_LOG_PATHS["mail"]
    if args.telegram_log is None:
        args.telegram_log = DEFAULT_LOG_PATHS["telegram"]

    # Resolve email
    if args.to_email is None:
        args.to_email = os.environ.get("NOTIFICATION_REPORT_TO")
    if args.from_email is None:
        args.from_email = os.environ.get("NOTIFICATION_REPORT_FROM", DEFAULT_FROM_EMAIL)
    if args.subject_prefix is None:
        args.subject_prefix = os.environ.get("NOTIFICATION_REPORT_SUBJECT_PREFIX",
                                              "[Checkmk] Notification limiter report")

    # Resolve time window
    now = datetime.datetime.now()
    if args.to_ts:
        try:
            args.window_end = datetime.datetime.strptime(args.to_ts, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            parser.error(f"Invalid --to format: {args.to_ts!r} (use YYYY-MM-DDTHH:MM:SS)")
    else:
        args.window_end = now

    if args.from_ts:
        try:
            args.window_start = datetime.datetime.strptime(args.from_ts, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            parser.error(f"Invalid --from format: {args.from_ts!r} (use YYYY-MM-DDTHH:MM:SS)")
    else:
        args.window_start = args.window_end - datetime.timedelta(hours=args.since_hours)

    # Validate pattern history days
    if args.pattern_history_days < 1 or args.pattern_history_days > 30:
        parser.error("--pattern-history-days must be between 1 and 30")
    args.pattern_history_start = args.window_end - datetime.timedelta(days=args.pattern_history_days)

    # Validate
    if not args.dry_run and not args.to_email:
        parser.error("No recipient configured. Use --to-email or set NOTIFICATION_REPORT_TO "
                      "environment variable, or use --dry-run to preview.")

    return args


# ---------------------------------------------------------------------------
# Email delivery
# ---------------------------------------------------------------------------


def send_email(to_addr, from_addr, subject, body):
    """Send email via /usr/sbin/sendmail -t."""
    msg = (
        f"To: {to_addr}\n"
        f"From: {from_addr}\n"
        f"Subject: {subject}\n"
        "Content-Type: text/plain; charset=UTF-8\n"
        "\n"
        f"{body}\n"
    )
    try:
        proc = subprocess.run(
            ["/usr/sbin/sendmail", "-t"],
            input=msg.encode("utf-8"),
            timeout=30,
        )
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        print("sendmail timeout", file=sys.stderr)
        return False
    except FileNotFoundError:
        print("/usr/sbin/sendmail not found", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"sendmail error: {exc}", file=sys.stderr)
        return False


def main(argv=None):
    args = parse_args(argv)

    # ---- Parse logs ----
    dq = DataQuality()

    # Use channel discovery for default paths, single-file mode for custom overrides
    if args.mail_log == DEFAULT_LOG_PATHS["mail"]:
        mail_stats = parse_log_channel(args.mail_log, "M@il-20", dq)
    else:
        mail_stats = parse_log_file(args.mail_log, "M@il-20", dq)

    if args.telegram_log == DEFAULT_LOG_PATHS["telegram"]:
        telegram_stats = parse_log_channel(args.telegram_log, "Telegram-20", dq)
    else:
        telegram_stats = parse_log_file(args.telegram_log, "Telegram-20", dq)

    dq.add_bad_json(mail_stats.bad_json + telegram_stats.bad_json)

    all_records = mail_stats.records + telegram_stats.records

    # ---- Filter by time window ----
    filtered = []
    for rec in all_records:
        if in_window(rec, args.window_start, args.window_end):
            filtered.append(rec)
        else:
            dq.outside_period += 1

    # ---- Filter for pattern history ----
    pattern_records = []
    for rec in all_records:
        if in_window(rec, args.pattern_history_start, args.window_end):
            pattern_records.append(rec)

    # ---- Build pattern history engine ----
    pattern_engine = None
    if args.pattern_history_days > 0 and pattern_records:
        pattern_engine = ReportEngine(pattern_records, args)

    # ---- Build report ----
    engine = ReportEngine(filtered, args, dq=dq, pattern_engine=pattern_engine)
    # dq is now passed directly to ReportEngine

    report_body = engine.generate_text()

    # ---- Output ----
    if args.format == "json":
        # Simplified JSON output — structure matches the text sections
        report_body = json.dumps({
            "version": SCRIPT_NAME,
            "generated_at": datetime.datetime.now().isoformat(),
            "period": {
                "start": args.window_start.isoformat(),
                "end": args.window_end.isoformat(),
            },
            "summary": {
                "total_executions": engine.total_executions,
                "delivered": engine.delivered_count,
                "would_suppress": engine.would_suppress_count,
                "suppressed": engine.suppressed_count,
                "recovery": engine.recovery_count,
                "errors": engine.error_count,
            },
        }, indent=2)

    if args.dry_run:
        print(report_body)

    if args.output:
        Path(args.output).write_text(report_body, encoding="utf-8")

    if not args.dry_run:
        subject = f"{args.subject_prefix} - {args.window_start.strftime('%Y-%m-%d %H:%M')}"
        success = send_email(args.to_email, args.from_email, subject, report_body)
        if not success:
            print("Failed to send email", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
