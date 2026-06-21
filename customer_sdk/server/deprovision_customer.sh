#!/usr/bin/env bash
#
# Revoke a customer trial on the VM broker: delete the mosquitto credential and
# reload. After this the publisher can no longer authenticate, so the VM stops
# processing its data. Invoked automatically by the systemd timer set at
# provisioning, or manually:
#   sudo ./deprovision_customer.sh <site_id>
#
set -euo pipefail

PASSWD_FILE="/etc/mosquitto/passwd"
die() { echo "[x] $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run as root."
[ $# -ge 1 ] || die "Usage: $0 <site_id>"
SITE_ID="$1"

if ! cut -d: -f1 "$PASSWD_FILE" | grep -qx "$SITE_ID"; then
    echo "[*] User '$SITE_ID' not present — nothing to revoke."
    exit 0
fi

echo "[*] Deleting broker credential '$SITE_ID'…"
mosquitto_passwd -D "$PASSWD_FILE" "$SITE_ID"

echo "[*] Reloading mosquitto (SIGHUP)…"
systemctl reload mosquitto 2>/dev/null || kill -HUP "$(cat /run/mosquitto/mosquitto.pid)"

echo "[ok] Revoked '$SITE_ID'. Publisher can no longer authenticate."
# Note: the scoped /c/<guid> dashboard teardown is handled in Phase 4.
