import os
import re
import json
import logging
from typing import TypedDict

import anthropic
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google.cloud import bigquery
from langgraph.graph import StateGraph, END

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "microgrid-demo")
DATASET    = "microgrid_db"
MODEL_ID   = "claude-sonnet-4-6"

bq     = bigquery.Client(project=PROJECT_ID)
claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

app = FastAPI(title="Microgrid Chat Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

SYSTEM_PROMPT = """You are the Operator Assistant for tinylab.ai's microgrid fleet — \
off-grid solar+battery sites using Victron MultiPlus 24V inverters.

Fleet: site-01 to site-11 (simulated) + hw-node-01 (physical hardware, Australia AEST UTC+10).

You have tools to query live telemetry and anomaly data. Always call at least one tool \
before answering questions about site status, anomalies, or fleet health.

Style: concise, technical, operator-focused. Use markdown. Lead with the key finding. \
Numbers: voltages 1dp V, power in W (kW if >1000), temps 1dp °C, SOC as %."""

TOOLS = [
    {
        "name": "get_site_status",
        "description": "Latest telemetry snapshot for one site (battery, solar, load, temps, state).",
        "input_schema": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "e.g. site-03 or hw-node-01"}
            },
            "required": ["site_id"]
        }
    },
    {
        "name": "get_fleet_overview",
        "description": "Current status for every active site — SOC, solar, load, inverter state.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_recent_anomalies",
        "description": "Recent anomaly events with AI triage results. Optionally filter by site.",
        "input_schema": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "Optional site filter"},
                "limit":   {"type": "integer", "description": "Max results (default 10)"}
            }
        }
    },
    {
        "name": "get_telemetry_trend",
        "description": "Statistical summary of telemetry over a time window for one site.",
        "input_schema": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string"},
                "hours":   {"type": "integer", "description": "Lookback window (default 1)"}
            },
            "required": ["site_id"]
        }
    }
]

_SITE_RE = re.compile(r'^[a-z0-9\-]{1,32}$')

def _safe_site(site_id: str) -> str:
    if not _SITE_RE.match(site_id):
        raise ValueError(f"Invalid site_id: {site_id!r}")
    return site_id

def _rows_to_json(rows) -> str:
    return json.dumps([{k: str(v) for k, v in dict(r).items()} for r in rows], indent=2)

