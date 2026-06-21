#!/usr/bin/env python3
"""
Customer trial gateway forwarder.

Subscribes to five local sensor topics on the customer's own MQTT broker,
aggregates the latest values, and republishes them to the tinylab VM broker as
a single telemetry message using the *exact* schema produced by
edge/sim_site.py (17 fields). This guarantees compatibility with the existing
mqtt_to_pubsub bridge, BigQuery schema and dashboard — no server-side changes.

Local sensor topics (plain numeric string payloads, last-value-wins):
    battery_soc       -> battery_soc      (%)
    battery_voltage   -> battery_v        (V)
    solar_output      -> solar_w          (W)
    load_demand       -> load_w           (W)
    inverter_temp     -> inverter_temp    (degC)

Configuration is read from a gateway.conf (INI) file — see gateway.conf.tmpl.
The publisher self-terminates after trial_hours (<=12) as a courtesy; the VM
also revokes the credential at the same deadline (authoritative).
"""

import configparser
import json
import logging
import os
import shutil
import ssl
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

# ── Local sensor topic -> internal metric key ──────────────────────────────────
SENSOR_TOPICS = {
    "battery_soc":     "battery_soc",
    "battery_voltage": "battery_v",
    "solar_output":    "solar_w",
    "load_demand":     "load_w",
    "inverter_temp":   "inverter_temp",
}
# All five must be seen at least once before the first uplink publish (no all-null
# messages); thereafter last-value-wins.
REQUIRED_METRICS = set(SENSOR_TOPICS.values())

log = logging.getLogger("forwarder")


def load_config():
    """Load [gateway] config from the first path that exists."""
    candidates = [
        os.getenv("MICROGRID_GATEWAY_CONF"),
        "gateway.conf",
        "/etc/microgrid-gateway/gateway.conf",
    ]
    path = next((p for p in candidates if p and os.path.exists(p)), None)
    if not path:
        log.error("No gateway.conf found (set MICROGRID_GATEWAY_CONF or place "
                  "gateway.conf in the working dir).")
        sys.exit(2)
    cp = configparser.ConfigParser()
    cp.read(path)
    if not cp.has_section("gateway"):
        log.error("Config %s is missing a [gateway] section.", path)
        sys.exit(2)
    log.info("Loaded config from %s", path)
    return cp["gateway"]


