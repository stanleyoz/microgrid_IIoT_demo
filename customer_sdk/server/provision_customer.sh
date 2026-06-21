#!/usr/bin/env bash
#
# Provision a customer trial on the VM broker. Adds a mosquitto credential and
# schedules its automatic revocation after the trial window. Topic isolation is
# handled by the existing pattern ACL (microgrid/%u/#) — no ACL edit needed.
#
# Run on the broker VM as root:
#   sudo ./provision_customer.sh <site_id> <secret> [trial_hours]
#
# Example:
#   sudo ./provision_customer.sh cust-7f3a... 'S3cr3t...' 12
#
set -euo pipefail

PASSWD_FILE="/etc/mosquitto/passwd"
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"

die() { echo "[x] $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run as root."
[ $# -ge 2 ] || die "Usage: $0 <site_id> <secret> [trial_hours]"

SITE_ID="$1"; SECRET="$2"; TRIAL_H="${3:-12}"
case "$SITE_ID" in
    cust-*) : ;;
    *) die "site_id must start with 'cust-' (got '$SITE_ID')." ;;
esac
# Cap at 12h.
awk "BEGIN{exit !($TRIAL_H > 12)}" && { echo "[!] capping trial_hours to 12"; TRIAL_H=12; }

command -v mosquitto_passwd >/dev/null || die "mosquitto_passwd not found."

if cut -d: -f1 "$PASSWD_FILE" | grep -qx "$SITE_ID"; then
    die "User '$SITE_ID' already exists — sequential onboarding expects one trial at a time. Deprovision first."
fi

echo "[*] Adding broker credential '$SITE_ID'…"
mosquitto_passwd -b "$PASSWD_FILE" "$SITE_ID" "$SECRET"

echo "[*] Reloading mosquitto (SIGHUP — no downtime)…"
systemctl reload mosquitto 2>/dev/null || kill -HUP "$(cat /run/mosquitto/mosquitto.pid)"

echo "[*] Scheduling auto-revocation in ${TRIAL_H}h…"
UNIT="cust-revoke-$(echo "$SITE_ID" | tr -c 'a-zA-Z0-9' '-')"
systemd-run --on-active="${TRIAL_H}h" --unit="$UNIT" \
    "$SELF_DIR/deprovision_customer.sh" "$SITE_ID" >/dev/null

echo "[ok] Provisioned '$SITE_ID' for ${TRIAL_H}h. Revocation unit: $UNIT"
echo "     (inspect with: systemctl list-timers '$UNIT*')"
