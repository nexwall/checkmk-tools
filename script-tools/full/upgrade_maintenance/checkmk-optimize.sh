#!/usr/bin/env bash
set -euo pipefail

# checkmk-optimize.sh
# "Balanced" optimizations for Checkmk hosts (Ubuntu/Debian).
# Simple output (ASCII-only), with backup of touched files.

LOGFILE="/var/log/checkmk-optimize.log"
TSLOG="/var/log/timeshift-rotation.log"
BACKUP_DIR="/var/backups/checkmk-optimize"

die() { echo "[ERR] $*" >&2; exit 1; }
log() { echo "[$(date +%F_%T)] $*" | tee -a "$LOGFILE"; }
warn() { echo "[$(date +%F_%T)] WARN: $*" | tee -a "$LOGFILE"; }

require_root() {
    [[ ${EUID:-$(id -u)} -eq 0 ]] || die "eseguire come root (sudo)"
}

ask() {
    # ask "Domanda?" => ritorna 0 se y/Y/s/S, altrimenti 1
    local prompt="$1" reply
    read -r -p "$prompt [y/N]: " reply
    reply="${reply:-N}"
    [[ "$reply" =~ ^[YySs]$ ]]
}

backup_file() {
    local src="$1" base
    base="$(basename "$src")"
    cp -a "$src" "$BACKUP_DIR/${base}.$(date +%Y%m%d-%H%M%S).bak"
}

timeshift_snapshot() {
    local label="$1" comment
    command -v timeshift >/dev/null 2>&1 || return 0
    [[ -x /usr/bin/timeshift ]] || return 0
    comment="${label}-checkmk-optimize $(date +%F_%T)"

    log "Timeshift: creazione snapshot ($label)"
    if /usr/bin/timeshift --create --comments "$comment" --tags D; then
        echo "[$(date +%F_%T)] Snapshot $label OK: $comment" >> "$TSLOG"
        log "Timeshift: snapshot $label completato"
    else
        echo "[$(date +%F_%T)] Snapshot $label ERROR: $comment" >> "$TSLOG"
        warn "Timeshift: errore creazione snapshot $label"
    fi
}

optimize_swap_zram() {
    log "SWAP: swappiness=10 (+ zram-tools se mancante)"

    if [[ -f /etc/sysctl.conf ]]; then
        backup_file /etc/sysctl.conf
    fi

    mkdir -p /etc/sysctl.d
    printf '%s\n' 'vm.swappiness = 10' > /etc/sysctl.d/99-swap.conf
    sysctl -w vm.swappiness=10 >/dev/null || true

    if ! dpkg-query -W -f='${Status}' zram-tools 2>/dev/null | grep -q "install ok installed"; then
        log "Installazione: zram-tools"
        apt-get update
        apt-get install -y zram-tools
    else
        log "zram-tools: gia installato"
    fi
}

disable_nonessential_services() {
    local svc
    for svc in snapd.service apport.service motd-news.timer; do
        if systemctl list-unit-files 2>/dev/null | awk '{print $1}' | grep -qx "$svc"; then
            systemctl disable --now "$svc" >/dev/null 2>&1 || true
            log "Disabilitato: $svc"
        else
            log "Non presente: $svc"
        fi
    done
}

optimize_io_scheduler() {
    local dev sched_file target
    dev="$(lsblk -ndo NAME,TYPE | awk '$2=="disk"{print $1; exit}')"
    [[ -n "$dev" ]] || { warn "Nessun disco rilevato (lsblk)"; return 0; }

    sched_file="/sys/block/${dev}/queue/scheduler"
    [[ -w "$sched_file" ]] || { warn "Impossibile scrivere scheduler: $sched_file"; return 0; }

    if grep -q "mq-deadline" "$sched_file"; then
        target="mq-deadline"
    elif grep -q "deadline" "$sched_file"; then
        target="deadline"
    else
        warn "Scheduler non riconosciuto per /dev/$dev (skip)"
        return 0
    fi

    echo "$target" > "$sched_file"
    log "I/O scheduler impostato su /dev/$dev: $target"
}

