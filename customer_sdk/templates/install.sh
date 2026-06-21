#!/usr/bin/env bash
#
# Microgrid trial gateway installer.
#
# Installs a local MQTT broker + the forwarder service on a customer Linux edge
# device (Raspberry Pi or equivalent: ARM32/64, x86-64, RISC-V). No Docker
# required. Run from the extracted SDK bundle directory, which must contain:
#   forwarder.py  gateway.conf  ca.crt  requirements.txt  microgrid-gateway.service
#
# Usage:  sudo ./install.sh
#
set -euo pipefail

INSTALL_DIR="/opt/microgrid-gateway"
SERVICE_NAME="microgrid-gateway"
MOSQ_DROPIN="/etc/mosquitto/conf.d/microgrid-gateway.conf"
LOCAL_BIND="${LOCAL_BIND:-0.0.0.0}"   # set LOCAL_BIND=127.0.0.1 to restrict to this host
BUNDLE_DIR="$(cd "$(dirname "$0")" && pwd)"

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Please run as root (sudo ./install.sh)."

for f in forwarder.py gateway.conf ca.crt requirements.txt; do
    [ -f "$BUNDLE_DIR/$f" ] || die "Bundle is missing $f"
done

# ── 1. Detect package manager and install dependencies ────────────────────────
install_deps() {
    local pkgs_mosq="mosquitto mosquitto-clients" pkgs_py="python3 python3-venv"
    if   command -v apt-get >/dev/null; then
        apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $pkgs_mosq $pkgs_py
    elif command -v dnf >/dev/null; then
        dnf install -y -q mosquitto python3 python3-virtualenv
    elif command -v apk >/dev/null; then
        apk add --no-cache mosquitto mosquitto-clients python3 py3-virtualenv
    elif command -v pacman >/dev/null; then
        pacman -Sy --noconfirm mosquitto python
    elif command -v zypper >/dev/null; then
        zypper -n install mosquitto python3 python3-virtualenv
    else
        die "No supported package manager found (apt/dnf/apk/pacman/zypper). Install mosquitto + python3 manually."
    fi
}
say "Installing dependencies (mosquitto + python3)…"
install_deps

# ── 2. Choose a free local broker port (bump if the preferred one is busy) ────
port_in_use() {
    local p="$1"
    if command -v ss >/dev/null; then
        ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$p\$" && return 0 || return 1
    fi
    # Robust fallback: python3 (always present after dep install) — a port is in
    # use if we can connect to it, OR if binding it fails (covers IPv4/IPv6).
    python3 - "$p" <<'PY'
import socket, sys
p = int(sys.argv[1])
def busy():
    s = socket.socket(); s.settimeout(0.3)
    if s.connect_ex(("127.0.0.1", p)) == 0:
        s.close(); return True
    s.close()
    try:
        b = socket.socket(); b.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        b.bind(("0.0.0.0", p)); b.close(); return False
    except OSError:
        return True
sys.exit(0 if busy() else 1)
PY
}
PREF_PORT="$(awk -F'= *' '/^local_broker_port/{print $2}' "$BUNDLE_DIR/gateway.conf" | tr -d '[:space:]')"
PREF_PORT="${PREF_PORT:-1883}"
PORT="$PREF_PORT"
while port_in_use "$PORT"; do
    warn "Port $PORT is already in use — trying $((PORT+1))…"
    PORT=$((PORT+1))
done
[ "$PORT" = "$PREF_PORT" ] || say "Local broker will use port $PORT (preferred $PREF_PORT was busy)."

# ── 3. Lay down install dir ───────────────────────────────────────────────────
say "Installing to $INSTALL_DIR …"
mkdir -p "$INSTALL_DIR"
cp "$BUNDLE_DIR/forwarder.py" "$BUNDLE_DIR/ca.crt" "$BUNDLE_DIR/requirements.txt" "$INSTALL_DIR/"
cp "$BUNDLE_DIR/gateway.conf" "$INSTALL_DIR/gateway.conf"

# Rewrite gateway.conf: chosen port, absolute ca path, enable service management.
GW="$INSTALL_DIR/gateway.conf"
sed -i \
    -e "s|^local_broker_port *=.*|local_broker_port = $PORT|" \
    -e "s|^ca_cert *=.*|ca_cert = $INSTALL_DIR/ca.crt|" \
    -e "s|^manage_service *=.*|manage_service = true|" \
    -e "s|^service_name *=.*|service_name = $SERVICE_NAME|" \
    "$GW"
