import os
import json
import base64
import logging
import requests
from datetime import datetime, timezone
from typing import TypedDict, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google.cloud import bigquery
from langgraph.graph import StateGraph, END

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

PROJECT_ID   = os.environ.get("PROJECT_ID", "microgrid-demo")
SLACK_URL    = os.environ.get("SLACK_WEBHOOK_URL", "")

SEVERITY_EMOJI = {
    "critical": "🔴",
    "high":     "🟠",
    "medium":   "🟡",
    "low":      "🟢",
}

SEVERITY_COLOR = {
    "critical": "#E74C3C",
    "high":     "#E67E22",
    "medium":   "#F1C40F",
    "low":      "#27AE60",
}

# Only dispatch these severities — suppress low to avoid noise
DISPATCH_SEVERITIES = {"critical", "high", "medium"}

DATASET = "microgrid_db"

bq = bigquery.Client(project=PROJECT_ID)

app = FastAPI(title="Microgrid Dispatch Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


# ── LangGraph state ───────────────────────────────────────────────────────────
class DispatchState(TypedDict):
    event:        dict
    severity:     str
    site_id:      str
    fault_type:   str
    slack_payload: dict
    slack_sent:   bool
    error:        Optional[str]


# ── Node 1: route — decide channels and build Slack payload ───────────────────
def route(state: DispatchState) -> DispatchState:
    e         = state["event"]
    severity  = (e.get("severity") or "medium").lower()
    site_id   = e.get("site_id", "unknown")
    fault     = e.get("fault_type", "unknown")
    score     = e.get("anomaly_score", 0)
    summary   = e.get("agent_summary", "No summary available.")
    action    = e.get("recommended_action", "Review telemetry.")
    ts        = e.get("timestamp", datetime.now(timezone.utc).isoformat())
    root      = e.get("root_cause", "")

    try:
        ts_fmt = datetime.fromisoformat(
            ts.replace("Z", "+00:00")
        ).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        ts_fmt = ts

    emoji = SEVERITY_EMOJI.get(severity, "⚪")
    color = SEVERITY_COLOR.get(severity, "#BDC3C7")

    header_text = f"{emoji} {severity.upper()}  ·  {fault.replace('_',' ').title()}  ·  {site_id}"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text, "emoji": True}
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Site:*\n`{site_id}`"},
                {"type": "mrkdwn", "text": f"*Fault Type:*\n`{fault}`"},
                {"type": "mrkdwn", "text": f"*Severity:*\n{emoji} `{severity}`"},
                {"type": "mrkdwn", "text": f"*Anomaly Score:*\n`{score:.4f}`"},
            ]
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*AI Analysis:*\n{summary}"}
        },
    ]

    if root:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Root Cause:*\n{root}"}
        })

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn",
                 "text": f":wrench: *Recommended Action:*\n{action}"}
    })

    if severity == "critical":
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (f":rotating_light: *CRITICAL ALERT — Operator acknowledgement required.*\n"
                         f"Log in to the dashboard and acknowledge this event to clear the alarm.")
            }
        })

    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": (f"⚡ Microgrid Ops  ·  tinylab.ai  ·  {ts_fmt}  ·  "
                         f"<https://anomaly-detector-633335742473.australia-southeast1.run.app/health|Service Status>")
            }
        ]
    })

    payload = {
        "attachments": [{
            "color":  color,
            "blocks": blocks
        }]
    }

    return {**state, "severity": severity, "site_id": site_id,
            "fault_type": fault, "slack_payload": payload}


# ── Node 2: send_slack ────────────────────────────────────────────────────────
def send_slack(state: DispatchState) -> DispatchState:
    if state["severity"] not in DISPATCH_SEVERITIES:
        log.info(f"Severity '{state['severity']}' below dispatch threshold — skipping.")
        return {**state, "slack_sent": False}

    if not SLACK_URL:
        log.warning("SLACK_WEBHOOK_URL not set — skipping Slack dispatch.")
        return {**state, "slack_sent": False, "error": "No webhook configured"}

    try:
        resp = requests.post(SLACK_URL, json=state["slack_payload"], timeout=10)
        if resp.status_code == 200:
            log.info(f"Slack alert sent: {state['site_id']} / {state['severity']}")
            return {**state, "slack_sent": True}
        else:
            log.error(f"Slack returned {resp.status_code}: {resp.text}")
            return {**state, "slack_sent": False, "error": resp.text}
    except Exception as e:
        log.error(f"Slack dispatch failed: {e}")
        return {**state, "slack_sent": False, "error": str(e)}


