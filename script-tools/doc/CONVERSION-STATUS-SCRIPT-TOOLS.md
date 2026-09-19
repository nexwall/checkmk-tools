# Conversion Status - script-tools/full
> **Category:** Operational

Report date: 2026-02-18

## Current status

- Folder analyzed: `script-tools/full`
- Bash (`.sh`) without Python equivalent: **0**
- Bash → Python conversion coverage: **100%**

## Verification method

For automatic comparison, name normalization was used:

- `-` and `_` treated as equivalent
- comparison by basename (`file.sh` ↔ `file.py`)

This avoids false negatives on mixed naming (kebab_case/snake_case).

## Decision taken at this stage

For complex or high operational risk scripts, Python entrypoints have been created that delegate to the canonical `.sh`, so as to obtain:

- uniform Python interface
- runtime behavior unchanged
- reduction of regressions during migration

## What this means operationally

- If you look for a script in `script-tools/full`, the `.py` counterpart now exists.
- For immediate use you can start the `.py`.
- Where internal delegation exists, the `.py` forwards args and environment to the corresponding `.sh`.

## Recommended next step (optional)

If you want maximum future maintainability, you can plan a phase 2:

1. Identify Python wrappers that delegate to Bash
2. prioritize the most used in production
3. Gradually convert logic from Bash to native Python