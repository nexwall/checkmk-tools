#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Rename CheckMK hosts via REST API using delete + recreate.
# Used when UI rename is not available (distributed/slave sites).
# Strategy: GET host (preserve folder + attributes) -> DELETE old -> POST new -> activate.

import sys
import json
import os
import argparse
import urllib.request
import urllib.error
import ssl

VERSION = "1.7.0"

# Host rename mapping: (old_name, new_name, ip_address, folder)
# folder is used in --recover mode (hosts already deleted, no GET possible)
HOSTS_TO_RENAME = [
    ("192.168.61.210", "marcatempo-colibri", "192.168.61.210", "/"),
]


## Utils

def make_ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def api_call(base_url, user, secret, method, path, body=None, etag=None):
    url = base_url.rstrip("/") + "/" + path.lstrip("/")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {user} {secret}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    if etag:
        req.add_header("If-Match", etag)
    try:
        with urllib.request.urlopen(req, context=make_ssl_ctx(), timeout=30) as resp:
            etag_out = resp.headers.get("ETag", "*")
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}, etag_out
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            err = json.loads(raw)
        except Exception:
            err = raw.decode()
        return e.code, err, ""


def get_host(base_url, user, secret, hostname):
    return api_call(base_url, user, secret, "GET", f"objects/host_config/{hostname}")


def delete_host(base_url, user, secret, hostname, etag):
    return api_call(base_url, user, secret, "DELETE",
                    f"objects/host_config/{hostname}", etag=etag)


def create_host(base_url, user, secret, hostname, folder, attributes):
    payload = {
        "host_name": hostname,
        "folder": folder,
        "attributes": attributes,
    }
    return api_call(base_url, user, secret, "POST",
                    "domain-types/host_config/collections/all", body=payload)


def activate_changes(base_url, user, secret):
    payload = {"force_foreign_changes": True}
    return api_call(base_url, user, secret, "POST",
                    "domain-types/activation_run/actions/activate-changes/invoke",
                    body=payload, etag="*")


def list_hosts(base_url, user, secret):
    return api_call(base_url, user, secret, "GET",
                    "domain-types/host_config/collections/all")


## Main

def main():
    parser = argparse.ArgumentParser(
        description=f"rename_hosts_api.py v{VERSION} - Rename CheckMK hosts via REST API"
    )
    parser.add_argument("--url", required=True,
                        help="CheckMK API base URL, e.g. https://server/site/check_mk/api/1.0")
    parser.add_argument("--user", default="automation",
                        help="Automation username (default: automation)")
    parser.add_argument("--secret", default=os.environ.get("CMK_SECRET", ""),
                        help="Automation secret (or set CMK_SECRET env var)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show actions without executing them")
    parser.add_argument("--no-activate", action="store_true",
                        help="Skip activate-changes at the end")
    parser.add_argument("--recover", action="store_true",
                        help="Recovery mode: skip GET/DELETE, just CREATE (for already-deleted hosts)")
    parser.add_argument("--list", action="store_true",
                        help="List all hosts on target (useful to find IP-named ones)")
    args = parser.parse_args()

    if not args.secret:
        print("ERROR: --secret is required (or set CMK_SECRET env var)", file=sys.stderr)
        sys.exit(1)

    print(f"rename_hosts_api.py v{VERSION}")
    print(f"Target : {args.url}")
    print(f"User   : {args.user}")
    print(f"Mode   : {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print()

    # --list mode: just dump all hosts
    if args.list:
        status, body, _ = list_hosts(args.url, args.user, args.secret)
        if status != 200:
            print(f"ERROR listing hosts (HTTP {status}): {body}", file=sys.stderr)
            sys.exit(1)
        items = body.get("value", [])
        print(f"Found {len(items)} hosts:")
        for item in items:
            hid = item.get("id", "?")
            folder = item.get("extensions", {}).get("folder", "?")
            ip = item.get("extensions", {}).get("attributes", {}).get("ipaddress", "")
            print(f"  {hid:<40} folder={folder}  ip={ip}")
        sys.exit(0)

    success = 0
    failed = 0

    for entry in HOSTS_TO_RENAME:
        old_name, new_name, ip, known_folder = entry
        print(f"[{old_name}] -> [{new_name}]  ip={ip}")

        # --recover: hosts already deleted, skip GET/DELETE, just CREATE
        if args.recover:
            status_cre, body_cre, _ = create_host(
                args.url, args.user, args.secret, new_name, known_folder, {"ipaddress": ip}
            )
            if status_cre not in (200, 201):
                print(f"  FAIL: CREATE '{new_name}' HTTP {status_cre}: {body_cre}")
                failed += 1
            else:
                print(f"  OK: created '{new_name}' in folder '{known_folder}'")
                success += 1
            continue

        # Step 1: GET existing host to read folder + attributes
        status, body, etag = get_host(args.url, args.user, args.secret, old_name)
        if status != 200:
            print(f"  SKIP: host '{old_name}' not found on target (HTTP {status})")
            failed += 1
            continue

        ext = body.get("extensions", {})
        folder = ext.get("folder", known_folder)
        existing_attrs = ext.get("attributes", {})
        print(f"  Found: folder='{folder}'  etag={etag}")

        # Build new attributes: strip internal fields not accepted by POST,
        # keep only valid tag_* keys, ipaddress, alias, site, labels, parents, snmp_community
        ALLOWED_PREFIXES = ("tag_",)
        ALLOWED_KEYS = {"ipaddress", "alias", "site", "labels", "parents",
                        "snmp_community", "snmp_credentials", "management_address",
                        "management_protocol", "management_snmp_community",
                        "management_ipmi_credentials", "network_scan",
                        "network_scan_result", "locked_by", "locked_attributes"}
        new_attrs = {}
        for k, v in existing_attrs.items():
            if k in ALLOWED_KEYS or any(k.startswith(p) for p in ALLOWED_PREFIXES):
                new_attrs[k] = v
        new_attrs["ipaddress"] = ip

        if args.dry_run:
            print(f"  DRY-RUN: would DELETE '{old_name}' (etag={etag})")
            print(f"  DRY-RUN: would CREATE '{new_name}' folder='{folder}' ipaddress={ip}")
            success += 1
            continue

        # Step 2: DELETE old host
        status_del, body_del, _ = delete_host(args.url, args.user, args.secret, old_name, etag)
        if status_del not in (200, 204):
            print(f"  FAIL: DELETE '{old_name}' HTTP {status_del}: {body_del}")
            failed += 1
            continue
        print(f"  OK: deleted '{old_name}'")

        # Step 3: CREATE new host in same folder
        status_cre, body_cre, _ = create_host(
            args.url, args.user, args.secret, new_name, folder, new_attrs
        )
        if status_cre not in (200, 201):
            print(f"  FAIL: CREATE '{new_name}' HTTP {status_cre}: {body_cre}")
            failed += 1
            continue
        print(f"  OK: created '{new_name}' in folder '{folder}'")
        success += 1

    print()
    print(f"Result: {success} OK  {failed} FAILED  out of {len(HOSTS_TO_RENAME)}")

    # Step 4: Activate changes
    if args.dry_run:
        print("DRY-RUN: skipping activation")
    elif args.no_activate:
        print("INFO: activation skipped (--no-activate)")
    elif success > 0:
        print()
        print("Activating changes...")
        status_act, body_act, _ = activate_changes(args.url, args.user, args.secret)
        if status_act in (200, 201, 202, 204):
            print(f"OK: activation started (HTTP {status_act})")
        else:
            print(f"WARN: activation HTTP {status_act}: {body_act}")

    sys.exit(0 if failed == 0 else 1)


main()
