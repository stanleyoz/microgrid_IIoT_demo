#!/usr/bin/env bash
#
# Microgrid trial gateway uninstaller. Removes the forwarder service, the local
# broker drop-in, and the install directory. Run as root: sudo ./uninstall.sh
#
set -euo pipefail

INSTALL_DIR="/opt/microgrid-gateway"
SERVICE_NAME="microgrid-gateway"
MOSQ_DROPIN="/etc/mosquitto/conf.d/microgrid-gateway.conf"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "Please run as root (sudo ./uninstall.sh)."; exit 1; }

if command -v systemctl >/dev/null && [ -d /run/systemd/system ]; then
    say "Stopping and removing service…"
    systemctl disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
    rm -f "/etc/systemd/system/$SERVICE_NAME.service"
    systemctl daemon-reload
fi

say "Removing local broker drop-in…"
rm -f "$MOSQ_DROPIN"
if command -v systemctl >/dev/null && [ -d /run/systemd/system ]; then
    systemctl restart mosquitto >/dev/null 2>&1 || true
fi

say "Removing $INSTALL_DIR …"
rm -rf "$INSTALL_DIR"

say "Uninstalled. (mosquitto package left installed; remove with your package manager if unwanted.)"
