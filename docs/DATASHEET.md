# Microgrid Intelligence Platform
## Agentic AI for Industrial IoT Operations
### tinylab.ai · Amplified Engineering

---

## The Problem

Off-grid solar+battery microgrids fail silently. A Victron inverter in a remote site can begin showing battery stress at 2 AM — voltage sagging, SOC dropping faster than the solar curve predicts, discharge current spiking against a weak cell. By the time a field engineer notices, the fault has cascaded.

Traditional SCADA approaches push raw telemetry to a dashboard and wait for a human to spot the pattern. The human never does — not across 12 sites, not at 2 AM, not when the dashboard is a table of numbers.

The question is not whether to instrument your microgrids. You already do that. The question is: **what happens after the data arrives?**

---

## What We Built

A production-grade, end-to-end IIoT intelligence platform that connects real inverter hardware to a four-agent AI system — detecting anomalies automatically, classifying faults in natural language, alerting operators through Slack, and answering operational questions in plain English.

Built on Google Cloud Platform. Deployed and running live. Demonstrated on real Victron MultiPlus 24V hardware.

---

## Architecture — Four Tiers

```
┌─────────────────────────────────────────────────────────────────────┐
│  TIER 1 — EDGE                                                      │
│  Victron MultiPlus inverters · 24V LiFePO4 banks · Rooftop PV      │
│  Modbus TCP → SQLite → MQTT/TLS (8883) → GCP broker                │
│  11 simulated sites + 1 live hardware node (nodeMINI/nodeG5)        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  MQTT TLS, 10-second cadence
┌──────────────────────────────▼──────────────────────────────────────┐
│  TIER 2 — CLOUD INGEST (GCP VM e2-small, australia-southeast1)      │
│  Mosquitto broker · per-device TLS auth · Redis live-state cache    │
│  mqtt_to_pubsub.py (systemd) → schema validation → Pub/Sub          │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  Pub/Sub push subscriptions
┌──────────────────────────────▼──────────────────────────────────────┐
│  TIER 3 — PROCESSING (Cloud Run · BigQuery · GCS)                   │
│  17-column telemetry schema → Isolation Forest (200 trees, 16       │
│  features) → anomaly scoring → AI agent pipeline (4 agents)         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  BigQuery · Slack · HTTP
┌──────────────────────────────▼──────────────────────────────────────┐
│  TIER 4 — PRESENTATION                                              │
│  Streamlit Operations Dashboard · Operator Chat · ACK Gate          │
└─────────────────────────────────────────────────────────────────────┘
```

**Data flow (end-to-end latency: ~15 seconds from fault to Slack alert)**

```
Inverter → MQTT TLS → Pub/Sub → anomaly-detector → microgrid-anomalies
  → triage-agent (Claude Haiku) → microgrid-agent-events
    → dispatch-agent → Slack
    → dashboard (live BQ query)
```

---

## The Agent Layer — Four Specialised Agents

Every agent is a containerised FastAPI + LangGraph service on Cloud Run. Stateless, event-driven, independently deployable.

### Agent 1 — Anomaly Detector
**Trigger:** every telemetry message via Pub/Sub push
**Stack:** scikit-learn Isolation Forest, Cloud Run, GCS model artefacts

Scores each telemetry reading against a trained Isolation Forest model. 16 features: 12 raw telemetry fields plus four engineered derivatives — normalised voltage, efficiency ratio, SOC rate-of-change per minute, and inverter mode transitions per hour. Flags ~5% of readings as anomalous (configurable contamination parameter). Writes anomaly events to BigQuery and publishes to `microgrid-anomalies` Pub/Sub topic.

**Key spec:**
- Model: 200 estimators, trained on 23,176 readings across 12 sites
- Threshold: score < −0.52 (configurable via dashboard slider)
- Severity classification: critical (< −0.65) · high (< −0.58) · medium (≥ −0.58)

---

### Agent 2 — Triage Agent
**Trigger:** anomaly event via Pub/Sub push
**Stack:** LangGraph 3-node pipeline, Claude Haiku (claude-haiku-4-5), BigQuery

The fault analyst. On each anomaly, fetches 30 minutes of historical context from BigQuery (SOC range, voltage envelope, solar/load averages, temperatures), then calls Claude Haiku with a structured prompt to produce:

- `fault_type` — one of: overvoltage, undervoltage, soc_drop, grid_outage, thermal, power_balance, battery_stress, unknown
- `severity` — critical / high / medium / low
- `root_cause` — one-sentence technical explanation
- `agent_summary` — 2–3 sentence operator-facing narrative
- `recommended_action` — concise field instruction

**LangGraph pipeline:** `fetch_context` → `classify_fault` → `persist_results` → END

Cost control: 10-minute per-site cooldown prevents re-triage storms. Haiku vs Sonnet: ~12× cheaper per call with no quality loss on structured classification tasks.

---

### Agent 3 — Dispatch Agent
**Trigger:** `triage_complete` event via Pub/Sub push
**Stack:** LangGraph 2-node pipeline, Slack Block Kit, Cloud Run

Routes triage results to operators. Builds severity-coded Slack Block Kit cards — colour bars, emoji severity indicators, AI analysis, root cause, recommended action. Critical alerts include an explicit acknowledgement prompt. Suppresses low-severity events to prevent alert fatigue.

**LangGraph pipeline:** `route` → `send_slack` → END

Human-in-the-loop gate: operator acknowledges via dashboard → ACK streamed to BigQuery `ack_events` table → green Slack confirmation card sent. Acknowledgement is permanent audit trail.

Slack severity palette: 🔴 #E74C3C critical · 🟠 #E67E22 high · 🟡 #F1C40F medium

---

### Agent 4 — Operator Chat Agent
**Trigger:** operator question via Streamlit dashboard
**Stack:** LangGraph ReAct loop, Claude Sonnet 4.6, BigQuery tools

The most visible agent. Answers natural-language questions from field engineers with live data. Uses a ReAct (Reason + Act) loop — Claude decides which tools to call, inspects results, and iterates until it has enough data to answer.

**Tools available to the agent:**
| Tool | Description |
|------|-------------|
| `get_site_status(site_id)` | Latest telemetry snapshot: battery, solar, load, temps, inverter state |
| `get_fleet_overview()` | Current status across all active sites |
| `get_recent_anomalies(site_id?, limit?)` | AI-triaged fault history |
| `get_telemetry_trend(site_id, hours?)` | Statistical summary over configurable window |

**Example interaction:**

> *"Why is site-07 in alarm?"*
>
> **Agent:** Site-07 is showing battery stress — discharge current at 38A against 91% SOC during peak solar hours. The Isolation Forest model flagged this at score −0.61. Over the past hour, SOC has ranged 88–100% with solar averaging 2,940W and load at 1,391W. The power balance is positive (+1,549W surplus) so the anomaly is driven by unexpected current draw relative to the charge state. Recommend checking for a load spike or BMS miscalibration.

Security: all `site_id` inputs validated against `^[a-z0-9\-]{1,32}$` before BQ query construction.

---

## Operations Dashboard

Built with Streamlit + Plotly. Five pages, auto-refresh configurable 15–300 seconds.

| Page | Key Content |
|------|-------------|
| **Fleet Overview** | 5 KPI cards (active sites, fleet solar kW, fleet load kW, avg SOC, alarm count) · site-status table with inline SOC bars · Solar vs Load grouped bar chart |
| **Site Details** | SOC gauge · 6 live KPI cards · SOC trend area chart · Solar/Load overlay · Power Balance (surplus/deficit fill chart) · recent anomaly table |
| **Anomaly Monitor** | Severity KPI cards · timeline scatter by site · score histogram · anomaly count per site · filterable event table |
| **Operator Chat** | Natural-language interface to Agent 4 · session history · tool-call attribution footer |
| **Settings** | ML model metadata · infrastructure summary |

**ACK gate banner:** Appears on every page when unacknowledged critical or high alerts exist. Blinking red indicator, per-alert detail row, one-click ACK button.

