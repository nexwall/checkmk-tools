#!/bin/bash
# deploy-nethesis-brand.sh
# Deploys Nethesis branding to CheckMK facelift theme on one or all known servers.
#
# Usage:
#   bash deploy-nethesis-brand.sh                  # deploy to all servers
# bash deploy-nethesis-brand.sh <target-server> # deploy to a single server
#
# Requirements: SSH access configured in ~/.ssh/config for each target.

set -e

ALL_TARGETS=(
    "<ubuntu-test-server>"
    "checkmk-vps-01"
    "checkmk-vps-02"
    "srv-monitoring-sp"
    "srv-monitoring-us"
)

THEME_PATH="/omd/sites/monitoring/local/share/check_mk/web/htdocs/themes/facelift/images"
CSS_PATH="/omd/sites/monitoring/local/share/check_mk/web/htdocs/themes/facelift/theme.css"

# --- Build assets ---
build_assets() {
    echo "[1/3] Downloading Nethesis logos..."
    curl -s -o /tmp/nethesis_color.png "https://www.nethesis.it/assets/uploads/2025/04/nethesis_colore_2025_base_180px.png"
    curl -s -o /tmp/nethesis_n_icon.png "https://www.nethesis.it/assets/uploads/2020/03/nethesisFavicon120.png"

    if [ ! -s /tmp/nethesis_color.png ] || [ ! -s /tmp/nethesis_n_icon.png ]; then
        echo "ERROR: failed to download logos. Check internet connectivity."
        exit 1
    fi

    COLOR_B64=$(base64 -w 0 /tmp/nethesis_color.png)
    N_B64=$(base64 -w 0 /tmp/nethesis_n_icon.png)

    echo "[2/3] Building SVG assets..."

    # Login page logo (290px, white box, green border, wordmark + MONITORING)
    cat > /tmp/checkmk_logo.svg << SVGEOF
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 290 80" width="290" height="80">
  <rect x="1" y="1" width="288" height="78" fill="white" rx="12" stroke="#3ecf8e" stroke-width="2"/>
  <image x="55" y="10" width="180" height="44" href="data:image/png;base64,${COLOR_B64}" preserveAspectRatio="xMidYMid meet"/>
  <text x="145" y="71" font-family="Poppins, Helvetica Neue, Arial, sans-serif" font-size="11" font-weight="600" fill="#1a425c" text-anchor="middle" letter-spacing="5">MONITORING</text>
</svg>
SVGEOF

    # Sidebar logo - N icon with rounded corners
    cat > /tmp/icon_checkmk_logo.svg << SVGEOF
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 40 40" width="40" height="40">
  <defs><clipPath id="rounded"><rect width="40" height="40" rx="10" ry="10"/></clipPath></defs>
  <image x="0" y="0" width="40" height="40" href="data:image/png;base64,${N_B64}" preserveAspectRatio="xMidYMid meet" clip-path="url(#rounded)"/>
</svg>
SVGEOF

    # Minimal sidebar icon
    cat > /tmp/icon_checkmk_logo_min.svg << SVGEOF
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 28 28" width="28" height="28">
  <defs><clipPath id="rounded"><rect width="28" height="28" rx="7" ry="7"/></clipPath></defs>
  <image x="0" y="0" width="28" height="28" href="data:image/png;base64,${N_B64}" preserveAspectRatio="xMidYMid meet" clip-path="url(#rounded)"/>
</svg>
SVGEOF
}

# --- Deploy to a single target ---
deploy_to() {
    local TARGET="$1"
    echo ""
    echo ">>> Deploying to: ${TARGET}"

    ssh "${TARGET}" "mkdir -p ${THEME_PATH}"
    scp /tmp/checkmk_logo.svg          "${TARGET}:${THEME_PATH}/checkmk_logo.svg"
    scp /tmp/icon_checkmk_logo.svg     "${TARGET}:${THEME_PATH}/icon_checkmk_logo.svg"
    scp /tmp/icon_checkmk_logo_min.svg "${TARGET}:${THEME_PATH}/icon_checkmk_logo_min.svg"

    ssh "${TARGET}" "cat > ${CSS_PATH}" << 'CSSEOF'
/* Nethesis brand override for Checkmk facelift theme */

:root {
  --color-state-success-background: #0369a1;
  --ux-color-primary: #0369a1;
}

body.login {
  background: linear-gradient(135deg, #1a425c 0%, #0369a1 100%) !important;
}

.login_window,
.login div#login_window {
  background: #ffffff !important;
  border-radius: 8px !important;
  box-shadow: 0 8px 32px rgba(26, 66, 92, 0.3) !important;
}

.login_window .login_title,
#login_window .login_title {
  display: none !important;
}

#header, .header, div#header { background: #1a425c !important; }
#sidebar, .sidebar, div#sidebar { background: #1a425c !important; }
#sidebar a:hover, .sidebar a:hover { background: #0369a1 !important; }
.top_navbar, #top_navbar { background: #1a425c !important; }
#page_menu_bar, .page_menu_bar { background: #1a425c !important; }
.logo, #logo, .header_logo { background: transparent !important; }
.title_line, div.title_line { border-bottom: 3px solid #0369a1 !important; }

input.button, a.button, button.hot, .hot {
  background: #0369a1 !important;
  border-color: #024d80 !important;
}
input.button:hover, a.button:hover, button.hot:hover { background: #024d80 !important; }
a { color: #0369a1 !important; }
.selected, .active, li.active { border-left-color: #0369a1 !important; }
.stateBOOLEAN_0, .stateOK { background-color: #0369a1 !important; }
CSSEOF

    ssh "${TARGET}" "omd restart monitoring apache 2>&1 | tail -2"
    echo "    Done: ${TARGET}"
}

# --- Main ---
build_assets

if [ -n "$1" ]; then
    echo "[3/3] Deploying to single target: $1"
    deploy_to "$1"
else
    echo "[3/3] Deploying to all ${#ALL_TARGETS[@]} servers..."
    for TARGET in "${ALL_TARGETS[@]}"; do
        deploy_to "${TARGET}"
    done
fi

echo ""
echo "Nethesis branding deployment complete."
