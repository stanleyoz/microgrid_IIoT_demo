#!/usr/bin/env python3
"""Uplink verifier — subscribes to the forwarder's telemetry topic and checks
that each message matches the exact 17-field sim_site.py schema with correct
types and sane derived values. Prints PASS/FAIL. For Phase 1 local testing."""
import argparse
import json
import sys

import paho.mqtt.client as mqtt

# Exact schema produced by edge/sim_site.py
EXPECTED_FIELDS = {
    "site_id": str, "timestamp": str, "battery_v": (int, float),
    "battery_soc": (int, float), "battery_current": (int, float),
    "battery_temp": (int, float), "ac_input_v": (int, float),
    "ac_output_v": (int, float), "ac_output_i": (int, float),
    "ac_input_power": (int, float), "ac_output_power": (int, float),
    "solar_w": (int, float), "load_w": (int, float),
    "inverter_state": int, "inverter_temp": (int, float),
    "fault_code": int, "power_balance_w": (int, float),
}


def check(payload):
    errors = []
    missing = set(EXPECTED_FIELDS) - set(payload)
    extra = set(payload) - set(EXPECTED_FIELDS)
    if missing:
        errors.append(f"missing fields: {sorted(missing)}")
    if extra:
        errors.append(f"unexpected fields: {sorted(extra)}")
    for field, types in EXPECTED_FIELDS.items():
        if field in payload and not isinstance(payload[field], types):
            errors.append(f"{field} wrong type: {type(payload[field]).__name__}")
    # Derived-value sanity
    if not errors:
        pb = round(payload["solar_w"] - payload["load_w"], 1)
        if abs(payload["power_balance_w"] - pb) > 0.2:
            errors.append(f"power_balance_w {payload['power_balance_w']} != "
                          f"solar-load {pb}")
        if not payload["site_id"].startswith("cust-"):
            errors.append(f"site_id not customer-scoped: {payload['site_id']}")
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--site-id", required=True)
    ap.add_argument("--samples", type=int, default=3,
                    help="messages to validate before declaring PASS")
    args = ap.parse_args()

    topic = f"microgrid/{args.site_id}/telemetry"
    state = {"ok": 0, "done": False}

    def on_connect(c, u, f, rc, p):
        c.subscribe(topic, qos=1)
        print(f"verifier subscribed to {topic}")

    def on_message(c, u, msg):
        if state["done"]:
            return
        try:
            payload = json.loads(msg.payload)
        except json.JSONDecodeError as e:
            print(f"FAIL: invalid JSON: {e}")
            state["done"] = True
            return
        errs = check(payload)
        if errs:
            print(f"FAIL on message: {errs}")
            print(json.dumps(payload, indent=2))
            state["done"] = True
            return
        state["ok"] += 1
        print(f"  ✓ valid message {state['ok']}/{args.samples}  "
              f"soc={payload['battery_soc']} pb={payload['power_balance_w']}")
        if state["ok"] >= args.samples:
            print(f"\nPASS — {args.samples} messages match the sim_site schema.")
            print("Sample payload:\n" + json.dumps(payload, indent=2))
            state["done"] = True

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="test-verifier")
    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(args.host, args.port, 60)
    c.loop_start()

    import time
    deadline = time.time() + 60
    while not state["done"] and time.time() < deadline:
        time.sleep(0.2)
    c.loop_stop()

    if state["ok"] >= args.samples:
        sys.exit(0)
    if not state["done"]:
        print(f"FAIL: timeout — only {state['ok']}/{args.samples} valid messages.")
    sys.exit(1)


if __name__ == "__main__":
    main()