grep -q '^manage_service' "$GW" || printf '\nmanage_service = true\nservice_name = %s\n' "$SERVICE_NAME" >> "$GW"

# ── 4. Python venv ────────────────────────────────────────────────────────────
say "Creating Python virtualenv…"
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

# ── 5. Local mosquitto listener (drop-in) ─────────────────────────────────────
say "Configuring local MQTT broker on $LOCAL_BIND:$PORT (anonymous)…"
cat > "$MOSQ_DROPIN" <<EOF
# Microgrid trial gateway — local sensor broker
listener $PORT $LOCAL_BIND
allow_anonymous true
EOF
[ "$LOCAL_BIND" = "127.0.0.1" ] || \
    warn "Local broker accepts unauthenticated connections on $LOCAL_BIND:$PORT — keep this device on a trusted network. (Set LOCAL_BIND=127.0.0.1 to restrict.)"

restart_mosquitto() {
    if command -v systemctl >/dev/null && [ -d /run/systemd/system ]; then
        systemctl enable mosquitto >/dev/null 2>&1 || true
        systemctl restart mosquitto
    elif command -v service >/dev/null; then
        service mosquitto restart || true
    else
        warn "Could not restart mosquitto automatically — start it manually."
    fi
}
restart_mosquitto

# ── 6. systemd service for the forwarder ──────────────────────────────────────
if command -v systemctl >/dev/null && [ -d /run/systemd/system ]; then
    say "Registering systemd service '$SERVICE_NAME'…"
    if [ -f "$BUNDLE_DIR/microgrid-gateway.service" ]; then
        cp "$BUNDLE_DIR/microgrid-gateway.service" /etc/systemd/system/$SERVICE_NAME.service
    else
        cat > /etc/systemd/system/$SERVICE_NAME.service <<EOF
[Unit]
Description=Microgrid Trial Gateway Forwarder
After=network-online.target mosquitto.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
Environment=MICROGRID_GATEWAY_CONF=$INSTALL_DIR/gateway.conf
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/forwarder.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    fi
    systemctl daemon-reload
    systemctl enable --now $SERVICE_NAME
    SERVICE_REGISTERED=1
else
    warn "systemd not available — run the forwarder manually:"
    warn "  MICROGRID_GATEWAY_CONF=$INSTALL_DIR/gateway.conf $INSTALL_DIR/.venv/bin/python $INSTALL_DIR/forwarder.py"
    SERVICE_REGISTERED=0
fi

# ── 7. Summary ────────────────────────────────────────────────────────────────
SITE_ID="$(awk -F'= *' '/^site_id/{print $2}' "$GW" | tr -d '[:space:]')"
TRIAL_H="$(awk -F'= *' '/^trial_hours/{print $2}' "$GW" | tr -d '[:space:]')"
echo
say "Installation complete."
cat <<EOF

  Site ID            : $SITE_ID
  Local MQTT broker  : $LOCAL_BIND:$PORT   (publish your sensor values here)
  Trial duration     : ${TRIAL_H}h (gateway stops automatically after this)

  Point your sensors at the local broker using plain numeric payloads:
    mosquitto_pub -h 127.0.0.1 -p $PORT -t battery_soc     -m 84.2
    mosquitto_pub -h 127.0.0.1 -p $PORT -t battery_voltage -m 25.4
    mosquitto_pub -h 127.0.0.1 -p $PORT -t solar_output    -m 1850
    mosquitto_pub -h 127.0.0.1 -p $PORT -t load_demand     -m 540
    mosquitto_pub -h 127.0.0.1 -p $PORT -t inverter_temp   -m 34.1
EOF
if [ -f "$BUNDLE_DIR/sensor_feed.sh" ]; then
    echo "  Quick test feed    : bash $BUNDLE_DIR/sensor_feed.sh   (auto-detects port $PORT)"
fi
if [ "$SERVICE_REGISTERED" = "1" ]; then
    echo "  Service status     : systemctl status $SERVICE_NAME"
    echo "  Live logs          : journalctl -u $SERVICE_NAME -f"
fi
echo
