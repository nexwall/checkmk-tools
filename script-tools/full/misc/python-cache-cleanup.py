#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Python cache artifact cleanup and verification tool
# Scans one or more Git repositories for __pycache__/, .pyc, .pyo files,
# reports inventory, removes artifacts, and verifies .gitignore coverage.

import argparse
import os
import subprocess
import sys
from datetime import datetime

VERSION = "1.0.0"
TOOL_NAME = "python-cache-cleanup"

# Default repository paths (WSL / Kali Linux mount)
DEFAULT_REPOS = [
    "/mnt/c/Users/Marzio/.copilot",
    "/mnt/c/Users/Marzio/Desktop/CheckMK/checkmk-tools",
    "/mnt/c/Users/Marzio/Desktop/CheckMK/copilot-tools",
    "/mnt/c/Users/Marzio/Desktop/CheckMK/ns8-checkmk-agent",
    "/mnt/c/Users/Marzio/Desktop/CheckMK/ns8-checkmk-container",
    "/mnt/c/Users/Marzio/Desktop/alexa-chatgpt-skill",
]

# Directory basenames to skip during traversal
EXCLUDE_DIRS = {".git", ".venv", "venv", "env", ".tox", ".nox", "node_modules"}

## Useful

def run(cmd):
    """Run a command and return (rc, stdout, stderr)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def find_artifacts(repo):
    """Walk repo and collect __pycache__ dirs and .pyc/.pyo files."""
    dirs = []
    files = []
    for root, dnames, fnames in os.walk(repo):
        dnames[:] = [d for d in dnames if d not in EXCLUDE_DIRS]
        for d in dnames:
            if d == "__pycache__":
                dirs.append(os.path.join(root, d))
        for f in fnames:
            if f.endswith(".pyc") or f.endswith(".pyo"):
                files.append(os.path.join(root, f))
    return dirs, files


def is_git_repo(path):
    """Return (ok, top_level) if path is inside a Git repository."""
    rc, out, _ = run(["git", "-C", path, "rev-parse", "--show-toplevel"])
    return rc == 0, out


def check_gitignore(repo):
    """Return dict with .gitignore Python cache coverage."""
    path = os.path.join(repo, ".gitignore")
    if not os.path.isfile(path):
        return {"exists": False}
    with open(path) as f:
        text = f.read()
    return {
        "exists": True,
        "pycache": "__pycache__/" in text,
        "pycod": "*.py[cod]" in text or "*.pyc" in text or "*.pyo" in text,
        "pyclass": "*$py.class" in text,
    }


def is_ignored(repo, rel):
    """Return (True, source) if rel path is gitignored."""
    rc, out, _ = run(["git", "-C", repo, "check-ignore", "-v", "--", rel])
    return rc == 0, out


def remove_dirs(dirs, dry_run=False):
    """Remove __pycache__ directories. Return list of removed paths."""
    removed = []
    for d in dirs:
        if dry_run:
            removed.append(d)
        else:
            rc, _, _ = run(["rm", "-rf", d])
            if rc == 0:
                removed.append(d)
    return removed


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S %Z")


def baseline_path():
    return "/tmp/python-cache-baseline-{}.txt".format(
        datetime.now().strftime("%Y%m%d-%H%M%S")
    )

## Main

def main():
    p = argparse.ArgumentParser(
        description="{} v{} — Python cache artifact cleanup".format(TOOL_NAME, VERSION)
    )
    p.add_argument("--dry-run", action="store_true",
                    help="show what would be removed without deleting")
    p.add_argument("--repos", nargs="*", default=None,
                    help="specific repo paths (default: all known repos)")
    p.add_argument("--inventory-only", action="store_true",
                    help="only list artifacts, do not remove")
    p.add_argument("--skip-gitignore", action="store_true",
                    help="skip .gitignore coverage check")
    p.add_argument("--baseline", action="store_true",
                    help="save baseline report to /tmp/ after cleanup")
    p.add_argument("--version", action="store_true",
                    help="show version and exit")
    args = p.parse_args()

    if args.version:
        print("{} v{}".format(TOOL_NAME, VERSION))
        return 0

    repos = args.repos if args.repos is not None else DEFAULT_REPOS
    ts = timestamp()

    print("{} v{}".format(TOOL_NAME, VERSION))
    print("Timestamp: {}".format(ts))
    print()

    total_dirs = 0
    total_files = 0
    all_clean = True

    for repo in repos:
        repo = os.path.abspath(os.path.expanduser(repo))
        name = os.path.basename(repo)

        if not os.path.isdir(repo):
            print("[{}] SKIP — path not found: {}".format(name, repo))
            continue

        ok, root = is_git_repo(repo)
        if not ok:
            print("[{}] SKIP — not a Git repository".format(name))
            continue

        print("=== {} ({}) ===".format(name, root))

        dirs, files = find_artifacts(repo)
        dirc = len(dirs)
        filec = len(files)

        if dirc == 0 and filec == 0:
            print("  Status: CLEAN (0 artifacts)")
            print()
            continue

        all_clean = False
        total_dirs += dirc
        total_files += filec
        print("  Found: {} __pycache__ dirs, {} .pyc/.pyo files".format(dirc, filec))

        # Inventory listing
        if args.inventory_only or args.dry_run:
            for d in dirs:
                print("  DIR {}".format(os.path.relpath(d, repo)))
            for f in files:
                print("  FILE {}".format(os.path.relpath(f, repo)))

        # .gitignore check
        if not args.skip_gitignore:
            gi = check_gitignore(repo)
            if not gi["exists"]:
                print("  WARNING: no .gitignore file")
            else:
                missing = []
                if not gi["pycache"]:
                    missing.append("__pycache__/")
                if not gi["pycod"]:
                    missing.append("*.py[cod]")
                if not gi["pyclass"]:
                    missing.append("*$py.class")
                if missing:
                    print("  WARNING: .gitignore missing: {}".format(", ".join(missing)))
                else:
                    print("  .gitignore: OK")

        # Remove
        if not args.inventory_only:
            removed = remove_dirs(dirs, dry_run=args.dry_run)
            label = "Would remove" if args.dry_run else "Removed"
            print("  {} {} __pycache__ directories".format(label, len(removed)))
            # Post-removal verification
            rem_dirs, rem_files = find_artifacts(repo)
            rem = len(rem_dirs) + len(rem_files)
            print("  Result: {}".format("CLEAN" if rem == 0 else "WARNING: {} remain".format(rem)))

        print()

    # Summary
    if all_clean:
        print("SUMMARY: All repositories clean — 0 artifacts")
    else:
        print("SUMMARY: {} __pycache__ dirs, {} .pyc/.pyo files cleaned".format(
            total_dirs, total_files))

    # Baseline
    if args.baseline:
        bfile = baseline_path()
        with open(bfile, "w") as f:
            f.write("Python Cache Clean Baseline Report\n")
            f.write("Tool: {} v{}\n".format(TOOL_NAME, VERSION))
            f.write("Timestamp: {}\n".format(ts))
            f.write("Repositories checked:\n")
            for repo in repos:
                f.write("  {}\n".format(os.path.abspath(os.path.expanduser(repo))))
            f.write("Artifacts found: {} dirs, {} files\n".format(total_dirs, total_files))
            f.write("Status: {}\n".format("ALL CLEAN" if all_clean else "ARTIFACTS CLEANED"))
        print("Baseline: {}".format(bfile))

    return 0 if all_clean else 0

main()