**AI agent pulse indicator:** Sidebar shows live triage activity — site, timestamp, fault type, severity, and truncated AI summary when an agent fired in the last 5 minutes.

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Edge gateway | Python, Modbus TCP, SQLite, Paho MQTT |
| MQTT broker | Eclipse Mosquitto, TLS 1.2, per-device password auth |
| Message bus | Google Cloud Pub/Sub (3 topics, 5 subscriptions) |
| Time-series store | BigQuery (`microgrid_telemetry`, `anomaly_events`, `ack_events`) |
| Live cache | Redis (per-site state, TTL 120s) |
| ML model | scikit-learn Isolation Forest, joblib, GCS artefact store |
| Agent orchestration | LangGraph (StateGraph, ReAct loop) |
| LLM — triage | Anthropic Claude Haiku (claude-haiku-4-5-20251001) |
| LLM — chat | Anthropic Claude Sonnet (claude-sonnet-4-6) |
| Agent runtime | FastAPI + uvicorn, Docker, Cloud Run (australia-southeast1) |
| Secrets | GCP Secret Manager (API key, Slack webhook) |
| Dashboard | Streamlit, Plotly, custom HTML/CSS |
| Alerting | Slack Block Kit via incoming webhook |
| IAM | GCP service account, least-privilege role bindings |

---

## Key Design Decisions

**Why LangGraph?** Each agent is a stateful graph — not a monolithic function. This makes the processing pipeline auditable (you can inspect each node's input/output), testable in isolation, and extensible without refactoring the whole agent. The triage agent's three-node graph (`fetch_context → classify_fault → persist_results`) is a textbook example: each node has a single responsibility, and the graph enforces the execution order.

**Why streaming insert instead of DML UPDATE?** BigQuery's streaming buffer blocks DML on recently inserted rows. Rather than fight this constraint, we design with it: anomaly results are new rows, ACK events are new rows in a separate table, and queries use LEFT JOIN to derive acknowledged state. This pattern is immutable, append-only, and naturally produces an audit log.

**Why Haiku for triage, Sonnet for chat?** Structured JSON classification (8 fault types × 4 severities) is well within Haiku's capability at ~12× lower cost than Sonnet. The chat interface requires nuanced reasoning over live data, multi-step tool use, and operator-quality prose — that's Sonnet's domain.

**Why a 10-minute per-site cooldown?** Without it, a single anomalous site triggers continuous triage calls. With cooldown across 11 sites, worst-case API load is ≤1.1 calls/minute — from several hundred.

---

## Deployment Footprint

| Service | Instance | Memory | Requests/min (peak) |
|---------|----------|--------|---------------------|
| anomaly-detector | Cloud Run | 512 Mi | ~60 (1 per telemetry msg) |
| triage-agent | Cloud Run | 1 Gi | ≤1.1 (cooldown gated) |
| dispatch-agent | Cloud Run | 512 Mi | ≤1.1 (follows triage) |
| chat-agent | Cloud Run | 512 Mi | on-demand |
| MQTT broker + Redis | e2-small VM | 2 Gi | always-on |

All Cloud Run services: min-instances=0 (scale to zero when idle), max-instances=3, australia-southeast1 region.

---

## What This Demonstrates

This platform is a reference architecture for the emerging class of **agentic IIoT systems** — infrastructure where AI agents are first-class operational components, not add-ons.

The key insight is the separation of concerns across the agent layer:

- **Detection** (statistical, fast, cheap) — Isolation Forest runs on every message
- **Reasoning** (LLM, contextual) — Haiku runs only when an anomaly warrants investigation
- **Dispatch** (deterministic, reliable) — formatting and routing has no need for LLM
- **Interaction** (conversational, high-quality) — Sonnet handles operator dialogue

This hierarchy keeps costs bounded, latency low, and each agent focused. It also makes the system debuggable: if the wrong fault type is classified, you know exactly which node to inspect.

The human-in-the-loop ACK gate closes the loop: AI detects and reasons, human confirms and closes. Neither replaces the other. The audit trail in `ack_events` is permanent.

---

## Roadmap

- **Forecast Agent** — SOC trajectory prediction using time-series models + OpenWeatherMap solar irradiance; proactive low-battery warnings before the event
- **LangSmith Tracing** — full agent run audit trail for compliance and debugging
- **Custom Domain** — `tinylab.ai` via Cloud Run domain mapping
- **Multi-tenant** — per-organisation site isolation, role-based dashboard access

---

*Built with Claude Code · Powered by Anthropic Claude · Deployed on Google Cloud Platform*
*tinylab.ai — Amplified Engineering · ODSC East, April 2026*
