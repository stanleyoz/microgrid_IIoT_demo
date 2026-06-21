#!/usr/bin/env bash
# Runs INSIDE an Ubuntu container. Proves multi-tenant isolation, scale-up and
# off-boarding using the real server-side lifecycle scripts + ACL.
set -euo pipefail
export PASSWD_FILE=/etc/mosquitto/passwd
export REGISTRY_DIR=/tmp/registry
SRV=/root/server

pass_for() {  # <onboard_json_file> <site_id>
    python3 -c "import json,sys
d=json.load(open(sys.argv[1]))
print(next(x['mqtt_pass'] for x in d['devices'] if x['site_id']==sys.argv[2]))" "$1" "$2"
}

# ── config (broker started after onboarding writes credentials) ───────────────
mosquitto_passwd -c -b "$PASSWD_FILE" mqtt-bridge pw
chmod 644 "$PASSWD_FILE"   # mirror the VM: mosquitto runs as 'mosquitto' user
cat > /etc/mosquitto/mosquitto.conf <<EOF
listener 1883 0.0.0.0
allow_anonymous false
password_file $PASSWD_FILE
acl_file /etc/mosquitto/aclfile
EOF
cp "$SRV/aclfile" /etc/mosquitto/aclfile

# ── onboard 3 customers × 2 devices ───────────────────────────────────────────
"$SRV/onboard_customer.sh" "Acme Solar"  12 2 > /tmp/c1.json 2>/dev/null
"$SRV/onboard_customer.sh" "Beta Grid"   12 2 > /tmp/c2.json 2>/dev/null
"$SRV/onboard_customer.sh" "Gamma Power" 12 2 > /tmp/c3.json 2>/dev/null
chmod 644 "$PASSWD_FILE"
mosquitto -c /etc/mosquitto/mosquitto.conf -d; sleep 1
echo "broker up: $(pgrep mosquitto >/dev/null && echo yes || echo no)"
G1=$(python3 -c "import json;print(json.load(open('/tmp/c1.json'))['guid'])")
G2=$(python3 -c "import json;print(json.load(open('/tmp/c2.json'))['guid'])")
G3=$(python3 -c "import json;print(json.load(open('/tmp/c3.json'))['guid'])")
echo "onboarded: G1=$G1 G2=$G2 G3=$G3"
echo "credentials issued: $(cut -d: -f1 $PASSWD_FILE | grep -c '^cust-') cust users"

# ── bridge subscribes to everything ───────────────────────────────────────────
timeout 6 mosquitto_sub -u mqtt-bridge -P pw -t 'microgrid/#' -F '%t' > /tmp/rx.txt 2>/dev/null &
sleep 1

P1=$(pass_for /tmp/c1.json "cust-$G1-01")
P2=$(pass_for /tmp/c2.json "cust-$G2-01")

echo "--- each device publishes to its OWN topic (should all arrive) ---"
mosquitto_pub -u "cust-$G1-01" -P "$P1" -t "microgrid/cust-$G1-01/telemetry" -m ok
mosquitto_pub -u "cust-$G1-02" -P "$(pass_for /tmp/c1.json cust-$G1-02)" -t "microgrid/cust-$G1-02/telemetry" -m ok
mosquitto_pub -u "cust-$G2-01" -P "$P2" -t "microgrid/cust-$G2-01/telemetry" -m ok
mosquitto_pub -u "cust-$G3-01" -P "$(pass_for /tmp/c3.json cust-$G3-01)" -t "microgrid/cust-$G3-01/telemetry" -m ok

echo "--- cross-customer violations (should be DENIED / not arrive) ---"
mosquitto_pub -u "cust-$G1-01" -P "$P1" -t "microgrid/cust-$G2-01/telemetry" -m HACK   # G1 -> G2
mosquitto_pub -u "cust-$G2-01" -P "$P2" -t "microgrid/cust-$G1-02/telemetry" -m HACK   # G2 -> G1
sleep 2

# ── scale-up: add a 3rd device to customer 1 ─────────────────────────────────
"$SRV/add_device.sh" "$G1" 1 > /tmp/c1add.json 2>/dev/null
chmod 644 "$PASSWD_FILE"; reload_broker() { pkill -HUP mosquitto 2>/dev/null||true; }; reload_broker; sleep 1
P1c=$(pass_for /tmp/c1add.json "cust-$G1-03")
mosquitto_pub -u "cust-$G1-03" -P "$P1c" -t "microgrid/cust-$G1-03/telemetry" -m ok
sleep 1

echo
echo "===== RESULTS ====="
echo "Bridge received (own-topic publishes, sorted):"
sort -u /tmp/rx.txt | sed 's/^/   /'
echo "HACK messages received (must be 0): $(grep -c HACK /tmp/rx.txt || true)"
echo "Customer 1 dashboard would show (LIKE cust-$G1-%):"
sort -u /tmp/rx.txt | grep "cust-$G1-" | sed 's/^/   /'

# ── off-board customer 2 ──────────────────────────────────────────────────────
echo
echo "===== OFF-BOARD customer 2 ($G2) ====="
echo "before: $(cut -d: -f1 $PASSWD_FILE | grep -c "^cust-$G2-") G2 creds, registry $( [ -f $REGISTRY_DIR/$G2.json ] && echo EXISTS || echo GONE)"
"$SRV/offboard_customer.sh" "$G2" 2>&1 | sed 's/^/   /'
chmod 644 "$PASSWD_FILE"; pkill -HUP mosquitto 2>/dev/null||true; sleep 1
echo "after:  $(cut -d: -f1 $PASSWD_FILE | grep -c "^cust-$G2-") G2 creds, registry $( [ -f $REGISTRY_DIR/$G2.json ] && echo EXISTS || echo GONE)"
echo "G2 device tries to publish post-offboard (expect auth failure):"
mosquitto_pub -u "cust-$G2-01" -P "$P2" -t "microgrid/cust-$G2-01/telemetry" -m x 2>&1 | sed 's/^/   /' || true
echo "G1 device still works post-offboard (expect no error):"
mosquitto_pub -u "cust-$G1-01" -P "$P1" -t "microgrid/cust-$G1-01/telemetry" -m x 2>&1 | sed 's/^/   /' && echo "   G1 publish OK"
echo "remaining creds: G1=$(cut -d: -f1 $PASSWD_FILE | grep -c "^cust-$G1-") G3=$(cut -d: -f1 $PASSWD_FILE | grep -c "^cust-$G3-") G2=$(cut -d: -f1 $PASSWD_FILE | grep -c "^cust-$G2-")"
