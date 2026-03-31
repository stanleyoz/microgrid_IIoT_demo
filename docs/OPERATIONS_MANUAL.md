# Microgrid IIoT Platform — Operations Manual

**GCP Project:** `microgrid-demo` · **Region:** `australia-southeast1` · **Broker VM:** `34.87.254.184`

---

## System Component Map

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  LOCAL DEV MACHINE                                                          │
│  ┌──────────────────────────────────┐   ┌──────────────────────────────┐   │
│  │  Docker Compose Simulator        │   │  Streamlit Dashboard         │   │
│  │  (edge/docker-compose.yml)       │   │  dashboard/dashboard_app.py  │   │
│  │  11 × sim_site.py containers     │   │  http://localhost:8501        │   │
│  └──────────────┬───────────────────┘   └──────────────────────────────┘   │
└─────────────────┼───────────────────────────────────────────────────────────┘
                  │ MQTT TLS 8883
┌─────────────────▼───────────────────────────────────────────────────────────┐
│  GCP VM  34.87.254.184  (microgrid-broker, e2-small)                        │
│  ┌─────────────┐  ┌──────────────────────────────────────────────────────┐  │
│  │  Mosquitto  │  │  mqtt_to_pubsub.py  (systemd: mqtt-bridge)           │  │
│  │  port 8883  │→ │  validates schema, publishes to Pub/Sub,             │  │
│  │  TLS + auth │  │  updates Redis live-state cache (TTL 120s)           │  │
│  └─────────────┘  └──────────────────────────────────────────────────────┘  │
│  ┌─────────────┐                                                             │
│  │  Redis      │  (port 6379, live site state cache)                        │
│  │  port 6379  │                                                             │
│  └─────────────┘                                                             │
└──────────────────────────────────────────────────────────────────────────────┘
                  │ Pub/Sub: microgrid-telemetry
┌─────────────────▼───────────────────────────────────────────────────────────┐
│  CLOUD RUN SERVICES  (auto-scale, scale-to-zero)                            │
│                                                                              │
│  anomaly-detector ◄── Pub/Sub push (anomaly-trigger-sub)                    │
│    Isolation Forest scoring → writes anomaly_events BQ                      │
│    → publishes to microgrid-anomalies                                        │
│                                                                              │
│  triage-agent     ◄── Pub/Sub push (triage-trigger-sub)                     │
│    Claude Haiku fault classification → enriches anomaly_events BQ           │
│    → publishes to microgrid-agent-events                                     │
│                                                                              │
│  dispatch-agent   ◄── Pub/Sub push (dispatch-sub)                           │
│    Slack Block Kit alerts + /ack endpoint (called by dashboard)              │
│                                                                              │
│  chat-agent       ◄── HTTP POST /chat (called by dashboard)                 │
│    Claude Sonnet ReAct loop + BQ query tools                                 │
└──────────────────────────────────────────────────────────────────────────────┘
                  │ BigQuery reads
┌─────────────────▼───────────────────────────────────────────────────────────┐
│  BIGQUERY  microgrid_db                                                      │
│  microgrid_telemetry  ·  anomaly_events  ·  ack_events                      │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Dependency Order

Some components must be running before others make sense:

```
VM (Mosquitto + Redis + mqtt-bridge)         ← must be up first
        ↓
Simulator OR Hardware gateway                ← produces telemetry
        ↓
Pub/Sub                                      ← always on (GCP-managed)
        ↓
anomaly-detector Cloud Run                   ← auto-wakes on Pub/Sub push
        ↓
triage-agent Cloud Run                       ← auto-wakes on anomaly push
        ↓
dispatch-agent Cloud Run                     ← auto-wakes on triage push
        ↓
Slack workspace                              ← receives alerts
        ↓
Streamlit dashboard                          ← operator view (start any time)
```

Cloud Run services **auto-start** on their first incoming Pub/Sub push.
The dashboard can be started at any point — it only reads, never blocks the pipeline.

---

## Pre-Flight Checklist

Run this before any session to confirm GCP infrastructure is healthy:

```bash
./scripts/check_GCP.sh
```

