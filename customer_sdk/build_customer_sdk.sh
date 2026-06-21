#!/usr/bin/env bash
#
# End-to-end customer SDK builder (tinylab operator side).
#
# One command: provisions the customer on the broker VM (credential + registry +
# 12h auto-revoke) and packages an installable, emailable SDK that the customer
# unzips and runs with `sudo bash install.sh`. This is the flow the website
# backend will automate later.
#
# Usage:
#   ./build_customer_sdk.sh "<customer_name>" [--devices N] [--interval S] [--format zip|tgz]
#
# Env (defaults shown): GCP_PROJECT=microgrid-demo  VM_ZONE=australia-southeast1-a
#                       VM_INSTANCE=microgrid-broker
#
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
[ $# -ge 1 ] || { echo "Usage: $0 \"<customer_name>\" [--devices N] [--interval S] [--format zip|tgz]"; exit 1; }
NAME="$1"; shift
DEVICES=1; INTERVAL=30; FORMAT=zip
while [ $# -gt 0 ]; do case "$1" in
  --devices)  DEVICES="$2"; shift 2;;
  --interval) INTERVAL="$2"; shift 2;;
  --format)   FORMAT="$2"; shift 2;;
  *) echo "unknown arg: $1"; exit 1;; esac; done

PROJECT="${GCP_PROJECT:-microgrid-demo}"
ZONE="${VM_ZONE:-australia-southeast1-a}"
INSTANCE="${VM_INSTANCE:-microgrid-broker}"

echo "[*] Provisioning '$NAME' ($DEVICES device(s)) on $INSTANCE …"
JSON="$(mktemp)"
gcloud compute ssh "$INSTANCE" --project="$PROJECT" --zone="$ZONE" --tunnel-through-iap \
  --command="cd /opt/microgrid/customer_sdk/server && sudo bash onboard_customer.sh '$NAME' 12 $DEVICES 2>/dev/null" \
  2>/dev/null | sed -n '/^{/,/^}/p' > "$JSON"

python3 -c "import json,sys; json.load(open('$JSON'))" 2>/dev/null \
  || { echo "[x] Onboarding failed (no JSON returned). Check VM access."; cat "$JSON"; exit 1; }
GUID="$(python3 -c "import json;print(json.load(open('$JSON'))['guid'])")"
echo "[*] Onboarded GUID $GUID"

echo "[*] Building bundle …"
bash "$SELF/build_bundle.sh" "$JSON" --interval "$INTERVAL" --feeder --format "$FORMAT"
rm -f "$JSON"
echo "[ok] SDK ready to zip-and-email."