def execute_tool(name: str, inputs: dict) -> str:
    try:
        if name == "get_site_status":
            sid = _safe_site(inputs["site_id"])
            q = f"""
            SELECT site_id, timestamp, battery_soc, battery_v, battery_current,
                   battery_temp, inverter_temp, solar_w, load_w, power_balance_w,
                   ac_input_v, ac_output_v, inverter_state, fault_code
            FROM `{PROJECT_ID}.{DATASET}.microgrid_telemetry`
            WHERE site_id = '{sid}'
            ORDER BY timestamp DESC LIMIT 1
            """
            rows = list(bq.query(q).result())
            if not rows:
                return f"No telemetry found for site {sid} in the last 15 minutes."
            return _rows_to_json(rows)

        elif name == "get_fleet_overview":
            q = f"""
            SELECT * EXCEPT(rn) FROM (
                SELECT site_id, timestamp, battery_soc, battery_v, solar_w, load_w,
                       power_balance_w, inverter_state, fault_code,
                       ROW_NUMBER() OVER (PARTITION BY site_id ORDER BY timestamp DESC) AS rn
                FROM `{PROJECT_ID}.{DATASET}.microgrid_telemetry`
                WHERE timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 15 MINUTE)
            ) WHERE rn = 1 ORDER BY site_id
            """
            rows = list(bq.query(q).result())
            if not rows:
                return "No sites reporting in the last 15 minutes."
            return _rows_to_json(rows)

        elif name == "get_recent_anomalies":
            site_filter = ""
            if inputs.get("site_id"):
                sid = _safe_site(inputs["site_id"])
                site_filter = f"AND site_id = '{sid}'"
            limit = min(int(inputs.get("limit", 10)), 50)
            q = f"""
            SELECT site_id, timestamp, fault_type, severity, anomaly_score, agent_summary
            FROM `{PROJECT_ID}.{DATASET}.anomaly_events`
            WHERE 1=1 {site_filter}
            ORDER BY timestamp DESC LIMIT {limit}
            """
            rows = list(bq.query(q).result())
            if not rows:
                return "No anomaly events found."
            return _rows_to_json(rows)

        elif name == "get_telemetry_trend":
            sid = _safe_site(inputs["site_id"])
            hours = min(int(inputs.get("hours", 1)), 48)
            q = f"""
            SELECT
                COUNT(*) as readings,
                ROUND(MIN(battery_soc),1) as soc_min, ROUND(MAX(battery_soc),1) as soc_max,
                ROUND(AVG(battery_soc),1) as soc_avg,
                ROUND(MIN(battery_v),1) as v_min, ROUND(MAX(battery_v),1) as v_max,
                ROUND(AVG(solar_w),0) as solar_avg, ROUND(MAX(solar_w),0) as solar_peak,
                ROUND(AVG(load_w),0) as load_avg,   ROUND(MAX(load_w),0) as load_peak,
                ROUND(AVG(battery_temp),1) as batt_temp_avg,
                ROUND(AVG(inverter_temp),1) as inv_temp_avg,
                ROUND(MIN(power_balance_w),0) as balance_min,
                ROUND(MAX(power_balance_w),0) as balance_max
            FROM `{PROJECT_ID}.{DATASET}.microgrid_telemetry`
            WHERE site_id = '{sid}'
              AND timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
            """
            rows = list(bq.query(q).result())
            if not rows or rows[0]["readings"] == 0:
                return f"No trend data for {sid} in the last {hours}h."
            return json.dumps({k: str(v) for k, v in dict(rows[0]).items()}, indent=2)

        return f"Unknown tool: {name}"
    except Exception as e:
        log.error(f"Tool {name} failed: {e}")
        return f"Tool error: {e}"


# ── LangGraph state + nodes ────────────────────────────────────────────────────
class AgentState(TypedDict):
    messages:   list
    tools_used: list
    response:   str
    done:       bool


def agent_node(state: AgentState) -> AgentState:
    resp = claude.messages.create(
        model=MODEL_ID,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
        messages=state["messages"]
    )
    if resp.stop_reason == "tool_use":
        new_msgs = state["messages"] + [{"role": "assistant", "content": resp.content}]
        return {**state, "messages": new_msgs, "done": False}
    text = next((b.text for b in resp.content if hasattr(b, "text")), "")
    return {**state, "response": text, "done": True}


def tools_node(state: AgentState) -> AgentState:
    last = state["messages"][-1]
    results = []
    new_tools = list(state["tools_used"])
    for block in last["content"]:
        if hasattr(block, "type") and block.type == "tool_use":
            new_tools.append(block.name)
            log.info(f"Executing tool: {block.name} inputs={block.input}")
            result = execute_tool(block.name, block.input)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result
            })
    new_msgs = state["messages"] + [{"role": "user", "content": results}]
    return {**state, "messages": new_msgs, "tools_used": new_tools}


def router(state: AgentState) -> str:
    return "end" if state["done"] else "tools"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", router, {"tools": "tools", "end": END})
    g.add_edge("tools", "agent")
    return g.compile()

chat_graph = build_graph()


# ── FastAPI ───────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    messages: list
    session_id: str = ""


@app.get("/health")
def health():
    return {"status": "ok", "agent": "chat", "model": MODEL_ID}


@app.post("/chat")
async def chat(req: ChatRequest):
    if not req.messages:
        return {"response": "No messages provided.", "tools_used": []}
    initial: AgentState = {
        "messages":   req.messages,
        "tools_used": [],
        "response":   "",
        "done":       False,
    }
    result = chat_graph.invoke(initial, {"recursion_limit": 12})
    log.info(f"Chat complete. Tools used: {result['tools_used']}")
    return {
        "response":   result["response"],
        "tools_used": result["tools_used"],
    }
