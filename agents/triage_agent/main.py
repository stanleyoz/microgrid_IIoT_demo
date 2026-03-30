import os
import json
import base64
import logging
from datetime import datetime, timezone
from typing import TypedDict, Optional

import anthropic
from fastapi import FastAPI, Request
from google.cloud import bigquery, pubsub_v1
from langgraph.graph import StateGraph, END

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

PROJECT_ID   = os.environ.get("PROJECT_ID", "microgrid-demo")
DATASET      = "microgrid_db"
AGENT_TOPIC  = f"projects/{PROJECT_ID}/topics/microgrid-agent-events"
MODEL_ID     = "claude-haiku-4-5-20251001"

bq      = bigquery.Client(project=PROJECT_ID)
ps      = pubsub_v1.PublisherClient()
claude  = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# In-process cooldown: suppress re-triage of the same site within 15 minutes
# Set lower (e.g. 5) for demo, higher for cost-controlled idle running
from datetime import timedelta
_last_triaged: dict[str, datetime] = {}
COOLDOWN = timedelta(minutes=120) #two hours cool-down for non-demo mode

app = FastAPI(title="Microgrid Triage Agent")

SYSTEM_PROMPT = """You are an expert industrial microgrid fault analyst specialising in
off-grid solar inverter systems (Victron MultiPlus, 24V battery banks).

An Isolation Forest ML model has flagged an anomaly. Your job is to:
1. Classify the fault type based on telemetry patterns
2. Assess severity for the field operator
3. Write a concise, actionable operator-facing summary

Fault types (pick the best fit):
  overvoltage     - battery_v above safe charging limit (>28V)
  undervoltage    - battery_v critically low (<23V)
  soc_drop        - rapid or unexpected SOC decline
  grid_outage     - AC input lost, system running on battery/solar only
  thermal         - elevated battery or inverter temperature
  power_balance   - solar generation or load outside expected range
  battery_stress  - high charge/discharge current relative to SOC
  unknown         - anomaly detected but pattern unclear

Severity:
  critical - immediate operator action required (safety risk or imminent shutdown)
  high     - action within 1 hour
  medium   - monitor closely, action within 24h
  low      - informational, log and review

Respond ONLY with valid JSON — no markdown, no explanation:
{
  "fault_type": "<one of the types above>",
  "severity": "<critical|high|medium|low>",
  "root_cause": "<1 sentence technical root cause>",
  "agent_summary": "<2-3 sentence operator-facing summary with key values>",
  "recommended_action": "<concise action for field operator>"
}"""


# ── LangGraph state ───────────────────────────────────────────────────────────
class TriageState(TypedDict):
    site_id: str
    timestamp: str
    anomaly_score: float
    telemetry: dict
    context: str
    fault_type: str
    severity: str
    root_cause: str
    agent_summary: str
    recommended_action: str
    error: Optional[str]


# ── Node 1: fetch 30-min context from BigQuery ────────────────────────────────
def fetch_context(state: TriageState) -> TriageState:
    site_id = state["site_id"]
    try:
        q = f"""
        SELECT
            MIN(battery_soc) as soc_min, MAX(battery_soc) as soc_max,
            ROUND(AVG(battery_soc), 1) as soc_avg,
            MIN(battery_v) as v_min, MAX(battery_v) as v_max,
            ROUND(AVG(solar_w), 0) as solar_avg, MAX(solar_w) as solar_max,
            ROUND(AVG(load_w), 0) as load_avg, MAX(load_w) as load_max,
            ROUND(AVG(battery_temp), 1) as batt_temp_avg,
            ROUND(AVG(inverter_temp), 1) as inv_temp_avg,
            MIN(power_balance_w) as balance_min, MAX(power_balance_w) as balance_max,
            COUNT(*) as readings
        FROM `{PROJECT_ID}.{DATASET}.microgrid_telemetry`
        WHERE site_id = '{site_id}'
          AND timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
        """
        row = list(bq.query(q).result())[0]
        context = (
            f"30-min window ({row.readings} readings): "
            f"SOC {row.soc_min}–{row.soc_max}% (avg {row.soc_avg}%), "
            f"Battery V {row.v_min}–{row.v_max}V, "
            f"Solar avg {row.solar_avg}W (max {row.solar_max}W), "
            f"Load avg {row.load_avg}W (max {row.load_max}W), "
            f"Power balance {row.balance_min}–{row.balance_max}W, "
            f"Battery temp avg {row.batt_temp_avg}°C, "
            f"Inverter temp avg {row.inv_temp_avg}°C"
        )
        log.info(f"Context fetched for {site_id}: {context}")
    except Exception as e:
        context = "Context unavailable — BQ query failed."
        log.warning(f"fetch_context failed for {site_id}: {e}")
    return {**state, "context": context}


