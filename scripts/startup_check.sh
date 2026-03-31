#!/bin/bash
# startup_check.sh — microgrid platform health check + auto-restart
#
# Walks through every component in dependency order, checks status,
# restarts VM services if down, reports Cloud Run health, checks data flow.
#
# Run from project root:
#   ./scripts/startup_check.sh           # check only
#   ./scripts/startup_check.sh --sim     # also start simulator if not running
#   ./scripts/startup_check.sh --demo    # sim + accelerated time for demo
#
# Requires: gcloud authed, bq CLI, docker, ssh key at edge/id_microgrid_demo

set -euo pipefail

# ── Config ─────────────────────────────────────────────────────────────────────
PROJECT=microgrid-demo
REGION=australia-southeast1
VM_IP=34.87.254.184
VM_USER=stanl
SSH_KEY="$(pwd)/edge/id_microgrid_demo"
SSH="ssh -i $SSH_KEY -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=no"

AGENT_BASE="https://AGENT-633335742473.australia-southeast1.run.app"
AGENTS=("anomaly-detector" "triage-agent" "dispatch-agent" "chat-agent")
VM_SERVICES=("mosquitto" "redis-server" "mqtt-bridge")

START_SIM=false
DEMO_MODE=false
for arg in "$@"; do
  [[ "$arg" == "--sim"  ]] && START_SIM=true
  [[ "$arg" == "--demo" ]] && START_SIM=true && DEMO_MODE=true
done

# ── Colour helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

ok()      { echo -e "  ${GREEN}✓${NC}  $1"; }
fail()    { echo -e "  ${RED}✗${NC}  $1"; FAILURES+=("$1"); }
warn()    { echo -e "  ${YELLOW}⚠${NC}  $1"; WARNINGS+=("$1"); }
info()    { echo -e "  ${BLUE}→${NC}  $1"; }
fixed()   { echo -e "  ${GREEN}↻${NC}  $1 (restarted)"; RESTARTED+=("$1"); }
section() {
  echo ""
  echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════${NC}"
  echo -e "${BOLD}${BLUE}  $1${NC}"
  echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════${NC}"
}

FAILURES=(); WARNINGS=(); RESTARTED=()

# ── 1. GCP Auth ────────────────────────────────────────────────────────────────
section "1/7  GCP Authentication"

ACCOUNT=$(gcloud config get-value account 2>/dev/null || true)
if [[ -n "$ACCOUNT" ]]; then
  ok "gcloud authenticated as $ACCOUNT"
else
  fail "gcloud not authenticated"
  echo "       Fix: gcloud auth login"
  exit 1
fi

# Check ADC (needed for BQ from dashboard)
if gcloud auth application-default print-access-token &>/dev/null; then
  ok "Application Default Credentials valid"
else
  warn "Application Default Credentials not set — dashboard BQ queries will fail"
  info "Fix: gcloud auth application-default login"
fi

# ── 2. VM Connectivity ─────────────────────────────────────────────────────────
section "2/7  Broker VM  ($VM_IP)"

if [[ ! -f "$SSH_KEY" ]]; then
  fail "SSH key not found: $SSH_KEY"
  exit 1
fi

chmod 600 "$SSH_KEY"
if $SSH $VM_USER@$VM_IP "echo ok" &>/dev/null; then
  ok "SSH reachable"
else
  fail "Cannot reach VM at $VM_IP — check if VM is running"
  info "Fix: gcloud compute instances start microgrid-broker --zone=australia-southeast1-a --project=$PROJECT"
  echo ""
  echo -e "${RED}  Cannot continue without VM — aborting.${NC}"
  exit 1
fi

# ── 3. VM Services ─────────────────────────────────────────────────────────────
section "3/7  VM Services  (mosquitto · redis · mqtt-bridge)"

for SVC in "${VM_SERVICES[@]}"; do
  STATUS=$($SSH $VM_USER@$VM_IP "sudo systemctl is-active $SVC" 2>/dev/null || echo "unknown")
  if [[ "$STATUS" == "active" ]]; then
    ok "$SVC"
  else
    warn "$SVC not active (state: $STATUS) — restarting..."
    $SSH $VM_USER@$VM_IP "sudo systemctl restart $SVC" 2>/dev/null
    sleep 4
    STATUS=$($SSH $VM_USER@$VM_IP "sudo systemctl is-active $SVC" 2>/dev/null || echo "unknown")
    if [[ "$STATUS" == "active" ]]; then
      fixed "$SVC"
    else
      fail "$SVC restart failed — check: sudo journalctl -u $SVC -n 20"
    fi
  fi
