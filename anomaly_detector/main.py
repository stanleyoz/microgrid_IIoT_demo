import os
import json
import base64
import logging
import numpy as np
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from google.cloud import storage, bigquery, pubsub_v1
import joblib

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "microgrid-demo")
BUCKET_NAME = os.environ.get("MODEL_BUCKET", "microgrid-ml-artefacts")
MODEL_PREFIX = os.environ.get("MODEL_PREFIX", "models/2026-03-27")
DATASET_ID = "microgrid_db"
ANOMALY_TABLE = "anomaly_events"
ANOMALY_TOPIC = f"projects/{PROJECT_ID}/topics/microgrid-anomalies"

FEATURE_COLS = [
    "battery_v", "battery_soc", "battery_current", "battery_temp",
    "ac_input_v", "ac_output_v", "ac_input_power", "ac_output_power",
    "solar_w", "load_w", "inverter_temp", "power_balance_w",
    "battery_v_norm", "efficiency_ratio", "soc_rate_per_min",
    "mode_transitions_per_hour"
]

model = None
scaler = None
bq_client = None
ps_publisher = None


def load_artefacts():
    global model, scaler, bq_client, ps_publisher
    log.info(f"Loading model artefacts from gs://{BUCKET_NAME}/{MODEL_PREFIX}")
    gcs = storage.Client(project=PROJECT_ID)
    bucket = gcs.bucket(BUCKET_NAME)
    bucket.blob(f"{MODEL_PREFIX}/isolation_forest.joblib").download_to_filename("/tmp/isolation_forest.joblib")
    bucket.blob(f"{MODEL_PREFIX}/scaler.joblib").download_to_filename("/tmp/scaler.joblib")
    model = joblib.load("/tmp/isolation_forest.joblib")
    scaler = joblib.load("/tmp/scaler.joblib")
    bq_client = bigquery.Client(project=PROJECT_ID)
    ps_publisher = pubsub_v1.PublisherClient()
    log.info("Artefacts, BQ client, and Pub/Sub publisher loaded.")


load_artefacts()

app = FastAPI(title="Microgrid Anomaly Detector")


def classify_fault(p: dict) -> tuple[str, str]:
    """Basic rule-based fault classification (replaced by Agent 2 in Sprint 3)."""
    score = p.get("anomaly_score", 0)
    if p.get("battery_v", 0) > 28.0:
        fault = "overvoltage"
    elif p.get("battery_soc", 100) < 10.0:
        fault = "soc_drop"
    elif p.get("battery_temp", 0) > 50.0 or p.get("inverter_temp", 0) > 60.0:
        fault = "thermal"
    elif p.get("solar_w", 0) > 3000.0:
        fault = "power_balance"
    else:
        fault = "unknown"

    if score < -0.65:
        severity = "critical"
    elif score < -0.58:
        severity = "high"
    else:
        severity = "medium"

    return fault, severity


def write_anomaly_to_bq(site_id: str, timestamp: str, score: float, payload: dict):
    fault, severity = classify_fault({**payload, "anomaly_score": score})
    row = {
        "site_id": site_id,
        "timestamp": timestamp,
        "anomaly_score": score,
        "fault_type": fault,
        "severity": severity,
        "agent_summary": f"[Sprint-2 rule] {fault} detected on {site_id}. Score: {score:.4f}. Severity: {severity}.",
        "acknowledged": False
    }
    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{ANOMALY_TABLE}"
    errors = bq_client.insert_rows_json(table_ref, [row])
    if errors:
        log.error(f"BQ insert errors: {errors}")
    else:
        log.info(f"Anomaly written to BQ: {site_id} score={score:.4f} fault={fault}")
        # Publish full event to microgrid-anomalies for triage agent
        event = {**payload, "site_id": site_id, "timestamp": timestamp,
                 "anomaly_score": score, "fault_type": fault, "severity": severity}
        ps_publisher.publish(ANOMALY_TOPIC, json.dumps(event).encode("utf-8"))
        log.info(f"Published to {ANOMALY_TOPIC}")


def run_scoring(payload: dict) -> dict:
    battery_v_norm = payload["battery_v"] / 24.0
    denom = payload["ac_input_power"] + payload["solar_w"]
    efficiency_ratio = float(np.clip(payload["ac_output_power"] / denom, -5, 5)) if denom != 0 else 0.0
    soc_rate = 0.0
    mode_transitions = 0.0

    feature_vector = [[
        payload["battery_v"], payload["battery_soc"], payload["battery_current"], payload["battery_temp"],
        payload["ac_input_v"], payload["ac_output_v"], payload["ac_input_power"], payload["ac_output_power"],
        payload["solar_w"], payload["load_w"], payload["inverter_temp"], payload["power_balance_w"],
        battery_v_norm, efficiency_ratio, soc_rate, mode_transitions
    ]]
    X_scaled = scaler.transform(feature_vector)
    score_val = float(model.score_samples(X_scaled)[0])
    is_anomaly = bool(model.predict(X_scaled)[0] == -1)
    return {"score": score_val, "is_anomaly": is_anomaly}


class TelemetryPayload(BaseModel):
    site_id: str
    timestamp: str | None = None
    battery_v: float
    battery_soc: float
    battery_current: float
    battery_temp: float
    ac_input_v: float
    ac_output_v: float
    ac_output_i: float
    ac_input_power: float
    ac_output_power: float
    solar_w: float
    load_w: float
    inverter_state: int
    inverter_temp: float
    fault_code: int
    power_balance_w: float


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": model is not None}


@app.post("/score")
def score(payload: TelemetryPayload):
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    p = payload.model_dump()
    result = run_scoring(p)
    ts = payload.timestamp or datetime.now(timezone.utc).isoformat()
    if result["is_anomaly"]:
        write_anomaly_to_bq(payload.site_id, ts, result["score"], p)
    return {
        "site_id": payload.site_id,
        "timestamp": ts,
        "anomaly_score": round(result["score"], 6),
        "is_anomaly": result["is_anomaly"]
    }


@app.post("/pubsub")
async def pubsub_push(request: Request):
    """Handles Pub/Sub push envelope from anomaly-trigger-sub."""
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    body = await request.json()
    try:
        data_b64 = body["message"]["data"]
        payload = json.loads(base64.b64decode(data_b64).decode("utf-8"))
    except Exception as e:
        log.warning(f"Bad Pub/Sub message: {e}")
        return {"status": "ignored"}

    required = ["battery_v", "battery_soc", "battery_current", "battery_temp",
                "ac_input_v", "ac_output_v", "ac_input_power", "ac_output_power",
                "solar_w", "load_w", "inverter_temp", "power_balance_w"]
    if not all(k in payload for k in required):
        log.warning(f"Missing fields in payload from {payload.get('site_id','?')}, skipping.")
        return {"status": "ignored"}

    result = run_scoring(payload)
    ts = payload.get("timestamp") or datetime.now(timezone.utc).isoformat()
    site_id = payload.get("site_id", "unknown")

    if result["is_anomaly"]:
        write_anomaly_to_bq(site_id, ts, result["score"], payload)
        log.info(f"ANOMALY: {site_id} score={result['score']:.4f}")
    else:
        log.debug(f"Normal: {site_id} score={result['score']:.4f}")

    return {"status": "ok", "site_id": site_id, "is_anomaly": result["is_anomaly"]}