class Forwarder:
    def __init__(self, cfg):
        self.site_id        = cfg.get("site_id")
        self.customer_name  = cfg.get("customer_name", self.site_id)
        self.local_host     = cfg.get("local_broker_host", "127.0.0.1")
        self.local_port     = cfg.getint("local_broker_port", 1883)
        self.vm_host        = cfg.get("vm_broker_host")
        self.vm_port        = cfg.getint("vm_broker_port", 8883)
        self.mqtt_user      = cfg.get("mqtt_user", fallback=None)
        self.mqtt_pass      = cfg.get("mqtt_pass", fallback=None)
        self.ca_cert        = cfg.get("ca_cert", "ca.crt")
        self.interval_s     = cfg.getfloat("publish_interval_s", 60.0)
        self.trial_hours    = min(cfg.getfloat("trial_hours", 12.0), 12.0)
        self.manage_service = cfg.getboolean("manage_service", False)
        self.service_name   = cfg.get("service_name", "microgrid-gateway")

        if not self.site_id or not self.vm_host:
            log.error("Config must define site_id and vm_broker_host.")
            sys.exit(2)

        self.uplink_topic = f"microgrid/{self.site_id}/telemetry"
        self.latest = {}                 # metric key -> float
        self.lock = threading.Lock()
        self.started_at = time.time()

        self.local = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                 client_id=f"{self.site_id}-local")
        self.uplink = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id=f"{self.site_id}-uplink")

    # ── local broker (sensor ingest) ──────────────────────────────────────────
    def _on_local_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            log.warning("Local broker connect failed: %s", reason_code)
            return
        for topic in SENSOR_TOPICS:
            client.subscribe(topic, qos=1)
        log.info("Subscribed to local sensor topics: %s",
                 ", ".join(SENSOR_TOPICS))

    def _on_local_message(self, client, userdata, msg):
        key = SENSOR_TOPICS.get(msg.topic)
        if not key:
            return
        raw = msg.payload.decode(errors="ignore").strip()
        try:
            value = float(raw)
        except ValueError:
            log.warning("Non-numeric payload on %s: %r", msg.topic, raw)
            return
        with self.lock:
            self.latest[key] = value

    # ── telemetry assembly (mirrors edge/sim_site.py schema) ──────────────────
    def build_payload(self):
        with self.lock:
            if not REQUIRED_METRICS.issubset(self.latest):
                return None
            m = dict(self.latest)

        solar_w = m["solar_w"]
        load_w = m["load_w"]
        battery_v = m["battery_v"]
        battery_soc = m["battery_soc"]
        power_balance_w = solar_w - load_w
        # Derived where physically possible; neutral defaults otherwise.
        battery_current = (-power_balance_w / battery_v) if battery_v else 0.0
        ac_output_v = 230.0
        ac_output_i = (load_w / ac_output_v) if ac_output_v else 0.0
        inverter_state = 10 if battery_soc < 10 else 9   # 10=low battery, 9=inverting

        return {
            "site_id":         self.site_id,
            "timestamp":       datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "battery_v":       round(battery_v, 2),
            "battery_soc":     round(battery_soc, 1),
            "battery_current": round(battery_current, 2),
            "battery_temp":    25.0,
            "ac_input_v":      230.0,
            "ac_output_v":     round(ac_output_v, 1),
            "ac_output_i":     round(ac_output_i, 2),
            "ac_input_power":  0.0,
            "ac_output_power": round(load_w, 1),
            "solar_w":         round(solar_w, 1),
            "load_w":          round(load_w, 1),
            "inverter_state":  inverter_state,
            "inverter_temp":   round(m["inverter_temp"], 1),
            "fault_code":      0,
            "power_balance_w": round(power_balance_w, 1),
        }

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def _expired(self):
        return (time.time() - self.started_at) >= self.trial_hours * 3600

    def _terminate(self):
        log.info("Trial window of %.2f h reached — terminating gateway.",
                 self.trial_hours)
        try:
            self.uplink.loop_stop(); self.local.loop_stop()
        except Exception:
            pass
        if self.manage_service and shutil.which("systemctl"):
            # Best-effort: disable so it does not restart after exit.
            subprocess.run(["systemctl", "disable", "--now", self.service_name],
                           check=False)
        sys.exit(0)

    def run(self):
        # Uplink (to VM broker) — TLS on 8883, matching sim_site.py.
        if self.mqtt_user:
            self.uplink.username_pw_set(self.mqtt_user, self.mqtt_pass)
        if self.vm_port == 8883:
            self.uplink.tls_set(ca_certs=self.ca_cert, cert_reqs=ssl.CERT_REQUIRED)
            self.uplink.tls_insecure_set(True)
        self.uplink.reconnect_delay_set(min_delay=1, max_delay=30)
        log.info("Uplink -> %s:%s topic=%s", self.vm_host, self.vm_port,
                 self.uplink_topic)
        self.uplink.connect_async(self.vm_host, self.vm_port, keepalive=60)
        self.uplink.loop_start()

        # Local (sensor ingest).
        self.local.on_connect = self._on_local_connect
        self.local.on_message = self._on_local_message
        self.local.reconnect_delay_set(min_delay=1, max_delay=15)
        self.local.connect_async(self.local_host, self.local_port, keepalive=60)
        self.local.loop_start()

        log.info("Gateway '%s' (%s) running — publishing every %.0fs, trial %.2fh.",
                 self.customer_name, self.site_id, self.interval_s, self.trial_hours)

        waiting_logged = False
        while True:
            if self._expired():
                self._terminate()
            payload = self.build_payload()
            if payload is None:
                if not waiting_logged:
                    have = sorted(self.latest)
                    log.info("Waiting for all sensors before first publish "
                             "(have: %s)", have or "none")
                    waiting_logged = True
            else:
                self.uplink.publish(self.uplink_topic, json.dumps(payload), qos=1)
                log.info("Published %s  soc=%.1f%%  solar=%.0fW  load=%.0fW",
                         self.site_id, payload["battery_soc"],
                         payload["solar_w"], payload["load_w"])
            time.sleep(self.interval_s)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    Forwarder(load_config()).run()


if __name__ == "__main__":
    main()
