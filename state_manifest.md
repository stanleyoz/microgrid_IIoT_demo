# Microgrid Project State Manifest

## [cite_start]Current Status: TRANSITION TO SPRINT 1 

| Component | POC Status | Sprint 1 Target | Current State |
| :--- | :--- | :--- | :--- |
| **GCP Project** | `microgrid-victron` | `microgrid-demo` | [cite_start]**DONE** [cite: 39] |
| **VM Size** | `e2-micro` | `e2-small` | [cite_start]**DONE** [cite: 60] |
| **MQTT Security** | Port 1883 / Anonymous | Port 8883 / TLS + Auth | [cite_start]**DONE** [cite: 68, 112] |
| **BigQuery Table** | `inverter_data` (KV) | `microgrid_telemetry` (Columnar) | [cite_start]**DONE** [cite: 73-78] |
| **Bridge Script** | `mqtt_to_pubsub.py` (POC) | `mqtt_to_pubsub.py` (Systemd/Redis) | [cite_start]**DONE**  |
| **Simulator** | `sim_pub_local.py` | Docker Compose (11 sites) | [cite_start]**NEW** [cite: 154-157] |

## Infrastructure Details
* [cite_start]**Service Account:** `microgrid-agent` [cite: 44]
* [cite_start]**Region/Zone:** `australia-southeast1-a` [cite: 59]
* [cite_start]**Topics:** `microgrid-telemetry`, `microgrid-anomalies`, `microgrid-agent-events` [cite: 83-85]
