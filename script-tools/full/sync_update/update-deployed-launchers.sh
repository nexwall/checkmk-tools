#!/bin/bash
# update-deployed-launchers.sh - Updates remote launchers deployed on the server
# Sincronizza r*.sh dal repository alle destinazioni

set -euo pipefail

REPO_PATH="/omd/sites/monitoring/checkmk-tools"
DEST_BASE="/opt"

echo "=== UPDATE DEPLOYED LAUNCHERS ==="
echo ""

if [[ ! -d "$REPO_PATH" ]]; then
  echo "Repository not found: $REPO_PATH"
  exit 1
fi

updated=0
failed=0

# Find all launchers in the repository
while IFS= read -r repo_launcher; do
  launcher_name=$(basename "$repo_launcher")
  
  # Determine destination based on path
  if [[ "$repo_launcher" =~ Ydea-Toolkit ]]; then
    dest="/opt/ydea-toolkit/$launcher_name"
  elif [[ "$repo_launcher" =~ script-notify-checkmk ]]; then
    dest="/usr/local/bin/notify-checkmk/$launcher_name"
  elif [[ "$repo_launcher" =~ script-tools ]]; then
    dest="/opt/scripts/$launcher_name"
  else
    continue
  fi
  
  # Create directory if it does not exist
  dest_dir=$(dirname "$dest")
  if [[ ! -d "$dest_dir" ]]; then
    echo "Creating directory: $dest_dir"
    sudo mkdir -p "$dest_dir"
  fi
  
  # Copia launcher
  echo " Updating: $launcher_name -> $dest"
  if sudo cp "$repo_launcher" "$dest" && sudo chmod +x "$dest"; then
    echo "   Updated"
    ((updated++))
  else
    echo "   Failed"
    ((failed++))
  fi
  
done < <(find "$REPO_PATH" -name "r*.sh" -type f)

echo ""
echo "=== RIEPILOGO ==="
echo "Updated: $updated"
echo "Failed:  $failed"