# ── Node 2: Claude Sonnet classification ─────────────────────────────────────
def classify_fault(state: TriageState) -> TriageState:
    t = state["telemetry"]
    ts = state["timestamp"]
    try:
        hour = datetime.fromisoformat(ts.replace("Z", "+00:00")).hour
    except Exception:
        hour = 12
    time_ctx = "daytime (solar generating)" if 6 <= hour < 18 else "night-time (battery/grid only)"

    user_msg = f"""Anomaly detected on site {state['site_id']} at {ts} ({time_ctx}).

ML anomaly score: {state['anomaly_score']:.4f} (threshold ~-0.52; more negative = more anomalous)

Current telemetry snapshot:
  battery_soc={t.get('battery_soc')}%  battery_v={t.get('battery_v')}V  battery_current={t.get('battery_current')}A
  battery_temp={t.get('battery_temp')}°C  inverter_temp={t.get('inverter_temp')}°C
  solar_w={t.get('solar_w')}W  load_w={t.get('load_w')}W  power_balance_w={t.get('power_balance_w')}W
  ac_input_v={t.get('ac_input_v')}V  ac_output_v={t.get('ac_output_v')}V
  inverter_state={t.get('inverter_state')}  fault_code={t.get('fault_code')}

Recent site history: {state['context']}

Classify this anomaly."""

    try:
        response = claude.messages.create(
            model=MODEL_ID,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}]
        )
        raw = response.content[0].text.strip()
        log.info(f"Claude raw response: {raw[:300]}")
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        log.info(f"Claude classified {state['site_id']}: {result['fault_type']} / {result['severity']}")
        return {
            **state,
            "fault_type":         result.get("fault_type", "unknown"),
            "severity":           result.get("severity", "medium"),
            "root_cause":         result.get("root_cause", ""),
            "agent_summary":      result.get("agent_summary", ""),
            "recommended_action": result.get("recommended_action", ""),
        }
    except Exception as e:
        log.error(f"classify_fault failed: {e}")
        return {**state, "fault_type": "unknown", "severity": "medium",
                "root_cause": "", "agent_summary": f"[Triage error] {e}",
                "recommended_action": "Manual inspection required.", "error": str(e)}


# ── Node 3: persist to BQ + publish agent event ───────────────────────────────
def persist_results(state: TriageState) -> TriageState:
    site_id   = state["site_id"]
    timestamp = state["timestamp"]
    summary   = f"[AI Triage] {state['agent_summary']} Action: {state['recommended_action']}"

    # INSERT enriched row — streaming buffer blocks UPDATE so we insert a superseding row.
    # Dashboard queries order by timestamp DESC so the AI triage row surfaces first.
    try:
        row = {
            "site_id":       site_id,
            "timestamp":     timestamp,
            "anomaly_score": state["anomaly_score"],
            "fault_type":    state["fault_type"],
            "severity":      state["severity"],
            "agent_summary": summary,
            "acknowledged":  False,
        }
        errors = bq.insert_rows_json(f"{PROJECT_ID}.{DATASET}.anomaly_events", [row])
        if errors:
            log.error(f"BQ insert errors: {errors}")
        else:
            log.info(f"BQ anomaly_events row inserted for {site_id}")
    except Exception as e:
        log.error(f"BQ insert failed: {e}")

    # Publish to microgrid-agent-events
    try:
        event = {
            "event_type":         "triage_complete",
            "site_id":            site_id,
            "timestamp":          timestamp,
            "fault_type":         state["fault_type"],
            "severity":           state["severity"],
            "root_cause":         state["root_cause"],
            "agent_summary":      state["agent_summary"],
            "recommended_action": state["recommended_action"],
            "anomaly_score":      state["anomaly_score"],
            "processed_at":       datetime.now(timezone.utc).isoformat(),
        }
        ps.publish(AGENT_TOPIC, json.dumps(event).encode("utf-8"))
        log.info(f"Published triage_complete event for {site_id} to {AGENT_TOPIC}")
    except Exception as e:
        log.error(f"Pub/Sub publish failed: {e}")

    return state


# ── Build LangGraph ───────────────────────────────────────────────────────────
def build_graph():
    g = StateGraph(TriageState)
    g.add_node("fetch_context",  fetch_context)
    g.add_node("classify_fault", classify_fault)
    g.add_node("persist_results", persist_results)
    g.set_entry_point("fetch_context")
    g.add_edge("fetch_context",  "classify_fault")
    g.add_edge("classify_fault", "persist_results")
    g.add_edge("persist_results", END)
    return g.compile()

triage_graph = build_graph()


# ── FastAPI endpoints ─────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "agent": "triage", "model": MODEL_ID}


@app.post("/pubsub")
async def pubsub_push(request: Request):
    body = await request.json()
    try:
        data_b64 = body["message"]["data"]
        payload  = json.loads(base64.b64decode(data_b64).decode("utf-8"))
    except Exception as e:
        log.warning(f"Bad Pub/Sub envelope: {e}")
        return {"status": "ignored"}

    site_id = payload.get("site_id", "unknown")
    ts      = payload.get("timestamp") or datetime.now(timezone.utc).isoformat()
    score   = float(payload.get("anomaly_score", 0))

    now = datetime.now(timezone.utc)
    last = _last_triaged.get(site_id)
    if last and (now - last) < COOLDOWN:
        log.info(f"Cooldown active for {site_id} — skipping (last triaged {(now-last).seconds}s ago)")
        return {"status": "cooldown", "site_id": site_id}
    _last_triaged[site_id] = now

    log.info(f"Triage triggered: {site_id} score={score:.4f}")

    initial_state: TriageState = {
        "site_id":            site_id,
        "timestamp":          ts,
        "anomaly_score":      score,
        "telemetry":          payload,
        "context":            "",
        "fault_type":         "",
        "severity":           "",
        "root_cause":         "",
        "agent_summary":      "",
        "recommended_action": "",
        "error":              None,
    }

    result = triage_graph.invoke(initial_state)
    return {
        "status":     "ok",
        "site_id":    site_id,
        "fault_type": result["fault_type"],
        "severity":   result["severity"],
    }
