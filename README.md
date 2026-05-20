# Microgrid IIoT + Agentic AI Platform

**End-to-end industrial IoT intelligence for off-grid solar+battery microgrids — anomaly detection, Agentic LLM for fault triage, operator chat, and human-in-the-loop alerting on Google Cloud Platform.**

Live demo: **[microgrid.tinylab.ai](https://microgrid.tinylab.ai)** · Built by [Amplified Engineering](https://amplified.com.au) · Demonstrated at ODSC East, April 2026

---

## System Architecture

![Microgrid IIoT + Agentic AI Platform — System Architecture](docs/Comprehensive_System_Diagram_G3.png)

---

## The Problem

Off-grid solar+battery microgrids fail silently. A Victron inverter at a remote site can begin showing battery stress at 2 AM — voltage sagging, SOC dropping faster than the solar curve predicts, discharge current spiking against a weak cell. By the time a field engineer notices, the fault has cascaded.

Traditional SCADA approaches push raw telemetry to a dashboard and wait for a human to spot the pattern. The human never does — not across 12 sites, not at 2 AM, not when the dashboard is a table of numbers.

**What happens after the data arrives?** This platform answers that question.

---

## What It Does

| Capability | Description |
|---|---|
| **Real-time ingest** | MQTT/TLS from Victron hardware + 11 simulated sites → GCP Pub/Sub in <1s |
| **Anomaly detection** | Isolation Forest scores every telemetry message; critical events gate downstream agents |
| **AI fault triage** | Claude Haiku classifies fault type, severity, root cause, and recommended action |
| **Slack alerting** | Severity-coded Block Kit alerts with human-in-the-loop ACK gate |
| **Operator chat** | Claude Sonnet + LangGraph ReAct loop answers natural-language fleet questions with live BQ data |
| **Live dashboard** | Streamlit operations centre at microgrid.tinylab.ai — always-on, TLS, no laptop required |

End-to-end latency from fault to Slack alert: **~15 seconds**.

---

## Architecture — Four Tiers

```
┌──────────────────────────────────────────────────────────────────────┐
│  TIER 1 — EDGE                                                       │
│  Victron MultiPlus 24V · LiFePO4 banks · Rooftop PV                  │
│  Modbus TCP → SQLite → MQTT/TLS :8883 → GCP broker                   │
│  11 Docker-simulated sites + 1 live hardware node                    │
└──────────────────────────┬───────────────────────────────────────────┘
                           │  MQTT TLS, 60-second cadence
┌──────────────────────────▼───────────────────────────────────────────┐
│  TIER 2 — CLOUD INGEST  (GCP VM e2-small, australia-southeast1)      │
│  Mosquitto broker · per-device password auth · Redis live-state TTL  │
│  mqtt_to_pubsub.py (systemd) → schema validation → Pub/Sub           │
└──────────────────────────┬───────────────────────────────────────────┘
                           │  Pub/Sub push subscriptions
┌──────────────────────────▼───────────────────────────────────────────┐
│  TIER 3 — PROCESSING  (Cloud Run · BigQuery · GCS)                   │
│  Isolation Forest (200 trees, 16 features) → anomaly scoring         │
│  → LangGraph agent pipeline (4 agents, Claude Haiku + Sonnet)        │
└──────────────────────────┬───────────────────────────────────────────┘
                           │  BigQuery · Slack · HTTP
┌──────────────────────────▼───────────────────────────────────────────┐
│  TIER 4 — PRESENTATION                                               │
│  Streamlit Operations Dashboard · Operator Chat · ACK Gate           │
│  https://microgrid.tinylab.ai                                        │
└──────────────────────────────────────────────────────────────────────┘
```

---

## The Agent Layer

Four specialised agents — each a containerised FastAPI + LangGraph service on Cloud Run. Stateless, event-driven, independently deployable via GitHub Actions CI/CD.

### Agent 1 — Anomaly Detector
**Trigger:** every telemetry message via Pub/Sub push

Scores each reading against an Isolation Forest model. 16 features: 12 raw telemetry fields + four engineered derivatives (normalised voltage, efficiency ratio, SOC rate-of-change per minute, mode transitions per hour). Publishes only critical-severity anomalies (`score < −0.65`) downstream to prevent triage storms.

- Model: 200 estimators, trained on 23,176 readings across 12 sites
- Severity: critical (`< −0.65`) · high (`< −0.58`) · medium (`≥ −0.58`)

### Agent 2 — Triage Agent
**Trigger:** anomaly event via Pub/Sub push | **LLM:** Claude Haiku

Three-node LangGraph graph: `fetch_context → classify_fault → persist_results`. Fetches 30 minutes of BigQuery context, calls Haiku to classify fault type, severity, root cause, and recommended action in structured JSON. 120-minute per-site cooldown prevents re-triage storms.

### Agent 3 — Dispatch Agent
**Trigger:** triage complete event via Pub/Sub push

Builds severity-coded Slack Block Kit cards and routes to operators. Human-in-the-loop ACK gate: operator acknowledges via dashboard → streamed to `ack_events` BigQuery table → confirmation card sent to Slack. Permanent audit trail.

### Agent 4 — Operator Chat Agent
**Trigger:** operator question via Streamlit | **LLM:** Claude Sonnet 4.6

LangGraph ReAct loop with four BigQuery tools: `get_site_status`, `get_fleet_overview`, `get_recent_anomalies`, `get_telemetry_trend`. Answers questions like *"Why is site-07 in alarm?"* with live data, model scores, and technical reasoning.

---

## Operations Dashboard

Five pages at **[microgrid.tinylab.ai](https://microgrid.tinylab.ai)** — auto-refresh 15–300s, ACK gate banner on every page.

| Page | Contents |
|---|---|
| **Fleet Overview** | 5 KPI cards · site-status table with SOC bars · Solar vs Load chart |
| **Site Details** | SOC gauge · 6 KPI cards · SOC trend · Solar/Load overlay · Power Balance chart |
| **Anomaly Monitor** | Severity KPIs · timeline scatter · score histogram · anomaly count per site |
| **Operator Chat** | Natural-language interface to Agent 4 with tool-call attribution |
| **Settings** | ML model metadata · infrastructure summary |

---

## Repository Structure

```
agents/
  anomaly_detector/   Cloud Run — Isolation Forest scoring
  triage_agent/       Cloud Run — LangGraph + Claude Haiku fault classification
  chat_agent/         Cloud Run — LangGraph ReAct + Claude Sonnet operator chat
  dispatch_agent/     Cloud Run — Slack Block Kit alerts + /ack endpoint
dashboard/
  dashboard_app.py    Streamlit app (deployed at microgrid.tinylab.ai)
  requirements.txt
edge/
  sim_site.py         Single-site simulator (11 instances via Docker Compose)
  docker-compose.yml  11-site fleet simulator
  db2mqtt_microgrid.py  Hardware gateway (Victron Modbus → MQTT)
  ca.crt              TLS CA certificate for broker connections
ml/
  generate_historical.py  Synthetic training data generator
  spinup_notebook.sh      Vertex AI Workbench launcher
scripts/
  check_GCP.sh              GCP component health check
  deploy_dashboard_vm.sh    One-command dashboard VM deployment
  vm_setup_dashboard.sh     VM-side setup (Nginx, systemd, venv)
  microgrid-dashboard.service  systemd unit for Streamlit
  nginx-microgrid.conf      Nginx reverse proxy + WebSocket config
mqtt_to_pubsub.py     MQTT → Pub/Sub bridge with Redis cache (runs on VM)
docs/                 Architecture diagrams, operations manual, plans
.github/workflows/    CI/CD — auto-deploys changed Cloud Run services on push to main
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| Edge gateway | Python, Modbus TCP, SQLite, Paho MQTT |
| MQTT broker | Eclipse Mosquitto, TLS 1.2, per-device password auth |
| Message bus | Google Cloud Pub/Sub (3 topics, 4 subscriptions) |
| Time-series store | BigQuery (`microgrid_telemetry`, `anomaly_events`, `ack_events`) |
| Live cache | Redis (per-site state, TTL 120s) |
| ML model | scikit-learn Isolation Forest, joblib, GCS artefact store |
| Agent orchestration | LangGraph (StateGraph, ReAct loop) |
| LLM — triage | Anthropic Claude Haiku (`claude-haiku-4-5-20251001`) |
| LLM — chat | Anthropic Claude Sonnet (`claude-sonnet-4-6`) |
| Agent runtime | FastAPI + uvicorn, Docker, Cloud Run (australia-southeast1) |
| Dashboard | Streamlit + Plotly, Nginx, Let's Encrypt TLS |
| Alerting | Slack Block Kit via incoming webhook |
| Secrets | GCP Secret Manager |
| CI/CD | GitHub Actions — per-service Cloud Run deploy on push |

---

## Running the Components

**Dashboard** (live at microgrid.tinylab.ai — no local run needed):
```bash
# For local development only
streamlit run dashboard/dashboard_app.py
```

**11-site Docker Compose simulator:**
```bash
cd edge
BROKER_HOST=34.87.254.184 BROKER_PORT=8883 docker compose up -d
docker compose logs -f site-06   # tail a specific site
```

**Hardware gateway** (runs on nodeMINI/nodeG5 edge devices):
```bash
python edge/db2mqtt_microgrid.py
```

**Generate synthetic training data:**
```bash
python ml/generate_historical.py   # writes ml/historical_data.csv
```

**GCP health check:**
```bash
./scripts/check_GCP.sh
```

**Deploy/update dashboard on VM:**
```bash
./scripts/deploy_dashboard_vm.sh
```

---

## GCP Project

| Setting | Value |
|---|---|
| Project | `microgrid-demo` |
| Region | `australia-southeast1` |
| VM / MQTT broker | `34.87.254.184` (microgrid-broker, e2-small) |
| Dashboard URL | `https://microgrid.tinylab.ai` |
| Service account | `microgrid-agent@microgrid-demo.iam.gserviceaccount.com` |

**MQTT credentials (simulators):**
```
User: site-01 … site-11   Pass: site-pass-secret
User: hw-node-01           Pass: node-pass-secret
User: mqtt-bridge          Pass: bridge-pass-secret
```

---

## CI/CD

Push to `main` → GitHub Actions detects which `agents/*` subdirectory changed → deploys only that Cloud Run service (~3 min). Manual trigger available via Actions UI. Dashboard updates are deployed to the VM via `git pull` on `/opt/microgrid`.

---

## Key Design Decisions

**Detection → Reasoning → Dispatch hierarchy** keeps costs bounded: Isolation Forest runs on every message (cheap, fast); Haiku runs only on confirmed anomalies (12× cheaper than Sonnet for structured classification); dispatch is deterministic (no LLM); Sonnet handles only conversational queries (highest quality where it matters).

**Append-only BigQuery** — anomaly results, ACK events, and triage outputs are all new rows. BigQuery's streaming buffer blocks DML on recent rows; designing with this constraint gives an immutable audit trail for free.

**VM over Cloud Run for Streamlit** — Streamlit is a stateful, long-lived WebSocket application. Cloud Run's idle connection timeouts and per-instance session isolation make it the wrong runtime for this workload. The broker VM had spare headroom and a static IP already.

---

## Documentation

| Document | Location |
|---|---|
| Technical datasheet | `docs/DATASHEET.md` |
| Operations manual | `docs/OPERATIONS_MANUAL.md` |
| Work plan & sprint status | `docs/work_plan.txt` |
| Implementation history | `docs/progress.txt` |
| Dashboard migration plan | `docs/Dashboard_migration_plan.txt` |

---

*Deployed on Google Cloud Platform*
