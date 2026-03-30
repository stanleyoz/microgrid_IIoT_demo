# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A multi-site microgrid IIoT monitoring and anomaly detection platform targeting a conference demo (ODSC East, April 2026). The system connects real Victron inverter hardware and simulated sites to GCP, runs Isolation Forest anomaly detection, and uses a LangGraph multi-agent AI layer for intelligent operations.

**GCP Project**: `microgrid-demo` (region: `australia-southeast1`)
**VM/Broker IP**: `34.87.254.184`
**GitHub**: `https://github.com/stanleyoz/microgrid_IIoT_demo` (private)

## Repository Structure

```
agents/           Cloud Run microservices (anomaly_detector, triage_agent, chat_agent, dispatch_agent)
dashboard/        Streamlit app (dashboard_app.py, requirements.txt)
edge/             Hardware gateway + Docker Compose simulator (sim_site.py, db2mqtt_microgrid.py, docker-compose.yml)
ml/               Training notebook, data generation scripts, spinup_notebook.sh
scripts/          Operational GCP scripts (check_GCP.sh)
docs/             All documentation, plans, diagrams
.github/workflows GitHub Actions CI/CD (auto-deploys Cloud Run on push to main)
```

## Running the Components

**Streamlit Dashboard** (requires GCP ADC credentials):
```bash
streamlit run dashboard/dashboard_app.py
# Accessible at http://localhost:8501
```

**Docker Compose Simulator** (11 simulated microgrid sites):
```bash
# Against GCP broker (TLS) — run from edge/ directory
cd edge
BROKER_HOST=34.87.254.184 BROKER_PORT=8883 docker compose up -d

# Local time-accelerated testing (1 day per hour)
TIME_SCALE=24 INTERVAL_S=5 docker compose up -d

# Tail a specific site
docker compose logs -f site-06
```

**Hardware Gateway** (runs on nodeMINI/nodeG5 edge devices):
```bash
python edge/db2mqtt_microgrid.py
```

**Generate synthetic historical training data**:
```bash
python ml/generate_historical.py
# Writes to ml/historical_data.csv
```

**Install dashboard dependencies**:
```bash
pip install -r dashboard/requirements.txt
```

**Spin up retraining notebook** (Vertex AI Workbench):
```bash
./ml/spinup_notebook.sh
```

**Check GCP component status**:
```bash
./scripts/check_GCP.sh
```

## Architecture

### Data Flow (4 tiers)

```
Edge → MQTT (TLS 8883) → GCP VM → Pub/Sub → BigQuery / Isolation Forest → Streamlit + LangGraph Agents
```

**Tier 1 — Edge** (`edge/`)
- `db2mqtt_microgrid.py`: Reads Victron Modbus registers from a local SQLite DB (`/amp/var/dataout.db`) on nodeMINI hardware and publishes JSON to MQTT topic `microgrid/{site_id}/telemetry`
- `sim_site.py`: Simulates a single site with realistic solar curves, load profiles, and battery dynamics; runs as one Docker container per site (11 total via `docker-compose.yml`)

**Tier 2 — Cloud Ingest (GCP VM)**
- Mosquitto broker on port 8883 with TLS (`edge/ca.crt`) and per-device password auth
- `mqtt_to_pubsub.py` (systemd on VM, not in this repo): bridges MQTT → Pub/Sub, validates schema, updates Redis TTL cache
- Redis: per-site live state cache (TTL=120s), queried by the Operator Chat agent
- Pub/Sub topics: `microgrid-telemetry`, `microgrid-anomalies`, `microgrid-agent-events`

**Tier 3 — Processing** (`agents/`)
- BigQuery dataset `microgrid_db`, tables `microgrid_telemetry` (17 columns), `anomaly_events`, `ack_events`
- `anomaly_detector/`: Isolation Forest model loaded from GCS, scores telemetry, publishes anomalies
- `triage_agent/`: LangGraph 3-node graph — fetch BQ context → Claude Haiku classify → persist + publish. 120-min per-site cooldown.
- `chat_agent/`: LangGraph ReAct loop — Claude Sonnet + 4 BQ tools for fleet/site queries
- `dispatch_agent/`: Slack Block Kit alerts + `/ack` endpoint for human-in-the-loop acknowledgement

**Tier 4 — Presentation** (`dashboard/`)
- `dashboard_app.py`: Streamlit app — Fleet Overview, Site Details, Anomaly Monitor, Operator Chat, Settings
- Sidebar ACK gate: shows unacknowledged critical/high alerts one at a time with blinking indicator

### CI/CD
Push to `main` → GitHub Actions detects changed `agents/*` subdirectory → deploys only that Cloud Run service (~3 min). Manual trigger available via Actions UI.

### BigQuery Schema (key fields)
```
site_id, timestamp, battery_v, battery_soc, battery_current, battery_temp,
ac_input_v, ac_output_v, ac_output_i, ac_input_power, ac_output_power,
solar_w, load_w, inverter_state, inverter_temp, fault_code, power_balance_w
```

### MQTT Credentials (Docker Compose)
```
MQTT_USER: site-01 … site-11 (or hw-node-01 for hardware)
MQTT_PASS: site-pass-secret  (hw: node-pass-secret)
```

## Sprint Status

- **Sprint 1 (done)**: Multi-site MQTT ingest, TLS auth, BigQuery schema, Docker Compose simulator, hardware node connected
- **Sprint 2 (done)**: Isolation Forest + Cloud Run scoring, Streamlit dashboard, Slack/Twilio alerts
- **Sprint 3 (done)**: LangGraph agents (triage, chat, dispatch), human-in-the-loop ACK gate
- **Sprint 4 (active)**: Forecast agent, demo rehearsal, public URL (`tinylab.ai`)

Detailed sprint tasks in `docs/work_plan.txt`; current status in `docs/state_manifest.md`; full history in `docs/progress.txt`.