# ── Build LangGraph ───────────────────────────────────────────────────────────
def build_graph():
    g = StateGraph(DispatchState)
    g.add_node("route",      route)
    g.add_node("send_slack", send_slack)
    g.set_entry_point("route")
    g.add_edge("route",      "send_slack")
    g.add_edge("send_slack", END)
    return g.compile()

dispatch_graph = build_graph()


# ── FastAPI endpoints ─────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "agent": "dispatch",
            "slack_configured": bool(SLACK_URL)}


@app.post("/pubsub")
async def pubsub_push(request: Request):
    body = await request.json()
    try:
        data_b64 = body["message"]["data"]
        event    = json.loads(base64.b64decode(data_b64).decode("utf-8"))
    except Exception as e:
        log.warning(f"Bad Pub/Sub envelope: {e}")
        return {"status": "ignored"}

    if event.get("event_type") != "triage_complete":
        log.info(f"Ignoring event type: {event.get('event_type')}")
        return {"status": "ignored"}

    initial: DispatchState = {
        "event":         event,
        "severity":      "",
        "site_id":       "",
        "fault_type":    "",
        "slack_payload": {},
        "slack_sent":    False,
        "error":         None,
    }

    result = dispatch_graph.invoke(initial)
    return {
        "status":      "ok",
        "site_id":     result["site_id"],
        "severity":    result["severity"],
        "slack_sent":  result["slack_sent"],
    }


# ── ACK endpoint — human-in-the-loop gate ─────────────────────────────────────
class AckRequest(BaseModel):
    site_id:       str
    timestamp:     str   # ISO 8601 UTC
    fault_type:    str
    severity:      str
    agent_summary: str = ""


@app.post("/ack")
async def acknowledge(req: AckRequest):
    acked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Stream ACK into ack_events table (avoids streaming buffer DML restriction)
    ack_row = {
        "site_id":          req.site_id,
        "anomaly_timestamp": req.timestamp,
        "fault_type":        req.fault_type,
        "severity":          req.severity,
        "acked_at":          datetime.now(timezone.utc).isoformat(),
    }
    try:
        errors = bq.insert_rows_json(f"{PROJECT_ID}.{DATASET}.ack_events", [ack_row])
        if errors:
            log.error(f"BQ ACK insert errors: {errors}")
            return {"status": "bq_error", "detail": str(errors)}
        log.info(f"ACK recorded in BQ: {req.site_id} @ {req.timestamp}")
    except Exception as e:
        log.error(f"BQ ACK insert failed: {e}")
        return {"status": "bq_error", "detail": str(e)}

    # Send green Slack confirmation
    if SLACK_URL:
        fault_label = req.fault_type.replace("_", " ").title()
        sev_emoji   = SEVERITY_EMOJI.get(req.severity, "⚪")
        payload = {
            "attachments": [{
                "color": "#27AE60",
                "blocks": [
                    {
                        "type": "header",
                        "text": {"type": "plain_text",
                                 "text": f"✅  ACKNOWLEDGED  ·  {fault_label}  ·  {req.site_id}",
                                 "emoji": True}
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Site:*\n`{req.site_id}`"},
                            {"type": "mrkdwn", "text": f"*Fault:*\n`{req.fault_type}`"},
                            {"type": "mrkdwn", "text": f"*Severity:*\n{sev_emoji} `{req.severity}`"},
                            {"type": "mrkdwn", "text": f"*Acknowledged:*\n{acked_at}"},
                        ]
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn",
                                 "text": f"*Original AI Summary:*\n{req.agent_summary}"}
                    },
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn",
                                      "text": "⚡ Operator acknowledged via Microgrid Dashboard · tinylab.ai"}]
                    }
                ]
            }]
        }
        try:
            resp = requests.post(SLACK_URL, json=payload, timeout=10)
            log.info(f"ACK Slack sent: {resp.status_code}")
        except Exception as e:
            log.warning(f"ACK Slack failed: {e}")

    return {"status": "acknowledged", "site_id": req.site_id, "acked_at": acked_at}