Expected output — all 4 Cloud Run services listed as READY, 3 Pub/Sub topics,
3 subscriptions with push endpoints, VM RUNNING, 3 BigQuery tables, secrets present.

Verify VM services over SSH:

```bash
ssh -i edge/id_microgrid_demo stanl@34.87.254.184

# Check all three services
sudo systemctl status mosquitto mqtt-bridge redis-server --no-pager

# Expected: all three Active: active (running)
```

Quick BQ data freshness check (run locally):

```bash
bq query --project_id=microgrid-demo --use_legacy_sql=false \
  "SELECT site_id, MAX(timestamp) as last_seen
   FROM microgrid_db.microgrid_telemetry
   GROUP BY site_id ORDER BY last_seen DESC LIMIT 5"
```

If timestamps are recent (within the last few minutes) and 11+ sites appear,
the full ingest pipeline is healthy.

---

## Startup Sequence

### Step 1 — Verify / Restart VM Services

```bash
ssh -i edge/id_microgrid_demo stanl@34.87.254.184
```

If any service is not running:

```bash
# Restart individually as needed
sudo systemctl restart mosquitto
sudo systemctl restart redis-server
sudo systemctl restart mqtt-bridge

# Confirm
sudo systemctl status mosquitto mqtt-bridge redis-server --no-pager

# Watch bridge logs for first messages (optional)
sudo journalctl -u mqtt-bridge -f
```

Exit SSH once services are confirmed running.

---

### Step 2A — Start the Simulator (simulated sites)

Run from the project root:

```bash
cd edge

# Standard mode — real-time, against GCP broker
BROKER_HOST=34.87.254.184 BROKER_PORT=8883 docker compose up -d

# Demo/test mode — accelerated time (1 day per hour), faster anomaly generation
TIME_SCALE=24 INTERVAL_S=5 \
  BROKER_HOST=34.87.254.184 BROKER_PORT=8883 docker compose up -d
```

Verify all 11 containers are running:

```bash
docker compose ps
# All 11 site-XX containers should show status: Up
```

Watch a specific site's output:

```bash
docker compose logs -f site-06
# Should see JSON payloads being published every 10s
```

Confirm data arriving in BQ (wait ~30 seconds after starting):

```bash
bq query --project_id=microgrid-demo --use_legacy_sql=false \
  "SELECT COUNT(*) as rows, MAX(timestamp) as latest
   FROM microgrid_db.microgrid_telemetry
   WHERE timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 MINUTE)"
```

Expected: rows > 0 and latest within the last 2 minutes.

---

### Step 2B — Start the Hardware Gateway (physical Victron site)

On the nodeMINI / nodeG5 edge device:

```bash
python edge/db2mqtt_microgrid.py
```

This reads from `/amp/var/dataout.db` (Victron Venus OS SQLite) every 10 seconds
and publishes as `hw-node-01`. Hardware and simulator can run simultaneously —
they use different `site_id` values.

Confirm hw-node-01 appearing in BQ:

```bash
bq query --project_id=microgrid-demo --use_legacy_sql=false \
  "SELECT site_id, MAX(timestamp) as last_seen
   FROM microgrid_db.microgrid_telemetry
   WHERE site_id = 'hw-node-01'
   GROUP BY site_id"
```

---

### Step 3 — Verify the Anomaly Detection Pipeline

The anomaly-detector wakes automatically when Pub/Sub delivers telemetry.
Check it processed something:

```bash
bq query --project_id=microgrid-demo --use_legacy_sql=false \
  "SELECT site_id, fault_type, severity, timestamp
   FROM microgrid_db.anomaly_events
   ORDER BY timestamp DESC LIMIT 5"
```

If `agent_summary` starts with `[AI Triage]`, the full chain
(anomaly-detector → triage-agent → Claude Haiku) has completed.

Check Cloud Run logs directly if the table is empty:

```bash
gcloud run services logs read anomaly-detector \
  --region=australia-southeast1 --project=microgrid-demo --limit=20

gcloud run services logs read triage-agent \
  --region=australia-southeast1 --project=microgrid-demo --limit=20
```

