#!/usr/bin/env bash
#
# Scale up a happy customer: add one or more devices to an existing active
# customer account. Prints the new device credentials (JSON) for new bundles.
# The new device auto-appears on the customer's /c/<guid> dashboard (prefix
# filter) — no dashboard/VM reconfiguration.
#
# Run on the broker VM as root:
#   sudo ./add_device.sh <guid> [count]
#
set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

die() { echo "[x] $*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die "Run as root."
[ $# -ge 1 ] || die "Usage: $0 <guid> [count]"

GUID="$1"; COUNT="${2:-1}"
registry_active "$GUID" || die "No active customer '$GUID' (onboard first)."
TRIAL_H="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['trial_hours'])" "$(reg_file "$GUID")")"

echo "[*] Adding $COUNT device(s) to customer $GUID…" >&2
echo "{ \"guid\": \"$GUID\", \"devices\": ["
for i in $(seq 1 "$COUNT"); do
    IDX="$(next_device_index "$GUID")"
    SITE="cust-$GUID-$IDX"
    SECRET="$(gen_secret)"
    add_credential "$SITE" "$SECRET"
    registry_add_device "$GUID" "$SITE"
    schedule_revoke "$SITE" "$TRIAL_H"
    SEP=","; [ "$i" -eq "$COUNT" ] && SEP=""
    echo "    {\"site_id\": \"$SITE\", \"mqtt_user\": \"$SITE\", \"mqtt_pass\": \"$SECRET\"}$SEP"
done
echo "] }"
reload_broker
echo "[ok] Added $COUNT device(s) to $GUID." >&2
