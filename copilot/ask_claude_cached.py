#!/usr/bin/env python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""
ask_claude_cached.py - Anthropic API caller with explicit prompt caching.

Sends the CheckMK Expert DS agent file as a cached system prompt
and a user prompt to Claude via the official Anthropic SDK.

Usage:
  export ANTHROPIC_API_KEY='...'
  python3 ask_claude_cached.py "Your prompt here"
  echo "Prompt via stdin" | python3 ask_claude_cached.py
"""

import argparse
import os
import sys
import textwrap

VERSION = "1.0.0"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Ask Claude with prompt caching via Anthropic API"
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="User prompt as CLI arguments. If omitted, read from stdin.",
    )
    parser.add_argument(
        "--model",
        default="claude-opus-4-8",
        help="Claude model (default: claude-opus-4-8)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=2048,
        help="Maximum output tokens (default: 2048)",
    )
    parser.add_argument(
        "--system-file",
        default="/mnt/c/Users/Marzio/.copilot/agents/checkmk-expert-ds.agent.md",
        help="Path to system prompt file (default: checkmk-expert-ds.agent.md)",
    )
    parser.add_argument(
        "--ttl",
        choices=["5m", "1h"],
        default="5m",
        help="Cache TTL: 5m (ephemeral) or 1h (default: 5m)",
    )
    parser.add_argument(
        "--api-url",
        default="https://api.anthropic.com",
        help="Anthropic API base URL (default: https://api.anthropic.com)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output",
    )
    return parser.parse_args()


def resolve_path(path):
    """Convert WSL /mnt/c/... paths to Windows C:\\... paths when on Windows."""
    if sys.platform == "win32" or sys.platform == "cygwin":
        if path.startswith("/mnt/"):
            parts = path.split("/")
            # /mnt/c/... → C:\...
            drive = parts[2].upper() + ":"
            rest = "\\".join(parts[3:])
            return drive + "\\" + rest
    return path


def read_system_prompt(path):
    path = resolve_path(path)
    if not os.path.isfile(path):
        print(f"ERROR: system file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_user_prompt(args):
    if args.prompt:
        return " ".join(args.prompt)
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    print("ERROR: no prompt provided. Pass as argument or pipe via stdin.", file=sys.stderr)
    sys.exit(1)


def build_cache_control(ttl):
    cc = {"type": "ephemeral"}
    if ttl == "1h":
        cc["ttl"] = "1h"
    return cc


def estimate_cost(usage, model, ttl):
    if model != "claude-opus-4-8":
        return None

    input_base = 5.00
    output = 25.00
    cache_write_5m = 6.25
    cache_write_1h = 10.00
    cache_read = 0.50

    in_tok = usage.input_tokens
    out_tok = usage.output_tokens
    c_create = usage.cache_creation_input_tokens or 0
    c_read = usage.cache_read_input_tokens or 0

    cost_in = (in_tok / 1_000_000) * input_base
    cost_out = (out_tok / 1_000_000) * output

    if ttl == "5m":
        cost_cw = (c_create / 1_000_000) * cache_write_5m
    else:
        cost_cw = (c_create / 1_000_000) * cache_write_1h

    cost_cr = (c_read / 1_000_000) * cache_read
    total = cost_in + cost_out + cost_cw + cost_cr

    return {
        "input": cost_in,
        "output": cost_out,
        "cache_write": cost_cw,
        "cache_read": cost_cr,
        "total": total,
    }


def main():
    args = parse_args()

    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.", file=sys.stderr)
        print("Set it with: export ANTHROPIC_API_KEY='your-key-here'", file=sys.stderr)
        sys.exit(1)

    # Check SDK
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic SDK not installed.", file=sys.stderr)
        print("Install with: pip install anthropic", file=sys.stderr)
        sys.exit(1)

    # Read system prompt
    system_text = read_system_prompt(args.system_file)

    # Get user prompt
    user_prompt = get_user_prompt(args)
    if not user_prompt:
        print("ERROR: prompt is empty.", file=sys.stderr)
        sys.exit(1)

    # Build cache_control
    cc = build_cache_control(args.ttl)

    # Build system block
    system_block = [
        {
            "type": "text",
            "text": system_text,
            "cache_control": cc,
        }
    ]

    # Build messages
    messages = [
        {
            "role": "user",
            "content": user_prompt,
        }
    ]

    # Debug info
    if args.debug:
        print(f"[DEBUG] API URL: {args.api_url}", file=sys.stderr)
        print(f"[DEBUG] Model: {args.model}", file=sys.stderr)
        print(f"[DEBUG] API key length: {len(api_key)} (first: {api_key[:10]}...last: {api_key[-10:]})", file=sys.stderr)
        print(f"[DEBUG] System file: {args.system_file}", file=sys.stderr)
        print(f"[DEBUG] User prompt length: {len(user_prompt)}", file=sys.stderr)

    # Call API
    client = anthropic.Anthropic(api_key=api_key, base_url=args.api_url)

    try:
        response = client.messages.create(
            model=args.model,
            max_tokens=args.max_tokens,
            system=system_block,
            messages=messages,
        )
    except Exception as e:
        print(f"ERROR: Anthropic API call failed: {e}", file=sys.stderr)
        if args.debug:
            print(f"[DEBUG] Full exception: {repr(e)}", file=sys.stderr)
        sys.exit(1)

    # Print response
    for block in response.content:
        if block.type == "text":
            print(block.text)

    # Print usage
    usage = response.usage
    print()
    print("---")
    print("Usage:")
    print(f"  input_tokens:              {usage.input_tokens}")
    print(f"  output_tokens:             {usage.output_tokens}")
    print(f"  cache_creation_input_tokens: {usage.cache_creation_input_tokens}")
    print(f"  cache_read_input_tokens:    {usage.cache_read_input_tokens}")

    # Cost estimate
    cost = estimate_cost(usage, args.model, args.ttl)
    if cost is not None:
        print()
        print("Cost estimate (claude-opus-4-8):")
        print(f"  input base:         ${cost['input']:.6f}")
        print(f"  output:             ${cost['output']:.6f}")
        print(f"  cache write ({args.ttl}):  ${cost['cache_write']:.6f}")
        print(f"  cache read:         ${cost['cache_read']:.6f}")
        print(f"  TOTAL:              ${cost['total']:.6f}")
    else:
        print()
        print("Cost estimate not available for this model.")

    # Test instructions
    print()
    print("---")
    print("Test commands:")
    print()
    print("  export ANTHROPIC_API_KEY='...'")
    print()
    print(
        '  python3 copilot/ask_claude_cached.py "Riassumi in 10 righe la RULE DS"'
    )
    print()
    print(
        '  python3 copilot/ask_claude_cached.py "Elenca i punti deboli residui della RULE DS"'
    )
    print()
    print("Expected:")
    print("  Run 1: cache_creation_input_tokens > 0")
    print("  Run 2 (within 5m): cache_read_input_tokens > 0")


if __name__ == "__main__":
    main()