---

### Step 4 — Verify Slack Alerts

Open your Slack workspace and confirm the `#microgrid-alerts` channel (or
whichever channel the webhook points to) is receiving messages.

A healthy alert looks like:
- Colour-coded severity bar (🔴 critical, 🟠 high, 🟡 medium)
- Fields: site ID, fault type, root cause, recommended action
- AI Summary section
- Timestamp

If no Slack messages are appearing but anomaly_events has rows:

```bash
gcloud run services logs read dispatch-agent \
  --region=australia-southeast1 --project=microgrid-demo --limit=20
# Look for "slack_sent: true" or any error messages
```

---

### Step 5 — Start the Streamlit Dashboard

Requires GCP Application Default Credentials on the local machine:

```bash
# One-time setup if not already done
gcloud auth application-default login
```

Start the dashboard:

```bash
streamlit run dashboard/dashboard_app.py
# Opens at http://localhost:8501
```

Navigate through the pages to verify each is loading:

| Page | What to check |
|---|---|
| Fleet Overview | Active sites count matches running containers, KPI cards populated |
| Site Details | Select any site, SOC gauge shows a value, time-series charts render |
| Anomaly Monitor | Events table has rows, severity breakdown cards have counts |
| Operator Chat | Type "What is the fleet status?" — agent should respond with live data |
| Settings | Model info card shows Isolation Forest metadata |

Sidebar: if any unacknowledged critical/high alerts exist from the last 6 hours,
the blinking red dot and ACK panel will appear automatically.

---

## Normal Operations

### Monitoring the Live Pipeline

**Dashboard auto-refresh:** configured in the sidebar (default 30s).
The fleet overview and anomaly monitor update automatically.

**Agent activity indicator:** the green pulse in the sidebar confirms
Claude Haiku triage ran within the last 5 minutes.

**Anomaly rate:** at 5% contamination, expect ~1 anomaly per site per ~3 minutes
under the simulator's normal operating pattern.

**Triage cooldown:** the triage-agent will only call Claude Haiku once per site
per 120 minutes (non-demo mode). You will see `"status": "cooldown"` in the
triage-agent logs for subsequent anomalies from the same site within that window.

---

### Acknowledging Alerts (Human-in-the-Loop)

When a critical or high severity alert appears:

1. The sidebar shows the ACK banner with a blinking red dot and alert count
2. The top unacknowledged alert is displayed with severity badge, fault type,
   site ID, timestamp, and AI triage summary
3. Click **✓ ACK** to acknowledge
4. The dashboard immediately removes it from the queue (local session state)
5. A green "✅ ACKNOWLEDGED" confirmation card is posted to Slack
6. The acknowledgement is recorded in `microgrid_db.ack_events` in BigQuery

If an alert was acknowledged on another session/device, it will disappear
from the queue on the next 20-second cache refresh.

---

### Operator Chat

Navigate to the **Operator Chat** page. Sample questions for common scenarios:

```
"What is the current fleet status?"
"Which sites have the lowest battery SOC?"
"Show me recent anomalies for site-06"
"What happened at site-03 in the last hour?"
"Are there any critical alerts I should know about?"
"What is the power balance trend for site-09?"
```

The chat agent queries live BigQuery data on every question. Responses include
tool usage footers showing which data sources were queried.

**Note:** Auto-refresh is disabled on the Operator Chat page to prevent the
page reloading mid-conversation. Switch to another page to re-enable refresh.

---

## Demo Mode

Switch from cost-controlled idle mode to snappy demo mode before a presentation:

### 1 — Set triage cooldown to 5 minutes

Edit `agents/triage_agent/main.py`:

```python
COOLDOWN = timedelta(minutes=5)   # demo mode
# COOLDOWN = timedelta(minutes=120)  # non-demo / cost-controlled
```

Commit and push — GitHub Actions redeploys triage-agent automatically (~3 min):

```bash
git add agents/triage_agent/main.py
git commit -m "demo: set triage cooldown to 5 minutes"
git push origin main
```

Monitor the Actions tab on GitHub to confirm the deploy completes before demo start.

