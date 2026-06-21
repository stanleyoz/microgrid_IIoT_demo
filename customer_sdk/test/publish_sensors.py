#!/usr/bin/env python3
"""Test sensor simulator — publishes plain numeric payloads to the five local
gateway topics, mimicking a customer's edge sensors. For Phase 1 local testing."""
import argparse
import math
import random
import time

import paho.mqtt.client as mqtt

TOPICS = ["battery_soc", "battery_voltage", "solar_output", "load_demand",
          "inverter_temp"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--count", type=int, default=0, help="0 = run forever")
    args = ap.parse_args()

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="test-sensors")
    c.connect(args.host, args.port, 60)
    c.loop_start()

    i = 0
    while args.count == 0 or i < args.count:
        t = time.time()
        soc = 60 + 20 * math.sin(t / 30)
        values = {
            "battery_soc":   round(soc, 1),
            "battery_voltage": round(24.0 + soc / 100 * 3.5, 2),
            "solar_output":  round(max(0, 2000 * math.sin(t / 20)) + random.uniform(-50, 50), 1),
            "load_demand":   round(400 + random.uniform(0, 400), 1),
            "inverter_temp": round(30 + random.uniform(-2, 5), 1),
        }
        for topic, val in values.items():
            c.publish(topic, str(val), qos=1)
        print(f"sensors -> soc={values['battery_soc']} "
              f"solar={values['solar_output']} load={values['load_demand']}")
        i += 1
        time.sleep(args.interval)

    c.loop_stop()


if __name__ == "__main__":
    main()
