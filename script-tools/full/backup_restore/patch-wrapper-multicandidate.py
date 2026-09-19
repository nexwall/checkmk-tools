#!/usr/bin/env python3
"""patch-wrapper-multicandidate.py - Patch the deployed wrapper on srv-monitoring
to process ALL backup candidates (not just the newest one).

Fixes: job01 ignored when job00+job01 finish simultaneously."""

import sys
import os

WRAPPER_PATH = "/usr/local/sbin/checkmk_cloud_backup_push_run.sh"

OLD_BLOCK = r"""NEWEST_PATH="$(echo "${candidates[0]}" | cut -d' ' -f2-)"
NEWEST_FILE="$(basename "$NEWEST_PATH")"

if [[ "$NEWEST_FILE" =~ -incomplete ]]; then
  log "Skipping incomplete backup: $NEWEST_FILE"
  exit 0
fi

LAST_MODIFIED=$(stat -c %Y "$NEWEST_PATH" 2>/dev/null || echo "0")
CURRENT_TIME=$(date +%s)
AGE_SECONDS=$((CURRENT_TIME - LAST_MODIFIED))
if [[ $AGE_SECONDS -lt 120 ]]; then
  log "Backup too recent (${AGE_SECONDS}s old), waiting for stability: $NEWEST_FILE"
  exit 0
fi

if [[ -d "$NEWEST_PATH" ]]; then
  BACKUP_SIZE=$(du -sb "$NEWEST_PATH" 2>/dev/null | awk '{print $1}')
else
  BACKUP_SIZE=$(stat -c %s "$NEWEST_PATH" 2>/dev/null || echo "0")
fi

if [[ $BACKUP_SIZE -lt 102400 ]]; then
  log "Backup too small (${BACKUP_SIZE} bytes), might be incomplete: $NEWEST_FILE"
  exit 0
fi

TIMESTAMP="$(date '+%Y-%m-%d-%Hh%M')"
TIMESTAMPED_NAME="${NEWEST_FILE}-${TIMESTAMP}"
TIMESTAMPED_PATH="${BACKUP_DIR}/${TIMESTAMPED_NAME}"

if [[ "$NEWEST_FILE" != *"-"[0-9][0-9][0-9][0-9]"-"[0-9][0-9]"-"[0-9][0-9]"-"* ]]; then
  log "Renaming backup with timestamp: $NEWEST_FILE -> $TIMESTAMPED_NAME"
  if mv "$NEWEST_PATH" "$TIMESTAMPED_PATH"; then
    NEWEST_PATH="$TIMESTAMPED_PATH"
    NEWEST_FILE="$TIMESTAMPED_NAME"
  fi
fi

DEST="${REMOTE%/}/${REMOTE_PREFIX%/}/"
[[ "$REMOTE_PREFIX" == "." || -z "$REMOTE_PREFIX" ]] && DEST="${REMOTE%/}/"
REMOTE_SITE_PATH="${DEST}${SITE}"

COMMON_OPTS=(
  "--config=$RCLONE_CONF"
  "--log-file=${LOGDIR}/push-${SITE}.log"
  "--log-level=INFO"
  "--retries=$RETRIES"
  "--retries-sleep=10s"
  "--low-level-retries=10"
  "--stats=30s"
  "--stats-one-line"
  "--checksum"
)
[[ "$BWLIMIT" != "0" ]] && COMMON_OPTS+=("--bwlimit=$BWLIMIT")

if [[ -d "$NEWEST_PATH" ]]; then
  rclone copy "$NEWEST_PATH/" "${REMOTE_SITE_PATH}/${NEWEST_FILE}/" "${COMMON_OPTS[@]}"
else
  TMP_NAME=".${NEWEST_FILE}.partial"
  REMOTE_TMP="${REMOTE_SITE_PATH}/${TMP_NAME}"
  REMOTE_FINAL="${REMOTE_SITE_PATH}/${NEWEST_FILE}"
  rclone copyto "$NEWEST_PATH" "$REMOTE_TMP" "${COMMON_OPTS[@]}"
  rclone moveto "$REMOTE_TMP" "$REMOTE_FINAL" "${COMMON_OPTS[@]}" || {
    rclone delete "$REMOTE_TMP" "${COMMON_OPTS[@]}" 2>/dev/null || true
    exit 7
  }
fi"""

