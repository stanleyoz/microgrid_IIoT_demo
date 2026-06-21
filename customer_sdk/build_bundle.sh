#!/usr/bin/env bash
#
# Build an installable customer SDK bundle from an onboard_customer.sh JSON.
# Run on the tinylab side after onboarding a customer.
#
# Usage:
#   ./build_bundle.sh <onboard.json> [--interval N] [--feeder] [--outdir DIR] [--vm-host IP]
#
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
[ $# -ge 1 ] || { echo "Usage: $0 <onboard.json> [--interval N] [--feeder] [--outdir DIR] [--vm-host IP]"; exit 1; }
JSON="$1"; shift
INTERVAL=30; FEEDER=0; OUTDIR="$SELF/dist"; VM_HOST="34.87.254.184"; FORMAT=zip
while [ $# -gt 0 ]; do case "$1" in
  --interval) INTERVAL="$2"; shift 2;;
  --feeder)   FEEDER=1; shift;;
  --outdir)   OUTDIR="$2"; shift 2;;
  --vm-host)  VM_HOST="$2"; shift 2;;
  --format)   FORMAT="$2"; shift 2;;
  *) echo "unknown arg: $1"; exit 1;; esac; done

j() { python3 -c "import json,sys; d=json.load(open('$JSON')); print($1)"; }
GUID="$(j 'd["guid"]')"
NAME="$(j 'd["customer_name"]')"
SITE="$(j 'd["devices"][0]["site_id"]')"
USER="$(j 'd["devices"][0]["mqtt_user"]')"
PASS="$(j 'd["devices"][0]["mqtt_pass"]')"

BNAME="microgrid-sdk-$GUID"
BDIR="$OUTDIR/$BNAME"
rm -rf "$BDIR"; mkdir -p "$BDIR"

cp "$SELF/templates/forwarder.py" "$SELF/templates/install.sh" \
   "$SELF/templates/uninstall.sh" "$SELF/templates/microgrid-gateway.service" \
   "$SELF/templates/requirements.txt" "$BDIR/"
cp "$SELF/../edge/ca.crt" "$BDIR/ca.crt"

cat > "$BDIR/gateway.conf" <<EOF
[gateway]
site_id = $SITE
customer_name = $NAME
local_broker_host = 127.0.0.1
local_broker_port = 1883
vm_broker_host = $VM_HOST
vm_broker_port = 8883
mqtt_user = $USER
mqtt_pass = $PASS
ca_cert = ca.crt
publish_interval_s = $INTERVAL
trial_hours = 12
manage_service = false
service_name = microgrid-gateway
EOF

if [ "$FEEDER" = "1" ]; then
    cp "$SELF/templates/sensor_feed.sh" "$BDIR/sensor_feed.sh"
    chmod +x "$BDIR/sensor_feed.sh"
    FEEDER_NOTE="
A test sensor feeder is bundled (no Python needed — uses mosquitto_pub and
auto-detects the local port). To populate the dashboard without real sensors:
    bash sensor_feed.sh"
else
    FEEDER_NOTE="
Publish your sensor values to the local broker (plain numbers), e.g.:
    mosquitto_pub -h 127.0.0.1 -p <LOCAL_PORT> -t battery_soc -m 84.2"
fi

cat > "$BDIR/INSTALL.txt" <<EOF
Microgrid Trial Gateway — $NAME
================================================

1. Install (needs sudo; installs a local MQTT broker + the forwarder service):
       sudo bash install.sh

2. Feed data to the local broker:$FEEDER_NOTE

3. View your live data (capability URL — keep private):
       https://microgrid.tinylab.ai/c/?c=$GUID

The trial runs for up to 12 hours, then the gateway stops automatically.

Uninstall any time:
       sudo bash uninstall.sh
EOF

chmod +x "$BDIR/install.sh" "$BDIR/uninstall.sh"
mkdir -p "$OUTDIR"
if [ "$FORMAT" = "zip" ]; then
    ARCHIVE="$OUTDIR/$BNAME.zip"
    rm -f "$ARCHIVE"
    if command -v zip >/dev/null; then
        ( cd "$OUTDIR" && zip -qr "$BNAME.zip" "$BNAME" )
    else
        ( cd "$OUTDIR" && python3 -m zipfile -c "$BNAME.zip" "$BNAME" )
    fi
else
    ARCHIVE="$OUTDIR/$BNAME.tgz"
    tar -C "$OUTDIR" -czf "$ARCHIVE" "$BNAME"
fi

echo "Bundle:    $ARCHIVE"
echo "Site:      $SITE"
echo "Dashboard: https://microgrid.tinylab.ai/c/?c=$GUID"
echo "Contents:"
if [ "$FORMAT" = "zip" ]; then python3 -m zipfile -l "$ARCHIVE" | awk 'NR>1{print "   "$1}'; else tar -tzf "$ARCHIVE" | sed 's/^/   /'; fi
