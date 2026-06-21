#!/usr/bin/env bash
#
# ONE-TIME, LIVE-IMPACTING: enable the topic ACL on the production broker.
# Installs /etc/mosquitto/aclfile and adds `acl_file` to the mosquitto config,
# then reloads. Includes backup + automatic rollback if the broker fails to
# come back healthy.
#
# Run on the broker VM as root:  sudo ./enable_acl.sh
#
set -euo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
ACL_DST="/etc/mosquitto/aclfile"
ACL_CONF="/etc/mosquitto/conf.d/acl.conf"
BACKUP="/etc/mosquitto/acl-enable-backup.$(date +%s)"
die() { echo "[x] $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run as root."
[ -f "$SELF_DIR/aclfile" ] || die "aclfile not found next to this script."

if [ -f "$ACL_CONF" ]; then
    echo "[*] $ACL_CONF already present — ACL appears enabled. Nothing to do."
    exit 0
fi

echo "[*] Backing up mosquitto config to $BACKUP …"
mkdir -p "$BACKUP"
cp -a /etc/mosquitto/conf.d "$BACKUP/conf.d"
[ -f "$ACL_DST" ] && cp -a "$ACL_DST" "$BACKUP/aclfile" || true

echo "[*] Installing ACL file and enabling acl_file directive…"
cp "$SELF_DIR/aclfile" "$ACL_DST"
chmod 644 "$ACL_DST"
echo "acl_file $ACL_DST" > "$ACL_CONF"

rollback() {
    echo "[!] Rolling back ACL change…"
    rm -f "$ACL_CONF"
    cp -a "$BACKUP/conf.d/." /etc/mosquitto/conf.d/
    systemctl reload mosquitto 2>/dev/null || systemctl restart mosquitto
    die "ACL enable failed — rolled back. Broker restored."
}

echo "[*] Validating config in a throwaway mosquitto instance (port 18999)…"
TMPCONF="$(mktemp)"
printf 'persistence false\nacl_file %s\nlistener 18999 127.0.0.1\nallow_anonymous true\n' "$ACL_DST" > "$TMPCONF"
mosquitto -c "$TMPCONF" -v >/tmp/acl-validate.log 2>&1 &
VPID=$!
sleep 1
if ! python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',18999))==0 else 1)"; then
    cat /tmp/acl-validate.log; kill "$VPID" 2>/dev/null || true; rm -f "$TMPCONF"; rollback
fi
kill "$VPID" 2>/dev/null || true; rm -f "$TMPCONF"
echo "[*] Config parses OK."

echo "[*] Reloading production mosquitto (SIGHUP)…"
systemctl reload mosquitto 2>/dev/null || kill -HUP "$(cat /run/mosquitto/mosquitto.pid)"
sleep 2

# Health check: broker active + accepting TLS connections on 8883.
systemctl is-active --quiet mosquitto || rollback
python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',8883))==0 else 1)" || rollback

echo "[ok] ACL enabled. Backup retained at $BACKUP"
echo "     Verify live ingest (BigQuery freshness) now; if anything looks wrong:"
echo "       sudo rm -f $ACL_CONF && sudo cp -a $BACKUP/conf.d/. /etc/mosquitto/conf.d/ && sudo systemctl reload mosquitto"