NEW_BLOCK = r"""DEST="${REMOTE%/}/${REMOTE_PREFIX%/}/"
[[ "$REMOTE_PREFIX" == "." || -z "$REMOTE_PREFIX" ]] && DEST="${REMOTE%/}/"
REMOTE_SITE_PATH="${DEST}${SITE}"

COMMON_OPTS=(
  "--config=$RCLONE_CONF"
  "--log-file=${LOGDIR}/push-${SITE}.log"
  "--log-level=INFO"
  "--retries=$RETRIES"
  "--retries-sleep=10s"
  "--low-level-retries=10"
  "--stats=30s"
  "--stats-one-line"
  "--checksum"
)
[[ "$BWLIMIT" != "0" ]] && COMMON_OPTS+=("--bwlimit=$BWLIMIT")

CURRENT_TIME=$(date +%s)
PUSHED=0

# Process ALL candidates (not just the newest) to handle simultaneous backups (e.g. job00+job01)
for entry in "${candidates[@]}"; do
  CANDIDATE_PATH="$(echo "$entry" | cut -d' ' -f2-)"
  CANDIDATE_FILE="$(basename "$CANDIDATE_PATH")"

  if [[ "$CANDIDATE_FILE" =~ -incomplete ]]; then
    log "Skipping incomplete backup: $CANDIDATE_FILE"
    continue
  fi

  LAST_MODIFIED=$(stat -c %Y "$CANDIDATE_PATH" 2>/dev/null || echo "0")
  AGE_SECONDS=$((CURRENT_TIME - LAST_MODIFIED))
  if [[ $AGE_SECONDS -lt 120 ]]; then
    log "Backup too recent (${AGE_SECONDS}s old), waiting for stability: $CANDIDATE_FILE"
    continue
  fi

  if [[ -d "$CANDIDATE_PATH" ]]; then
    BACKUP_SIZE=$(du -sb "$CANDIDATE_PATH" 2>/dev/null | awk '{print $1}')
  else
    BACKUP_SIZE=$(stat -c %s "$CANDIDATE_PATH" 2>/dev/null || echo "0")
  fi
  if [[ $BACKUP_SIZE -lt 102400 ]]; then
    log "Backup too small (${BACKUP_SIZE} bytes), might be incomplete: $CANDIDATE_FILE"
    continue
  fi

  if [[ "$CANDIDATE_FILE" != *"-"[0-9][0-9][0-9][0-9]"-"[0-9][0-9]"-"[0-9][0-9]"-"* ]]; then
    TIMESTAMP="$(date '+%Y-%m-%d-%Hh%M')"
    TIMESTAMPED_NAME="${CANDIDATE_FILE}-${TIMESTAMP}"
    TIMESTAMPED_PATH="${BACKUP_DIR}/${TIMESTAMPED_NAME}"
    log "Renaming backup with timestamp: $CANDIDATE_FILE -> $TIMESTAMPED_NAME"
    if mv "$CANDIDATE_PATH" "$TIMESTAMPED_PATH"; then
      CANDIDATE_PATH="$TIMESTAMPED_PATH"
      CANDIDATE_FILE="$TIMESTAMPED_NAME"
    fi
  fi

  if [[ -d "$CANDIDATE_PATH" ]]; then
    rclone copy "$CANDIDATE_PATH/" "${REMOTE_SITE_PATH}/${CANDIDATE_FILE}/" "${COMMON_OPTS[@]}"
  else
    TMP_NAME=".${CANDIDATE_FILE}.partial"
    REMOTE_TMP="${REMOTE_SITE_PATH}/${TMP_NAME}"
    REMOTE_FINAL="${REMOTE_SITE_PATH}/${CANDIDATE_FILE}"
    rclone copyto "$CANDIDATE_PATH" "$REMOTE_TMP" "${COMMON_OPTS[@]}"
    rclone moveto "$REMOTE_TMP" "$REMOTE_FINAL" "${COMMON_OPTS[@]}" || {
      rclone delete "$REMOTE_TMP" "${COMMON_OPTS[@]}" 2>/dev/null || true
      continue
    }
  fi

  log "Push completed: $CANDIDATE_FILE"
  PUSHED=$((PUSHED + 1))
done

log "Total backups pushed this run: $PUSHED""""

def main():
    if not os.path.exists(WRAPPER_PATH):
        print(f"ERROR: wrapper not found: {WRAPPER_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(WRAPPER_PATH, "r") as f:
        content = f.read()

    if OLD_BLOCK not in content:
        if "Process ALL candidates" in content:
            print("Wrapper already patched (multi-candidate loop found). Nothing to do.")
            sys.exit(0)
        print("ERROR: expected old block not found in wrapper. Cannot patch.", file=sys.stderr)
        sys.exit(1)

    new_content = content.replace(OLD_BLOCK, NEW_BLOCK, 1)
    backup_path = WRAPPER_PATH + ".bak-multicandidate"
    with open(backup_path, "w") as f:
        f.write(content)
    print(f"Backup saved: {backup_path}")

    with open(WRAPPER_PATH, "w") as f:
        f.write(new_content)
    print(f"Wrapper patched successfully: {WRAPPER_PATH}")


if __name__ == "__main__":
    main()
