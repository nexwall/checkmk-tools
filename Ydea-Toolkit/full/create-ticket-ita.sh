#!/bin/bash
source .env

TITLE="$1"
DESCRIPTION="$2"
PRIORITY_ITA="$3"

# Convert Italian priority to English
case "${PRIORITY_ITA,,}" in
  bassa)    PRIORITY="low" ;;
  media)    PRIORITY="normal" ;;
  alta)     PRIORITY="high" ;;
  critica)  PRIORITY="critical" ;;
  *)        PRIORITY="normal" ;;
esac

echo "Creation of tickets with priority: $PRIORITY_ITA → $PRIORITY"
echo ""

./ydea-toolkit.sh create "$TITLE" "$DESCRIPTION" "$PRIORITY"