optimize_db() {
    local service conf
    service=""
    conf=""

    if systemctl list-unit-files 2>/dev/null | awk '{print $1}' | grep -qx mariadb.service; then
        service="mariadb"
        conf="/etc/mysql/mariadb.conf.d/50-server.cnf"
    elif systemctl list-unit-files 2>/dev/null | awk '{print $1}' | grep -qx mysql.service; then
        service="mysql"
        conf="/etc/mysql/mysql.conf.d/mysqld.cnf"
    else
        warn "DB: nessun servizio mariadb/mysql trovato (skip)"
        return 0
    fi

    [[ -f "$conf" ]] || { warn "DB: config non trovata: $conf"; return 0; }

    log "DB: backup e applicazione tuning su $conf"
    backup_file "$conf"

    # Removes any previous block handled by this script
    sed -i '/^# BEGIN CHECKMK_OPTIMIZE$/,/^# END CHECKMK_OPTIMIZE$/d' "$conf"

    cat >> "$conf" <<'EOF'

# BEGIN CHECKMK_OPTIMIZE
# "Balanced" tuning (check based on RAM/usage).
innodb_buffer_pool_size = 512M
innodb_log_file_size = 128M
# NOTE: query_cache is removed/ignored on modern MySQL; left here only if supported.
query_cache_size = 32M
query_cache_type = 1
# END CHECKMK_OPTIMIZE
EOF

    systemctl restart "$service" && log "DB: riavviato servizio $service" || warn "DB: riavvio fallito ($service)"
}

optimize_apache_limits() {
    local dropin
    dropin="/etc/systemd/system/apache2.service.d"
    mkdir -p "$dropin"

    log "Apache: impostazione LimitNOFILE=4096"
    cat > "$dropin/limits.conf" <<'EOF'
[Service]
LimitNOFILE=4096
EOF

    systemctl daemon-reload
    systemctl restart apache2 && log "Apache: riavviato" || warn "Apache: riavvio fallito"
}

prepare_agent_cache() {
    local dir
    dir="/var/lib/check_mk_agent/cache"
    mkdir -p "$dir"
    chown root:root "$dir"
    chmod 700 "$dir"
    log "Agent cache: pronta in $dir"
    log "Suggerimento TTL local checks: '0 NomeServizio <ttl=300> testo...'"
}

disable_frp_compression() {
    local f
    for f in /etc/frp/frpc.toml /etc/frp/frps.toml; do
        [[ -f "$f" ]] || continue
        log "FRP: disattivo compressione in $f"
        backup_file "$f"
        sed -i 's/^\s*use_compression\s*=\s*true\s*$/use_compression = false/gI' "$f" || true
        sed -i 's/^\s*use_compression\s*=\s*"true"\s*$/use_compression = false/gI' "$f" || true
    done

    systemctl restart frpc >/dev/null 2>&1 || true
    systemctl restart frps >/dev/null 2>&1 || true
}

main() {
    require_root
    mkdir -p "$BACKUP_DIR"
    touch "$LOGFILE" "$TSLOG"

    echo "Checkmk optimization (interactive)"
    echo "Log:    $LOGFILE"
    echo "TS log: $TSLOG"
    echo "Backup: $BACKUP_DIR"
    echo

    if command -v timeshift >/dev/null 2>&1; then
        if ask "Creare snapshot Timeshift PRE?"; then
            timeshift_snapshot "PRE"
        fi
    else
        log "Timeshift non installato (skip snapshot)"
    fi

    if ask "Ottimizzare SWAP (swappiness=10) e zram?"; then
        optimize_swap_zram
    fi

    if ask "Disabilitare servizi non essenziali (snapd/apport/motd-news)?"; then
        disable_nonessential_services
    fi

    if ask "Impostare scheduler I/O (mq-deadline/deadline)?"; then
        optimize_io_scheduler
    fi

    if ask "Ottimizzare DB (mariadb/mysql) con tuning bilanciato?"; then
        optimize_db
    fi

    if ask "Ottimizzare Apache (LimitNOFILE=4096)?"; then
        optimize_apache_limits
    fi

    if ask "Preparare caching directory per Checkmk agent?"; then
        prepare_agent_cache
    fi

    if ask "Disattivare compressione FRP (riduce CPU)?"; then
        disable_frp_compression
    fi

    log "Suggerimento (WATO / Global settings):"
    log "- Normal check interval: 2-3 min (non critici)"
    log "- Maximum concurrent checks: 10-15"
    log "- Periodic service discovery: giornaliera o disattivata"

    if command -v timeshift >/dev/null 2>&1; then
        if ask "Creare snapshot Timeshift POST?"; then
            timeshift_snapshot "POST"
        fi
    fi

    echo
    log "Ottimizzazione completata. Backup in $BACKUP_DIR"
}

main "$@"
