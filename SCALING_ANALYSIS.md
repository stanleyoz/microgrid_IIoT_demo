# Microgrid Platform — Scaling Cost & Load Analysis
### Assumptions: 10s telemetry cadence · 5% anomaly rate · 2h triage cooldown (non-demo)

---

## Cost Summary

| Metric | Current (12 sites) | 100 sites | 1,000 sites |
|---|---|---|---|
| Telemetry rate | 1.2 msg/s | 10 msg/s | 100 msg/s |
| Anomalies flagged | 216/hr | 1,800/hr | 18,000/hr |
| Triage API calls | 6/hr | 50/hr | 500/hr |
| **Total cost/month** | **~$30** | **~$119** | **~$1,074** |
| **Per site/month** | **$2.53** | **$1.19** | **$1.07** |

Cost per site actually **decreases** at scale — Pub/Sub and BigQuery are near-free at low volumes, fixed VM cost amortises across more sites.

### Cost Breakdown at 1,000 Sites

| Component | $/month | % of total |
|---|---|---|
| Haiku triage API | $504 | 47% |
| Cloud Run (anomaly-detector) | $496 | 46% |
| Broker VM (upgraded) | $55 | 5% |
| BigQuery | $10 | 1% |
| Pub/Sub | $5 | <1% |
| Other agents | $5 | <1% |

The two dominant costs are **LLM API calls** and **anomaly detector Cloud Run compute** — both linear with site count.

---

## Demo vs Non-Demo Cost Impact (5-min vs 2-hr cooldown)

| Cooldown | Triage calls/hr (1,000 sites) | Haiku API $/month |
|---|---|---|
| 2 hours (current) | 500 | $504 |
| 30 minutes | 2,000 | $2,016 |
| 15 minutes | 4,000 | $4,032 |
| 5 minutes (demo) | 12,000 | $12,096 |

**Never run 5-minute cooldown at 1,000 sites in production.**

---

## Architectural Bottlenecks by Scale

### 12 → 100 sites — Current architecture handles this fine

- Mosquitto e2-small handles 10 msg/s comfortably (rated to ~50k connections)
- Cloud Run auto-scales anomaly-detector without config changes
- BigQuery well within free query tier
- Redis single-instance adequate for live state cache
- **No changes required**

### 100 → 1,000 sites — Three things need attention

#### 1. MQTT Broker (critical)
Single Mosquitto on e2-small becomes unreliable at ~100 msg/s sustained with 1,000 concurrent connections.

Options (in order of preference):
- **Upgrade to e2-standard-4** (~$55/month) — handles ~500 msg/s, simpler
- **EMQX cluster** (2× e2-medium) — production-grade, HA, built-in monitoring
- **GCP Pub/Sub MQTT bridge directly** — eliminates broker VM entirely, most scalable, ~$5/month vs ~$55 VM

#### 2. BigQuery table partitioning (important)
At 1,000 sites the `microgrid_telemetry` table grows ~36 GB/month. Without partitioning, dashboard queries scan the entire table — costs explode and performance degrades.

Fix: recreate table with `PARTITION BY DATE(timestamp)` + `CLUSTER BY site_id`. One-time migration. Reduces query scan by 95%+ for time-bounded queries.

```sql
CREATE TABLE microgrid_db.microgrid_telemetry_v2
PARTITION BY DATE(timestamp)
CLUSTER BY site_id
AS SELECT * FROM microgrid_db.microgrid_telemetry;
```

#### 3. Anomaly detector: min-instances (important)
At 100 msg/s, cold starts on Cloud Run become a problem — requests queue while containers spin up. Set `--min-instances=2` on anomaly-detector to keep warm replicas ready.

Cost impact: 2 idle instances × 512Mi × $0.0000025/GiB-s = ~$6.50/month. Worth it.

### 1,000 → 10,000 sites — Architecture needs redesign

At this scale the current design hits fundamental limits:

| Component | Problem | Solution |
|---|---|---|
| MQTT broker | Single broker can't handle 1,000 msg/s | Managed MQTT (HiveMQ Cloud) or Pub/Sub direct |
| Anomaly detector | 1,000 msg/s = need ~6 vCPU continuously | Move to Vertex AI Endpoint (auto-scaling, GPU optional) |
| BigQuery ingest | Streaming insert costs ~$0.01/200MB = $1,296/month at 10k sites | Switch to BigQuery Storage Write API (10× cheaper) |
| Triage agent | 5,000 calls/hr exhausts single Cloud Run instance | Increase Cloud Run concurrency + max-instances |
| Redis cache | Single instance OOM risk at 10k live sites | Cloud Memorystore (managed Redis cluster) |

---

## Cost Optimisation Levers (in priority order)

### 1. Severity-gated triage (highest impact)
Currently triage fires on ALL anomalies. If you filter to only critical+high before triggering triage, the 5% anomaly rate at 1,000 sites drops to ~0.5–1% effectively triaged.

```python
# In anomaly_detector/main.py — only publish to microgrid-anomalies if score < -0.58
if score < HIGH_THRESHOLD:   # not just is_anomaly
    ps.publish(ANOMALY_TOPIC, ...)
```

**Impact at 1,000 sites:** Triage API cost drops from $504 → ~$100/month

### 2. Local LLM for triage (planned)
Swap Haiku for `qwen2.5:7b` on local RTX 4090 (or a GPU VM): $0 API cost, ~$0.50/hr GPU VM.
At 1,000 sites: saves ~$504/month vs ~$360/month GPU VM = still cheaper above ~700 sites.

### 3. Batch anomaly scoring
Instead of scoring every message individually, batch 10 readings per site and score together.
Reduces Cloud Run requests by 10× — saves ~$450/month at 1,000 sites with no accuracy loss.

### 4. BigQuery partitioning
As above — prevents query cost blowout as data grows.

### 5. Telemetry downsampling for stable sites
Sites in normal operation (no anomalies for >1hr) could report at 30s instead of 10s.
Reduces ingestion volume by 3× for healthy sites = meaningful Pub/Sub + BQ savings at scale.

---

## Recommended Scale Tiers

| Tier | Sites | Architecture | Est. Cost/month |
|---|---|---|---|
| PoC / Demo | 1–20 | Current | $30–50 |
| Pilot | 20–100 | Current + severity-gated triage | $80–120 |
| Small commercial | 100–500 | + BQ partitioning + broker upgrade | $200–450 |
| Mid-market | 500–2,000 | + local LLM or GPU VM + batch scoring | $400–900 |
| Enterprise | 2,000+ | Full redesign: managed MQTT, Vertex AI, BQ Storage Write | TBD |

---

*Analysis based on GCP australia-southeast1 pricing, Anthropic claude-haiku-4-5-20251001 pricing, March 2026.*
*Operator Chat (Claude Sonnet) costs excluded — on-demand, usage-dependent.*
