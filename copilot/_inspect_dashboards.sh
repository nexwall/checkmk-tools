#!/bin/bash
SITE="/omd/sites/monitoring"

echo "=== Dashboard files esistenti ==="
find "$SITE" -name "*.mk" | xargs grep -l "dashboard" 2>/dev/null | head -10

echo ""
echo "=== Dashboards dir ==="
ls -la "$SITE/etc/check_mk/multisite.d/wato/" 2>/dev/null
ls -la "$SITE/var/check_mk/web/cmkadmin/" 2>/dev/null

echo ""
echo "=== Esempio dashboard esistente (primi 80 righe) ==="
find "$SITE/var/check_mk/web" -name "dashboards.mk" 2>/dev/null | head -1 | xargs head -80 2>/dev/null