### 2 — Accelerate the simulator

```bash
cd edge
docker compose down
TIME_SCALE=24 INTERVAL_S=5 \
  BROKER_HOST=34.87.254.184 BROKER_PORT=8883 docker compose up -d
```

At TIME_SCALE=24, one simulated day passes per real hour — anomalies will
appear much more frequently for a compelling live demo.

### 3 — Pre-clear the ACK queue

Run a quick BQ check to see if there are old unacknowledged alerts that
would clutter the demo:

```bash
bq query --project_id=microgrid-demo --use_legacy_sql=false \
  "SELECT COUNT(*) FROM microgrid_db.anomaly_events a
   LEFT JOIN microgrid_db.ack_events k
     ON k.site_id = a.site_id AND k.anomaly_timestamp = a.timestamp
   WHERE k.site_id IS NULL
     AND a.severity IN ('critical','high')
     AND a.agent_summary LIKE '[AI Triage]%'
     AND a.timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR)"
```

If the count is high, acknowledge old alerts through the dashboard before the
demo starts, or bulk-insert ACK rows for the old events.

### 4 — Revert after demo

```bash
# Restore non-demo cooldown
# Edit COOLDOWN = timedelta(minutes=120) in agents/triage_agent/main.py
git add agents/triage_agent/main.py
git commit -m "chore: restore 120-min triage cooldown post-demo"
git push origin main

# Stop accelerated simulator, restart in real-time mode
cd edge
docker compose down
BROKER_HOST=34.87.254.184 BROKER_PORT=8883 docker compose up -d
```

---

## Shutdown Sequence

### Stopping the Simulator

```bash
cd edge
docker compose down
# All 11 site containers stop; no data loss (BQ data is permanent)
```

### Stopping the Dashboard

`Ctrl+C` in the terminal running Streamlit.

### Stopping the Hardware Gateway

`Ctrl+C` on the edge device running `db2mqtt_microgrid.py`.

### VM Services — Leave Running

The VM (Mosquitto, Redis, mqtt-bridge) should be **left running** between sessions.
They are low-cost (e2-small ~$13/month) and are required to be up before the
simulator or hardware can connect.

Only stop VM services if doing maintenance:

```bash
ssh -i edge/id_microgrid_demo stanl@34.87.254.184
sudo systemctl stop mqtt-bridge mosquitto redis-server
```

### Cloud Run — Leave Running (scale-to-zero)

Cloud Run services scale to zero automatically when there is no traffic.
There is no cost when idle. Do not manually stop them.

---

## Deploying Code Changes

After any code change to an agent or the dashboard:

```bash
git add <changed files>
git commit -m "<description>"
git push origin main
```

GitHub Actions automatically detects which `agents/` subdirectory changed and
redeploys only that service. Monitor progress at:
`https://github.com/stanleyoz/microgrid_IIoT_demo/actions`

Deploy takes ~3 minutes. The old revision continues serving traffic until the
new one passes health checks — zero downtime.

**Manual deploy** (without a code change, e.g. to pick up a new Secret Manager
secret value):
- GitHub → Actions → Deploy Cloud Run Services → Run workflow → select service

---

## Troubleshooting

### No data appearing in BigQuery

1. Check simulator is running: `docker compose ps` — all containers Up
2. Check VM bridge is running: SSH → `sudo systemctl status mqtt-bridge`
3. Check bridge logs: `sudo journalctl -u mqtt-bridge -n 50`
4. Check Pub/Sub is receiving: GCP Console → Pub/Sub → microgrid-telemetry → Metrics
5. Check BQ subscription: `gcloud pubsub subscriptions describe bq-ingest-sub --project=microgrid-demo`

### Anomaly events table empty (data in telemetry but no anomalies)

1. Check anomaly-detector health:
   `curl https://anomaly-detector-633335742473.australia-southeast1.run.app/health`
2. Check anomaly-detector logs:
   `gcloud run services logs read anomaly-detector --region=australia-southeast1 --project=microgrid-demo --limit=30`
