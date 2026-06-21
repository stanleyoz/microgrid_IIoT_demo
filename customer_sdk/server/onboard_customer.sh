#!/usr/bin/env bash
#
# Onboard a new customer: create a registry entry and issue credentials for one
# or more initial devices. Prints the GUID + per-device credentials (JSON) for
# the bundle generator to embed in each device's SDK.
#
# Run on the broker VM as root:
#   sudo ./onboard_customer.sh "<customer_name>" [trial_hours] [num_devices]
#
set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

die() { echo "[x] $*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die "Run as root."
[ $# -ge 1 ] || die "Usage: $0 \"<customer_name>\" [trial_hours] [num_devices]"

NAME="$1"; TRIAL_H="${2:-12}"; NDEV="${3:-1}"
awk "BEGIN{exit !($TRIAL_H > 12)}" && { echo "[!] capping trial_hours to 12"; TRIAL_H=12; }
command -v mosquitto_passwd >/dev/null || die "mosquitto_passwd not found."

GUID="$(gen_guid)"
registry_create "$GUID" "$NAME" "$TRIAL_H"
echo "[*] Onboarded '$NAME' as customer $GUID (trial ${TRIAL_H}h)." >&2

echo "{"
echo "  \"customer_name\": \"$NAME\","
echo "  \"guid\": \"$GUID\","
echo "  \"dashboard_url\": \"/c/$GUID\","
echo "  \"devices\": ["
for i in $(seq 1 "$NDEV"); do
    IDX="$(next_device_index "$GUID")"
    SITE="cust-$GUID-$IDX"
    SECRET="$(gen_secret)"
    add_credential "$SITE" "$SECRET"
    registry_add_device "$GUID" "$SITE"
    schedule_revoke "$SITE" "$TRIAL_H"
    SEP=","; [ "$i" -eq "$NDEV" ] && SEP=""
    echo "    {\"site_id\": \"$SITE\", \"mqtt_user\": \"$SITE\", \"mqtt_pass\": \"$SECRET\"}$SEP"
done
echo "  ]"
echo "}"

reload_broker
echo "[ok] Provisioned $NDEV device(s) for $GUID." >&2
