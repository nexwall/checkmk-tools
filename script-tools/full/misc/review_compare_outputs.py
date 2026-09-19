#!/usr/bin/env python3
"""review_compare_outputs.py - Compare two variants of CheckMK local checks.

Runs an "original" and a "beta"/candidate version of each same-named
NethSecurity 8.8 local check, captures stdout/stderr/exit code/duration, and
produces comparison reports.

There is no permanent "beta" directory in this repo (script-check-nsec8/
only has full/ and doc/, matching every other script-check-* directory) -
--beta-dir must point at wherever you've staged the candidate version for
this one-off comparison (e.g. a temp directory with modified copies).

Exit codes:
  0 = all pairs identical, equivalent, or expected differences
  1 = one or more unexpected differences
  2 = runner error, invalid arguments, missing directories
  3 = one or more scripts timed out or blocked
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.0.2"
TOOL_NAME = "review_compare_outputs"

# Paths
# This file lives at <repo>/script-tools/full/misc/review_compare_outputs.py -
# a generic QA/diffing tool, not a NethSecurity-specific check itself, so it
# doesn't live alongside the scripts it compares. Default --original-dir
# still targets script-check-nsec8/full since that's the primary use case
# this tool was built for; pass --original-dir explicitly to compare a
# different script set.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ORIGINAL_DIR_DEFAULT = REPO_ROOT / "script-check-nsec8" / "full"
OUTPUT_DIR_DEFAULT = Path("/tmp/nethsecurity-checkmk-beta-review")

# Files to exclude from pairing
EXCLUDE_PATTERNS = (
    "README.md",
    "REVIEW-BETA-DIFFERENCES.md",
    "review_compare_outputs.py",
    "__pycache__",
)
EXCLUDE_DIRS = ("__pycache__", ".gitignore")

# Sensitive patterns for redaction
SENSITIVE_PATTERNS = re.compile(
    r"(token|password|secret|api_key|authorization|bearer)\s*[=:]\s*\S+",
    re.IGNORECASE,
)


def redact(text):
    """Redact obvious secrets from output."""
    return SENSITIVE_PATTERNS.sub(r"\1 = [REDACTED]", text)


def discover_pairs(orig_dir, beta_dir):
    """Find same-name original/beta pairs."""
    orig_files = {}
    for f in orig_dir.iterdir():
        if f.suffix == ".py" and f.name not in EXCLUDE_PATTERNS:
            orig_files[f.name] = f

    pairs = []
    betas = set()
    for f in beta_dir.iterdir():
        if f.suffix == ".py" and f.name not in EXCLUDE_PATTERNS:
            betas.add(f.name)
            if f.name in orig_files:
                pairs.append({
                    "name": f.name,
                    "original": str(orig_files[f.name]),
                    "beta": str(f),
                    "pair_found": True,
                })
            else:
                pairs.append({
                    "name": f.name,
                    "original": None,
                    "beta": str(f),
                    "pair_found": False,
                    "note": "beta without original",
                })

    for name, path in sorted(orig_files.items()):
        if name not in betas:
            pairs.append({
                "name": name,
                "original": str(path),
                "beta": None,
                "pair_found": False,
                "note": "original without beta",
            })

    pairs.sort(key=lambda p: p["name"])
    return pairs


def run_script(script_path, timeout=30):
    """Run a script and capture output. Returns dict with results."""
    result = {
        "script": str(script_path),
        "basename": Path(script_path).name,
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "duration_ms": 0,
        "timeout": False,
        "exception": None,
        "parsed_services": [],
    }

    if script_path is None:
        result["exception"] = "No script path provided"
        return result

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    start = time.perf_counter()
    try:
        p = subprocess.run(
            [sys.executable, "-B", str(script_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        result["exit_code"] = p.returncode
        result["stdout"] = redact(p.stdout)
        result["stderr"] = redact(p.stderr)
    except subprocess.TimeoutExpired:
        result["exit_code"] = -1
        result["timeout"] = True
        result["stderr"] = f"TIMEOUT after {timeout}s"
    except Exception as e:
        result["exit_code"] = -1
        result["exception"] = str(e)
    finally:
        result["duration_ms"] = int((time.perf_counter() - start) * 1000)

    # Parse CheckMK local-check output
    result["parsed_services"] = parse_checkmk_output(result["stdout"])
    return result


def parse_checkmk_output(text):
    """Parse CheckMK local-check output lines."""
    services = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Format: <STATE> <SERVICE> [perfdata] - <summary>
        m = re.match(
            r"^(\d)\s+"
            r'("(?:[^"\\]|\\.)*"|\S+)\s+'
            r"(.*)$",
            line,
        )
        if m:
            services.append({
                "state": int(m.group(1)),
                "service": m.group(2).strip('"'),
                "rest": m.group(3).strip(),
                "raw": line,
            })
        else:
            services.append({
                "state": None,
                "service": None,
                "rest": line,
                "raw": line,
                "parse_error": True,
            })
    return services


def compare_services(orig_services, beta_services):
    """Compare parsed services from original and beta."""
    diffs = []
    max_len = max(len(orig_services), len(beta_services))

    for i in range(max_len):
        o = orig_services[i] if i < len(orig_services) else None
        b = beta_services[i] if i < len(beta_services) else None

        if o is None and b is not None:
            diffs.append({"index": i, "type": "BETA_EXTRA", "beta": b["raw"]})
            continue
        if o is not None and b is None:
            diffs.append({"index": i, "type": "ORIG_EXTRA", "original": o["raw"]})
            continue

        diff = {"index": i, "type": "IDENTICAL"}
        if o["state"] != b["state"]:
            diff["type"] = "STATE_DIFF"
            diff["orig_state"] = o["state"]
            diff["beta_state"] = b["state"]
        if o["service"] != b["service"]:
            diff["type"] = diff["type"] if diff["type"] != "IDENTICAL" else "SERVICE_DIFF"
            diff["orig_service"] = o["service"]
            diff["beta_service"] = b["service"]
        if o["raw"] != b["raw"]:
            if diff["type"] == "IDENTICAL":
                diff["type"] = "OUTPUT_DIFF"
            diff["orig_raw"] = o["raw"]
            diff["beta_raw"] = b["raw"]

        diffs.append(diff)

    return diffs


def classify_result(result_orig, result_beta):
    """Classify comparison result."""
    if result_orig["exception"] and result_beta["exception"]:
        return "BOTH_FAILED"
    if result_orig["timeout"] or result_beta["timeout"]:
        return "TIMEOUT"
    if result_orig["exception"]:
        return "ORIGINAL_FAILED"
    if result_beta["exception"]:
        return "BETA_FAILED"
    if result_orig["exit_code"] != 0 and result_beta["exit_code"] != 0:
        return "BOTH_FAILED"

    diffs = compare_services(
        result_orig.get("parsed_services", []),
        result_beta.get("parsed_services", []),
    )
    significant = [d for d in diffs if d["type"] != "IDENTICAL"]
    if not significant:
        return "IDENTICAL"
    return "DIFFERENT"


def run_comparison(pairs, timeout=30):
    """Run all pairs and return comparison results."""
    results = []
    for pair in pairs:
        if not pair["pair_found"]:
            results.append({
                "name": pair["name"],
                "pair_found": False,
                "note": pair.get("note", ""),
                "classification": "BLOCKED",
            })
            continue

        orig_result = run_script(pair["original"], timeout)
        beta_result = run_script(pair["beta"], timeout)
        classification = classify_result(orig_result, beta_result)

        results.append({
            "name": pair["name"],
            "pair_found": True,
            "original": orig_result,
            "beta": beta_result,
            "classification": classification,
            "differences": compare_services(
                orig_result.get("parsed_services", []),
                beta_result.get("parsed_services", []),
            ),
        })
    return results


def generate_markdown_report(comparison, output_dir):
    """Generate Markdown comparison report."""
    lines = []
    lines.append("# Output Comparison Report")
    lines.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    lines.append(f"\n## Summary\n")
    counts = {}
    for r in comparison:
        c = r.get("classification", "UNKNOWN")
        counts[c] = counts.get(c, 0) + 1

    lines.append("| Classification | Count |")
    lines.append("|---|---|")
    for c, n in sorted(counts.items()):
        lines.append(f"| {c} | {n} |")

    lines.append(f"\n## Per-script Details\n")
    for r in comparison:
        lines.append(f"### {r['name']}\n")
        lines.append(f"**Classification**: {r.get('classification', 'N/A')}\n")
        if not r.get("pair_found"):
            lines.append(f"**Note**: {r.get('note', '')}\n")
            continue

        o = r.get("original", {})
        b = r.get("beta", {})

        lines.append(f"**Original**: exit={o.get('exit_code')}, "
                      f"duration={o.get('duration_ms')}ms, "
                      f"services={len(o.get('parsed_services', []))}")
        lines.append(f"\n```")
        lines.append(o.get("stdout", "").strip()[:500])
        lines.append("```\n")

        lines.append(f"**Beta**: exit={b.get('exit_code')}, "
                      f"duration={b.get('duration_ms')}ms, "
                      f"services={len(b.get('parsed_services', []))}")
        lines.append(f"\n```")
        lines.append(b.get("stdout", "").strip()[:500])
        lines.append("```\n")

        diffs = r.get("differences", [])
        significant = [d for d in diffs if d["type"] != "IDENTICAL"]
        if significant:
            lines.append(f"**Differences ({len(significant)}):**\n")
            for d in significant:
                lines.append(f"- [{d['type']}] line {d['index']}")
                if "orig_raw" in d:
                    lines.append(f"  Original: `{d['orig_raw'][:120]}`")
                if "beta_raw" in d:
                    lines.append(f"  Beta: `{d['beta_raw'][:120]}`")
            lines.append("")
        else:
            lines.append("**No significant differences.**\n")

    report = "\n".join(lines)
    md_path = output_dir / "comparison-report.md"
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path.write_text(report)
    return md_path


def generate_json_report(comparison, output_dir):
    """Generate JSON comparison report."""
    report = {
        "tool": TOOL_NAME,
        "version": VERSION,
        "timestamp": datetime.now().isoformat(),
        "results": [],
    }
    for r in comparison:
        entry = {
            "name": r["name"],
            "pair_found": r.get("pair_found", False),
            "classification": r.get("classification", "UNKNOWN"),
        }
        if r.get("original"):
            o = r["original"]
            entry["original"] = {
                "exit_code": o.get("exit_code"),
                "duration_ms": o.get("duration_ms"),
                "stdout": o.get("stdout", ""),
                "stderr": o.get("stderr", ""),
                "timeout": o.get("timeout", False),
            }
        if r.get("beta"):
            b = r["beta"]
            entry["beta"] = {
                "exit_code": b.get("exit_code"),
                "duration_ms": b.get("duration_ms"),
                "stdout": b.get("stdout", ""),
                "stderr": b.get("stderr", ""),
                "timeout": b.get("timeout", False),
            }
        if r.get("differences"):
            entry["differences"] = [
                d for d in r["differences"] if d["type"] != "IDENTICAL"
            ]
        report["results"].append(entry)

    json_path = output_dir / "comparison-report.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2))
    return json_path


def save_raw_outputs(comparison, output_dir):
    """Save raw stdout/stderr per script."""
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for r in comparison:
        if not r.get("pair_found"):
            continue
        name = r["name"].replace(".py", "")
        for variant in ("original", "beta"):
            data = r.get(variant, {})
            if data.get("stdout"):
                (raw_dir / f"{name}_{variant}.stdout").write_text(data["stdout"])
            if data.get("stderr"):
                (raw_dir / f"{name}_{variant}.stderr").write_text(data["stderr"])


def list_pairs(pairs):
    """Print pair listing."""
    print(f"{'Name':40s} {'Original':12s} {'Beta':12s} {'Status'}")
    print("-" * 80)
    for p in pairs:
        o = "EXISTS" if p["original"] else "MISSING"
        b = "EXISTS" if p["beta"] else "MISSING"
        status = "PAIR" if o == "EXISTS" and b == "EXISTS" else p.get("note", "MISMATCH")
        print(f"{p['name']:40s} {o:12s} {b:12s} {status}")


def main():
    p = argparse.ArgumentParser(
        description=f"{TOOL_NAME} v{VERSION} — Compare original vs beta CheckMK scripts"
    )
    p.add_argument("--script", help="Run comparison for a single script name only")
    p.add_argument("--all", action="store_true", help="Run comparison for all paired scripts")
    p.add_argument("--original-dir", default=str(ORIGINAL_DIR_DEFAULT),
                   help=f"Original scripts directory (default: {ORIGINAL_DIR_DEFAULT})")
    p.add_argument("--beta-dir", default=None,
                   help="Beta/candidate scripts directory (required - no permanent "
                        "beta/ directory exists in this repo, point this at wherever "
                        "you've staged the candidate version for this comparison)")
    p.add_argument("--output-dir", default=str(OUTPUT_DIR_DEFAULT),
                   help=f"Output directory (default: {OUTPUT_DIR_DEFAULT})")
    p.add_argument("--timeout", type=int, default=30, help="Per-script timeout in seconds")
    p.add_argument("--json", action="store_true", help="Generate JSON report")
    p.add_argument("--markdown", action="store_true", help="Generate Markdown report")
    p.add_argument("--list", action="store_true", help="List discovered pairs and exit")
    p.add_argument("--fail-on-difference", action="store_true",
                   help="Exit with code 1 on any difference")
    args = p.parse_args()

    orig_dir = Path(args.original_dir)
    output_dir = Path(args.output_dir)

    if args.beta_dir is None:
        print("ERROR: --beta-dir is required (no permanent beta/ directory exists "
              "in this repo)", file=sys.stderr)
        return 2
    beta_dir = Path(args.beta_dir)

    if not orig_dir.is_dir():
        print(f"ERROR: original directory not found: {orig_dir}", file=sys.stderr)
        return 2
    if not beta_dir.is_dir():
        print(f"ERROR: beta directory not found: {beta_dir}", file=sys.stderr)
        return 2

    pairs = discover_pairs(orig_dir, beta_dir)

    if args.list:
        list_pairs(pairs)
        return 0

    # Filter by script name if --script given
    if args.script:
        pairs = [p for p in pairs if p["name"] == args.script]
        if not pairs:
            print(f"ERROR: script '{args.script}' not found in pairs", file=sys.stderr)
            return 2

    # Run comparison
    print(f"Running comparison for {len(pairs)} pair(s)...")
    comparison = run_comparison(pairs, timeout=args.timeout)

    # Generate reports
    output_dir.mkdir(parents=True, exist_ok=True)
    save_raw_outputs(comparison, output_dir)

    if args.json or args.markdown:
        if args.json:
            jp = generate_json_report(comparison, output_dir)
            print(f"JSON report: {jp}")
        if args.markdown:
            mp = generate_markdown_report(comparison, output_dir)
            print(f"Markdown report: {mp}")
    else:
        # Default: text summary
        print(f"\n{'Script':40s} {'Classification':20s}")
        print("-" * 60)
        for r in comparison:
            c = r.get("classification", "UNKNOWN")
            print(f"{r['name']:40s} {c:20s}")

    # Determine exit code
    unexpected = [r for r in comparison
                  if r.get("classification") in ("DIFFERENT", "UNEXPECTED_DIFFERENCE")]
    timed_out = [r for r in comparison if r.get("classification") == "TIMEOUT"]
    blocked = [r for r in comparison if r.get("classification") == "BLOCKED"]
    both_failed = [r for r in comparison if r.get("classification") == "BOTH_FAILED"]

    has_unexpected = bool(unexpected) and args.fail_on_difference
    has_timeout = bool(timed_out)
    has_blocked = bool(blocked)
    has_both_failed = bool(both_failed)

    if has_unexpected:
        return 1
    if has_timeout or has_blocked or has_both_failed:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
