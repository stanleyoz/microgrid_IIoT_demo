#!/usr/bin/env bash
# Shared helpers for customer lifecycle scripts (source this file).
# All state lives in the mosquitto passwd file + a file-based registry, so the
# whole flow is automatable and dependency-light.

PASSWD_FILE="${PASSWD_FILE:-/etc/mosquitto/passwd}"
REGISTRY_DIR="${REGISTRY_DIR:-/var/lib/microgrid-registry}"

_have_systemd() { command -v systemctl >/dev/null && [ -d /run/systemd/system ]; }

reload_broker() {
    if _have_systemd; then
        systemctl reload mosquitto 2>/dev/null && return 0
    fi
    if [ -f /run/mosquitto/mosquitto.pid ]; then
        kill -HUP "$(cat /run/mosquitto/mosquitto.pid)" 2>/dev/null && return 0
    fi
    # Fallback (e.g. test container): HUP any mosquitto process.
    pkill -HUP mosquitto 2>/dev/null || true
}

add_credential() {  # <site_id> <secret>
    mosquitto_passwd -b "$PASSWD_FILE" "$1" "$2"
}

remove_credential() {  # <site_id>
    mosquitto_passwd -D "$PASSWD_FILE" "$1" 2>/dev/null || true
}

cred_exists() {  # <site_id>
    cut -d: -f1 "$PASSWD_FILE" 2>/dev/null | grep -qx "$1"
}

revoke_unit() {  # <site_id> -> systemd unit name
    echo "cust-revoke-$(echo "$1" | tr -c 'a-zA-Z0-9' '-')"
}

schedule_revoke() {  # <site_id> <hours>
    _have_systemd || { echo "[i] (no systemd — skipping auto-revoke timer for $1)" >&2; return 0; }
    local unit; unit="$(revoke_unit "$1")"
    systemd-run --on-active="${2}h" --unit="$unit" \
        "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deprovision_customer.sh" "$1" >/dev/null
}

cancel_revoke() {  # <site_id>
    _have_systemd || return 0
    systemctl stop "$(revoke_unit "$1").timer" 2>/dev/null || true
    systemctl reset-failed "$(revoke_unit "$1")"* 2>/dev/null || true
}

# ── registry (one JSON file per customer) ─────────────────────────────────────
reg_file() { echo "$REGISTRY_DIR/$1.json"; }

registry_create() {  # <guid> <customer_name> <hours>
    mkdir -p "$REGISTRY_DIR"
    local now exp
    now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exp="$(date -u -d "+$3 hours" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "")"
    cat > "$(reg_file "$1")" <<EOF
{
  "guid": "$1",
  "customer_name": "$2",
  "status": "active",
  "created": "$now",
  "expires": "$exp",
  "trial_hours": $3,
  "devices": []
}
EOF
}

registry_add_device() {  # <guid> <site_id>
    local f; f="$(reg_file "$1")"
    python3 - "$f" "$2" <<'PY'
import json, sys
f, dev = sys.argv[1], sys.argv[2]
d = json.load(open(f))
if dev not in d["devices"]:
    d["devices"].append(dev)
json.dump(d, open(f, "w"), indent=2)
PY
}

registry_devices() {  # <guid> -> prints site_ids
    local f; f="$(reg_file "$1")"
    [ -f "$f" ] || return 0
    python3 -c "import json,sys; print('\n'.join(json.load(open(sys.argv[1]))['devices']))" "$f"
}

registry_active() {  # <guid> -> 0 if active
    local f; f="$(reg_file "$1")"
    [ -f "$f" ] || return 1
    [ "$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['status'])" "$f")" = "active" ]
}

registry_remove() {  # <guid>
    rm -f "$(reg_file "$1")"
}

next_device_index() {  # <guid> -> NN (zero-padded)
    local n; n="$(registry_devices "$1" | grep -c .)"
    printf '%02d' "$((n + 1))"
}

gen_secret() { openssl rand -hex 16 2>/dev/null || head -c16 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
gen_guid()   { cat /proc/sys/kernel/random/uuid 2>/dev/null | tr -d '-' | cut -c1-12; }
