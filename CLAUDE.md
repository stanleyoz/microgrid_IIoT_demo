# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A multi-site microgrid IIoT monitoring and anomaly detection platform targeting a conference demo (ODSC East, April 2026). The system connects real Victron inverter hardware and simulated sites to GCP, runs Isolation Forest anomaly detection, and will add a LangGraph multi-agent AI layer for intelligent operations.

**GCP Project**: `microgrid-demo` (region: `australia-southeast1`)
**VM/Broker IP**: `34.87.254.184`

## Running the Components

**Streamlit Dashboard** (requires GCP ADC credentials):
```bash
streamlit run dashboard_app.py
# Accessible at http://localhost:8501
```

**Docker Compose Simulator** (11 simulated microgrid sites):
```bash
# Against GCP broker (TLS)
BROKER_HOST=34.87.254.184 BROKER_PORT=8883 docker compose up -d

# Local time-accelerated testing (1 day per hour)
TIME_SCALE=24 INTERVAL_S=5 docker compose up -d

# Tail a specific site
docker compose logs -f site-06
```

**Hardware Gateway** (runs on nodeMINI/nodeG5 edge devices):
```bash
python db2mqtt_microgrid.py
```

**Generate synthetic historical training data**:
```bash
python generate_historical.py
# Writes to historical_data.csv
```

**Install dependencies**:
```bash
pip install -r requirements.txt
```

## Architecture

### Data Flow (4 tiers)

```
Edge → MQTT (TLS 8883) → GCP VM → Pub/Sub → BigQuery / Isolation Forest → Streamlit + LangGraph Agents
```

**Tier 1 — Edge**
- `db2mqtt_microgrid.py`: Reads Victron Modbus registers from a local SQLite DB (`/amp/var/dataout.db`) on nodeMINI hardware and publishes JSON to MQTT topic `microgrid/{site_id}/telemetry`
- `sim_site.py`: Simulates a single site with realistic solar curves, load profiles, and battery dynamics; runs as one Docker container per site (11 total via `docker-compose.yml`)

**Tier 2 — Cloud Ingest (GCP VM)**
- Mosquitto broker on port 8883 with TLS (`ca.crt`) and per-device password auth
- `mqtt_to_pubsub.py` (systemd, not in this repo): bridges MQTT → Pub/Sub, validates schema, updates Redis TTL cache
- Redis: per-site live state cache (TTL=120s), queried by the Operator Chat agent
- Pub/Sub topics: `microgrid-telemetry`, `microgrid-anomalies`, `microgrid-agent-events`

**Tier 3 — Processing**
- BigQuery dataset `microgrid_db`, tables `microgrid_telemetry` (17 columns) and `anomaly_events`
- Isolation Forest model (Vertex AI Workbench notebook): trained on 13 raw fields + 4 derived features; served via Cloud Run `/score`
- LangGraph orchestrator (Cloud Run, planned Sprint 3): 4 agents — Operator Chat, Anomaly Triage, Dispatch (Slack/Twilio/email), Forecast

**Tier 4 — Presentation**
- `dashboard_app.py`: Streamlit app with fleet overview, per-site time-series, anomaly monitor, and settings (anomaly threshold slider → ML contamination param)

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

- **Sprint 1 (current)**: Multi-site MQTT ingest, TLS auth, BigQuery schema, Docker Compose simulator, hardware node connected
- **Sprint 2**: Isolation Forest + Cloud Run scoring endpoint, Streamlit dashboard, Slack/Twilio alerts
- **Sprint 3**: LangGraph orchestrator + Operator Chat / Triage / Dispatch agents, human-in-the-loop gates
- **Sprint 4**: Forecast agent, demo rehearsal, public URL (`tinylab.ai`)

Detailed sprint tasks and risk register are in `work_plan.txt`; current status matrix is in `state_manifest.md`.