done

# Spot-check bridge is actually publishing (look for recent log activity)
BRIDGE_LOG=$($SSH $VM_USER@$VM_IP \
  "sudo journalctl -u mqtt-bridge --since '3 minutes ago' --no-pager -q 2>/dev/null | wc -l")
if [[ "$BRIDGE_LOG" -gt 0 ]]; then
  ok "mqtt-bridge log activity confirmed ($BRIDGE_LOG lines in last 3 min)"
else
  warn "mqtt-bridge running but no recent log activity — may not be receiving MQTT messages yet"
fi

# ── 4. Pub/Sub Subscriptions ───────────────────────────────────────────────────
section "4/7  Pub/Sub Subscriptions"

declare -A SUBS=(
  ["bq-ingest-sub"]="microgrid-telemetry → BigQuery"
  ["anomaly-trigger-sub"]="microgrid-telemetry → anomaly-detector"
  ["triage-trigger-sub"]="microgrid-anomalies → triage-agent"
  ["dispatch-sub"]="microgrid-agent-events → dispatch-agent"
)

for SUB in "${!SUBS[@]}"; do
  ENDPOINT=$(gcloud pubsub subscriptions describe "$SUB" \
    --project=$PROJECT \
    --format="value(pushConfig.pushEndpoint)" 2>/dev/null || echo "")
  if [[ -n "$ENDPOINT" ]]; then
    ok "$SUB  →  ${SUBS[$SUB]}"
  else
    fail "$SUB missing or has no push endpoint"
  fi
done

# ── 5. Cloud Run Agent Health ──────────────────────────────────────────────────
section "5/7  Cloud Run Agents"

for AGENT in "${AGENTS[@]}"; do
  URL="${AGENT_BASE/AGENT/$AGENT}/health"
  HTTP=$(curl -s -o /tmp/cr_resp -w "%{http_code}" --max-time 15 "$URL" 2>/dev/null || echo "000")
  if [[ "$HTTP" == "200" ]]; then
    MODEL=$(python3 -c "import json,sys; d=json.load(open('/tmp/cr_resp')); print(d.get('model',''))" 2>/dev/null || echo "")
    [[ -n "$MODEL" ]] && ok "$AGENT  (model: $MODEL)" || ok "$AGENT"
  elif [[ "$HTTP" == "000" ]]; then
    warn "$AGENT timed out (cold start likely) — will wake on first Pub/Sub push"
  else
    fail "$AGENT returned HTTP $HTTP"
    info "Logs: gcloud run services logs read $AGENT --region=$REGION --project=$PROJECT --limit=20"
  fi
done

# ── 6. Data Flow (BigQuery) ────────────────────────────────────────────────────
section "6/7  Data Flow  (BigQuery freshness)"

# Recent telemetry
TELEM_COUNT=$(bq query --project_id=$PROJECT --use_legacy_sql=false \
  --format=csv --quiet \
  "SELECT COUNT(*) FROM microgrid_db.microgrid_telemetry
   WHERE timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 5 MINUTE)" \
  2>/dev/null | tail -1 | tr -d '[:space:]' || echo "0")

if [[ "${TELEM_COUNT:-0}" -gt 0 ]]; then
  ok "Telemetry flowing — $TELEM_COUNT rows in last 5 min"
else
  warn "No telemetry in last 5 minutes"
  info "Simulator may not be running — see step 7"
fi

# Recent anomalies
ANOM_COUNT=$(bq query --project_id=$PROJECT --use_legacy_sql=false \
  --format=csv --quiet \
  "SELECT COUNT(*) FROM microgrid_db.anomaly_events
   WHERE timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)" \
  2>/dev/null | tail -1 | tr -d '[:space:]' || echo "0")

if [[ "${ANOM_COUNT:-0}" -gt 0 ]]; then
  ok "Anomalies detected — $ANOM_COUNT events in last 30 min"
else
  warn "No anomaly events in last 30 min (normal if simulator just started)"
fi

# AI triage active?
TRIAGE_COUNT=$(bq query --project_id=$PROJECT --use_legacy_sql=false \
  --format=csv --quiet \
  "SELECT COUNT(*) FROM microgrid_db.anomaly_events
   WHERE agent_summary LIKE '[AI Triage]%'
     AND timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)" \
  2>/dev/null | tail -1 | tr -d '[:space:]' || echo "0")

