#!/usr/bin/env python3
"""mqtt_to_pubsub.py — MQTT to Pub/Sub bridge with Redis live-state cache.

Subscribes to microgrid/+/telemetry, publishes each message to the
microgrid-telemetry Pub/Sub topic (which has a native BQ-ingest subscription),
and caches the latest per-site reading in Redis with a 120-second TTL.
"""
import json
import logging
import os
import ssl
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import redis
from google.cloud import pubsub_v1

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mqtt-bridge")

PROJECT_ID   = os.getenv("PROJECT_ID",   "microgrid-demo")
BROKER_HOST  = os.getenv("BROKER_HOST",  "127.0.0.1")
BROKER_PORT  = int(os.getenv("BROKER_PORT", "8883"))
MQTT_USER    = os.getenv("MQTT_USER",    "mqtt-bridge")
MQTT_PASS    = os.getenv("MQTT_PASS",    "bridge-pass-secret")
CA_CERT      = os.getenv("CA_CERT",      "/etc/mosquitto/certs/ca.crt")
REDIS_HOST   = os.getenv("REDIS_HOST",   "127.0.0.1")
REDIS_PORT   = int(os.getenv("REDIS_PORT", "6379"))
REDIS_TTL    = int(os.getenv("REDIS_TTL",  "120"))

TOPIC_FILTER = "microgrid/+/telemetry"
PUBSUB_TOPIC = f"projects/{PROJECT_ID}/topics/microgrid-telemetry"

REQUIRED_FIELDS = {
    "site_id", "timestamp", "battery_v", "battery_soc", "battery_current",
    "battery_temp", "ac_input_v", "ac_output_v", "ac_output_i",
    "ac_input_power", "ac_output_power", "solar_w", "load_w",
    "inverter_state", "inverter_temp", "fault_code", "power_balance_w",
}

ps_client  = pubsub_v1.PublisherClient()
redis_conn = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.warning(f"Bad JSON on {msg.topic}: {e}")
        return

    missing = REQUIRED_FIELDS - payload.keys()
    if missing:
        log.warning(f"Schema mismatch on {msg.topic}: missing {missing}")
        return

    site_id = payload.get("site_id", "unknown")

    # Normalise timestamp to RFC3339 with UTC offset (BigQuery requires this)
    ts = payload.get("timestamp", datetime.now(timezone.utc).isoformat())
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    payload["timestamp"] = ts

    # Pub/Sub publish — bq-ingest-sub writes this to microgrid_telemetry
    data = json.dumps(payload).encode("utf-8")
    future = ps_client.publish(PUBSUB_TOPIC, data=data)
    future.result()

    # Redis per-site live state — read by the Operator Chat agent
    redis_conn.setex(f"site:{site_id}", REDIS_TTL, json.dumps(payload))

    log.info(f"Published {site_id}  soc={payload.get('battery_soc')}%  solar={payload.get('solar_w')}W")


def on_connect(client, userdata, flags, reason_code, properties):
    if not reason_code.is_failure:
        log.info(f"Connected to broker {BROKER_HOST}:{BROKER_PORT}")
        client.subscribe(TOPIC_FILTER, qos=1)
        log.info(f"Subscribed to {TOPIC_FILTER}")
    else:
        log.error(f"Connection refused: {reason_code}")


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    log.warning(f"Disconnected ({reason_code}), will reconnect...")


def run():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect    = on_connect
    client.on_message    = on_message
    client.on_disconnect = on_disconnect

    if BROKER_PORT == 8883:
        client.tls_set(ca_certs=CA_CERT, cert_reqs=ssl.CERT_REQUIRED)
        client.tls_insecure_set(True)

    while True:
        try:
            client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
            client.loop_forever()
        except Exception as e:
            log.error(f"Connection error: {e}, retrying in 10s...")
            time.sleep(10)


if __name__ == "__main__":
    run()