3. Verify the Pub/Sub subscription push endpoint points to the correct URL:
   `gcloud pubsub subscriptions describe anomaly-trigger-sub --project=microgrid-demo`
4. The anomaly rate is 5% — at 10 msg/s, expect ~1 anomaly every ~20 seconds.
   Wait at least 2 minutes before concluding nothing is working.

### No AI triage summaries ([AI Triage] prefix missing from anomaly_events)

1. Anomaly_events has rows but no `[AI Triage]` prefix → triage-agent not running
2. Check triage-agent logs for cooldown messages vs errors:
   `gcloud run services logs read triage-agent --region=australia-southeast1 --project=microgrid-demo --limit=30`
3. Verify ANTHROPIC_API_KEY secret is accessible:
   `gcloud secrets versions access latest --secret=anthropic-api-key --project=microgrid-demo`
4. Check triage-trigger-sub push endpoint:
   `gcloud pubsub subscriptions describe triage-trigger-sub --project=microgrid-demo`

### No Slack alerts

1. Check dispatch-agent health:
   `curl https://dispatch-agent-633335742473.australia-southeast1.run.app/health`
   Response should include `"slack_configured": true`
2. Check dispatch-agent logs for `slack_sent` status:
   `gcloud run services logs read dispatch-agent --region=australia-southeast1 --project=microgrid-demo --limit=20`
3. Verify slack-webhook-url secret:
   `gcloud secrets versions access latest --secret=slack-webhook-url --project=microgrid-demo`
4. Dispatch-agent only sends for severity critical/high/medium — low is suppressed.

### Operator Chat not responding

1. Check chat-agent health:
   `curl https://chat-agent-633335742473.australia-southeast1.run.app/health`
2. Verify CHAT_AGENT_URL in dashboard is pointing to the correct URL
3. Check chat-agent logs:
   `gcloud run services logs read chat-agent --region=australia-southeast1 --project=microgrid-demo --limit=20`

### Dashboard showing stale data

1. Check the auto-refresh interval in the sidebar — increase frequency if needed
2. Force a cache clear: Settings page → any slider adjustment triggers requery
3. Check GCP ADC credentials are current:
   `gcloud auth application-default print-access-token`
   If this fails, re-run: `gcloud auth application-default login`

### ACK count not updating after acknowledging

1. The local session state gives immediate visual feedback — count drops instantly
2. BQ streaming buffer takes ~90 seconds to be fully queryable — the alert may
   briefly reappear on the next cache refresh then disappear permanently
3. This is expected behaviour — not a bug. Wait 2 minutes after ACK.

---

## Quick Reference — Key URLs and Commands

| Item | Value |
|---|---|
| Broker VM | `34.87.254.184` |
| MQTT port | `8883` (TLS) |
| Dashboard (local) | `http://localhost:8501` |
| anomaly-detector | `https://anomaly-detector-633335742473.australia-southeast1.run.app` |
| triage-agent | `https://triage-agent-633335742473.australia-southeast1.run.app` |
| dispatch-agent | `https://dispatch-agent-633335742473.australia-southeast1.run.app` |
| chat-agent | `https://chat-agent-633335742473.australia-southeast1.run.app` |
| GitHub Actions | `https://github.com/stanleyoz/microgrid_IIoT_demo/actions` |
| GCP Console | `https://console.cloud.google.com/home/dashboard?project=microgrid-demo` |

```bash
# SSH to broker VM
ssh -i edge/id_microgrid_demo stanl@34.87.254.184

# Full GCP status check
./scripts/check_GCP.sh

# Start simulator (normal)
cd edge && BROKER_HOST=34.87.254.184 BROKER_PORT=8883 docker compose up -d

# Stop simulator
cd edge && docker compose down

# Start dashboard
streamlit run dashboard/dashboard_app.py

# View Cloud Run logs
gcloud run services logs read SERVICE-NAME \
  --region=australia-southeast1 --project=microgrid-demo --limit=30

# Health check all agents
for svc in anomaly-detector triage-agent dispatch-agent chat-agent; do
  echo -n "$svc: "
  curl -s https://${svc}-633335742473.australia-southeast1.run.app/health
  echo
done
```