if [[ "${TRIAGE_COUNT:-0}" -gt 0 ]]; then
  ok "AI triage active — $TRIAGE_COUNT Claude classifications in last 30 min"
else
  warn "No AI triage in last 30 min (cooldown may be active, or no anomalies yet)"
fi

# Pending ACKs
PENDING_ACKS=$(bq query --project_id=$PROJECT --use_legacy_sql=false \
  --format=csv --quiet \
  "SELECT COUNT(*) FROM microgrid_db.anomaly_events a
   LEFT JOIN microgrid_db.ack_events k
     ON k.site_id = a.site_id AND k.anomaly_timestamp = a.timestamp
   WHERE k.site_id IS NULL
     AND a.severity IN ('critical','high')
     AND a.agent_summary LIKE '[AI Triage]%'
     AND a.timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR)" \
  2>/dev/null | tail -1 | tr -d '[:space:]' || echo "0")

if [[ "${PENDING_ACKS:-0}" -gt 0 ]]; then
  warn "$PENDING_ACKS unacknowledged critical/high alert(s) pending in dashboard"
else
  ok "No pending ACKs"
fi

# ── 7. Simulator ───────────────────────────────────────────────────────────────
section "7/7  Simulator  (Docker Compose)"

if ! command -v docker &>/dev/null; then
  warn "Docker not found — skip simulator check"
else
  RUNNING=$(docker compose -f edge/docker-compose.yml ps --status running \
    --format json 2>/dev/null | python3 -c \
    "import json,sys; d=json.load(sys.stdin); print(len(d))" 2>/dev/null \
    || docker compose -f edge/docker-compose.yml ps -q 2>/dev/null | wc -l || echo 0)

  if [[ "${RUNNING:-0}" -ge 11 ]]; then
    if $DEMO_MODE; then
      warn "Simulator running — would restart in demo mode (TIME_SCALE=24)"
      info "Restarting in accelerated demo mode..."
      docker compose -f edge/docker-compose.yml down -q 2>/dev/null
      TIME_SCALE=24 INTERVAL_S=5 BROKER_HOST=$VM_IP BROKER_PORT=8883 \
        docker compose -f edge/docker-compose.yml up -d -q 2>/dev/null
      ok "Simulator restarted in demo mode (TIME_SCALE=24)"
    else
      ok "Simulator running ($RUNNING containers)"
    fi
  else
    warn "Simulator not running ($RUNNING/11 containers up)"
    if $START_SIM; then
      info "Starting simulator..."
      if $DEMO_MODE; then
        TIME_SCALE=24 INTERVAL_S=5 BROKER_HOST=$VM_IP BROKER_PORT=8883 \
          docker compose -f edge/docker-compose.yml up -d -q 2>/dev/null
        fixed "Simulator started in demo mode (TIME_SCALE=24, INTERVAL_S=5)"
      else
        BROKER_HOST=$VM_IP BROKER_PORT=8883 \
          docker compose -f edge/docker-compose.yml up -d -q 2>/dev/null
        fixed "Simulator started in normal mode"
      fi
    else
      info "To start: ./scripts/startup_check.sh --sim"
      info "For demo: ./scripts/startup_check.sh --demo"
    fi
  fi
fi

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${BLUE}  SUMMARY${NC}"
echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════${NC}"

if [[ ${#RESTARTED[@]} -gt 0 ]]; then
  echo -e "  ${GREEN}↻ Restarted:${NC} ${RESTARTED[*]}"
fi

if [[ ${#WARNINGS[@]} -gt 0 ]]; then
  echo -e "  ${YELLOW}⚠ Warnings:${NC}"
  for w in "${WARNINGS[@]}"; do echo -e "    · $w"; done
fi

if [[ ${#FAILURES[@]} -gt 0 ]]; then
  echo ""
  echo -e "  ${RED}✗ Failures:${NC}"
  for f in "${FAILURES[@]}"; do echo -e "    · $f"; done
  echo ""
  echo -e "  ${RED}Platform NOT fully operational — review failures above.${NC}"
  EXIT_CODE=1
else
  echo ""
  echo -e "  ${GREEN}${BOLD}✓ All checks passed — platform operational.${NC}"
  EXIT_CODE=0
fi

echo ""
echo -e "  Dashboard: ${BOLD}streamlit run dashboard/dashboard_app.py${NC}"
echo ""

exit $EXIT_CODE
