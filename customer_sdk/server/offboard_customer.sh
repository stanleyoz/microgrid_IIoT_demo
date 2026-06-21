#!/usr/bin/env bash
#
# Off-board a customer: full reversal of VM-side onboarding state. Removes every
# device credential, cancels their auto-revoke timers, and deletes the registry
# entry, then reloads the broker. After this the customer's gateways can no
# longer authenticate and their /c/<guid> dashboard stops resolving.
#
# BigQuery telemetry rows are left as an append-only audit trail by default;
# pass --purge-data to also delete them.
#
# Run on the broker VM as root:
#   sudo ./offboard_customer.sh <guid> [--purge-data]
#
set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

die() { echo "[x] $*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die "Run as root."
[ $# -ge 1 ] || die "Usage: $0 <guid> [--purge-data]"

GUID="$1"; PURGE="${2:-}"
[ -f "$(reg_file "$GUID")" ] || die "Unknown customer '$GUID' (no registry entry)."

DEVICES="$(registry_devices "$GUID")"
echo "[*] Off-boarding $GUID — devices: ${DEVICES//$'\n'/ }"

for SITE in $DEVICES; do
    echo "    - revoking $SITE"
    cancel_revoke "$SITE"
    remove_credential "$SITE"
done

# Belt-and-suspenders: remove any stray cust-<guid>-* credentials.
for SITE in $(cut -d: -f1 "$PASSWD_FILE" 2>/dev/null | grep -E "^cust-$GUID-" || true); do
    remove_credential "$SITE"
done

registry_remove "$GUID"
reload_broker
echo "[ok] Off-boarded $GUID. Credentials, timers, and registry entry removed."

if [ "$PURGE" = "--purge-data" ]; then
    if command -v bq >/dev/null; then
        echo "[*] Purging BigQuery telemetry for cust-$GUID-* …"
        bq query --use_legacy_sql=false \
          "DELETE FROM \`microgrid-demo.microgrid_db.microgrid_telemetry\` WHERE site_id LIKE 'cust-$GUID-%'" \
          && echo "[ok] BigQuery rows purged."
    else
        echo "[!] bq not found — skipping data purge."
    fi
fi
