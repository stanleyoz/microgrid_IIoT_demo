# Customer Trial SDK — Requirements Specification

**Status:** Approved for design (2026-06-21) · **Owner:** tinylab.ai · **Type:** v1 demo / sales trial feature

## 1. Purpose

Provide a manually-issued, per-customer **trial gateway SDK**. After a sales conversation, tinylab generates a unique SDK bundle (stamped with a **GUID**) for a prospect. The customer installs it on their own Linux edge device; it stands up a **local MQTT broker**, accepts their five metric streams, and securely forwards them to the tinylab VM broker. The device then appears on a **private, per-customer dashboard** as a `customer_name` Site, for a **maximum of 12 hours**, after which the VM stops processing that publisher.

Goals: let a prospect see *their own* live data in our platform with minimal effort, while preserving privacy (each customer sees only their own site) and keeping the main demo dashboard tidy.

## 2. Architecture

```
[Customer edge device — Linux, any arch]                 [tinylab GCP VM: microgrid-broker]
 customer sensors                                          mosquitto :8883 (TLS, per-user pw + ACL)
   publish to local broker topics:                                 │
     battery_soc / battery_voltage /          ──TLS:8883──►  mqtt_to_pubsub (unchanged)
     solar_output / load_demand / inverter_temp                    │ → Pub/Sub → BigQuery
        │                                                          │ → Redis site:<id> TTL
        ▼                                                          ▼
   local mosquitto (installed by SDK)                       Private dashboard (scoped Streamlit
        │                                                    :8502, SITE_FILTER=<site_id>)
        ▼                                                    served at /c/<guid>/ via nginx
   forwarder.py (subscribe 5 topics → build full 17-field
   sim_site schema → publish microgrid/<site_id>/telemetry)
```

## 3. The GUID — dual role

A single per-customer GUID (UUIDv4) provides:

1. **Secure publisher identity.** MQTT username `cust-<guid>` + a generated secret password. A mosquitto **ACL locks this user to publishing only `microgrid/cust-<guid>/telemetry`** — they cannot read or write any other site's data.
2. **Private-dashboard capability key.** The customer's dashboard is served at the unguessable URL `https://microgrid.tinylab.ai/c/<guid>/`, filtered to show only their site, labelled with the friendly `customer_name`.

**`site_id` = `cust-<guid>`** (the GUID is the canonical site id under the hood; the friendly `customer_name` is display-only).

### Security model & caveat
Privacy is **capability-URL based** (the GUID is an unguessable secret in the path) plus per-user MQTT credentials + topic ACL over TLS. This is adequate for time-boxed sales trials. It is **not** a hardened auth system — there is no per-user login on the dashboard; anyone with the GUID URL can view that one site. Acceptable for v1; revisit if trials become long-lived or carry sensitive data.

## 4. Site isolation (privacy)

- **Main demo dashboard** (`microgrid.tinylab.ai`): queries filtered to **exclude** customer sites — show only `site-01..11` (`WHERE site_id NOT LIKE 'cust-%'`). Customer trials never appear here.
- **Each customer dashboard**: scoped to exactly one site (`WHERE site_id = 'cust-<guid>'`). No customer can see another customer's or the demo fleet's data.
- **MQTT ACL**: each `cust-<guid>` user may publish only its own telemetry topic.

## 5. Components

### (A) Bundle generator — tinylab side, manual
Input: a small JSON config (§6). Actions:
1. Generate GUID → derive `site_id = cust-<guid>` and MQTT secret.
2. **Provision on VM** (§8): add mosquitto user + ACL rule, schedule 12h credential revocation, reload broker.
3. **Launch/point** the scoped private dashboard instance for this GUID (§9).
4. Emit the **customer bundle**: `install.sh`, `forwarder.py`, `ca.crt`, and a generated `gateway.conf`.

### (B) Customer installer — `install.sh` (runs on edge device)
- Detect distro/arch; install mosquitto + Python3/venv via the system package manager.
- **Port check:** if preferred local broker port `1883` is in use (`ss -ltn`), select the next free port, **print the chosen port to the user**, and write it into the local broker config + `gateway.conf`.
- Install `forwarder.py` into a venv and register it as a **systemd service** (`Restart=always`).
- Print final status, the local broker endpoint the customer should publish to, and the trial expiry time.

### (C) Forwarder — `forwarder.py` (the running app)
- Subscribe to the five **local** topics (§7); keep the latest value of each.
- Every `publish_interval_s`, construct the **full 17-field sim_site schema** payload:
  - Mapped from sensors: `battery_soc`, `battery_v` (←battery_voltage), `solar_w` (←solar_output), `load_w` (←load_demand), `inverter_temp`.
  - Derived: `power_balance_w = solar_w − load_w`; `timestamp` (UTC ISO+Z); `site_id = cust-<guid>`.
  - Padded (neutral defaults, as `sim_site.py` shapes them): `battery_current`, `battery_temp`, `ac_input_v`, `ac_output_v`, `ac_output_i`, `ac_input_power`, `ac_output_power`, `inverter_state`, `fault_code`.
- Publish to `microgrid/cust-<guid>/telemetry` over **TLS:8883** with the issued credential (bundled `ca.crt`).
- Withhold publishing until the core metrics have been received at least once (no all-null messages).
- **Client-side 12h self-stop:** exit and disable own service at T+12h.

### (D) VM-side provisioning & enforcement
See §8.

## 6. Config file (input to generator)

```json
{
  "customer_name": "Acme Solar",
  "device_name": "pi-gateway-01",
  "local_broker_port": 1883,
  "publish_interval_s": 60,
  "vm_broker_host": "34.87.254.184",
  "vm_broker_port": 8883,
  "trial_hours": 12
}
```
- `trial_hours` is capped at 12. `customer_name` is display-only.

## 7. Local data ingestion contract (customer → local broker)

| Local topic | Maps to schema field | Unit |
|---|---|---|
| `battery_soc` | `battery_soc` | % (0–100) |
| `battery_voltage` | `battery_v` | volts |
| `solar_output` | `solar_w` | watts |
| `load_demand` | `load_w` | watts |
| `inverter_temp` | `inverter_temp` | °C |

- **Payload:** plain numeric string per message (e.g. publish `"84.2"` to `battery_soc`), last-value-wins.
- The full telemetry **schema is reused verbatim from `edge/sim_site.py`** (17 fields) to guarantee pipeline compatibility — no bridge or BigQuery changes.

## 8. VM provisioning & 12-hour lifecycle

### Credential + ACL
- mosquitto currently has **no ACL file** — provisioning introduces `/etc/mosquitto/aclfile` (referenced via `acl_file` in conf.d) with:
  ```
  user mqtt-bridge
  topic read microgrid/#

  pattern write microgrid/%u/#
  ```
  The `%u` pattern locks every device (demo + customer) to publishing only within its **own** site subtree `microgrid/<username>/#`.
- **Verified (2026-06-21):** existing publishers are `site-01..11` (→ `microgrid/site-NN/telemetry`), `hw-node-01` (→ `microgrid/hw-node-01/telemetry` **and** `microgrid/hw-node-01/gps`), and `mqtt-bridge` (subscribes only). The rule is `%u/#` (not `%u/telemetry`) specifically so the hardware node's secondary `/gps` topic keeps working. Tested in an isolated broker: all existing publishers preserved (incl. hw GPS), and a `cust-*` user is denied both publishing to and subscribing from any other site.
- Add the customer user: `mosquitto_passwd -b /etc/mosquitto/passwd cust-<guid> <secret>`, then reload mosquitto.

### 12h enforcement (two simple layers)
- **Authoritative (VM):** at provisioning, schedule a job (systemd-timer or `at`) at **T+12h** that runs `mosquitto_passwd -D cust-<guid>` (delete user) + reloads mosquitto, and stops/removes the scoped dashboard instance. After this, the publisher can no longer authenticate and no data is processed.
- **Courtesy (client):** `forwarder.py` self-terminates at T+12h.
- **Clock start:** provisioning time (simplest; matches sequential manual onboarding).
- **Expiry UX:** none required — the site drops off the dashboard's 15-min window naturally.

## 9. Private dashboard (scoped Streamlit)

- Reuse `dashboard/dashboard_app.py` in a **scoped mode** driven by env vars:
  - `SITE_FILTER=cust-<guid>` — every query restricted to this site; site selector hidden; fleet-wide pages reduced to the single site.
  - `CUSTOMER_NAME="Acme Solar"` — friendly title.
- Run a second Streamlit instance on `127.0.0.1:8502` with `--server.baseUrlPath=/c/<guid>`.
- Add an nginx `location /c/<guid>/` block (+ matching `/_stcore/stream` subpath) proxying to `:8502`.
- **Sequential onboarding** ⇒ a single scoped instance/port (`8502`) is reconfigured per trial; teardown removes the nginx block and stops the instance.

### Main dashboard change
- `fleet_latest()` and other fleet queries: add `WHERE site_id NOT LIKE 'cust-%'` so customer sites are excluded from the public demo dashboard.

## 10. Non-functional requirements

- **Portability:** target generic Linux on ARM32/ARM64/x86-64/RISC-V → **Python + paho + systemd, no Docker** (Docker images unreliable on RISC-V). Pure-Python forwarder, system-package mosquitto.
- **Security:** TLS to VM (bundled `ca.crt`); least-privilege per-customer credential + topic ACL; secrets only in the generated bundle, never committed; GUID URL over HTTPS.
- **Reliability:** forwarder auto-reconnects to local broker and VM; `Restart=always`.
- **Observability:** forwarder logs connect/publish events (mirrors `sim_site.py`).
- **Uninstall:** `uninstall.sh` stops/removes the forwarder + local broker config on the device; VM teardown (credential + dashboard) handled by the 12h job or manually.

## 11. Anomaly detection

**Disabled for customer sites in v1.** The Isolation Forest uses 16 features (incl. engineered ones needing AC fields); customer data supplies only 5, so scoring would be meaningless and risk showing false faults to a prospect. Customer trials are **telemetry + live dashboard only**. Re-enable later if richer customer telemetry warrants it.

## 12. Verified current VM state (2026-06-21)

- Single VM `microgrid-broker` (australia-southeast1-a), mosquitto TLS:8883, `allow_anonymous false`, `password_file /etc/mosquitto/passwd`, **no ACL file configured**.
- Bridge `mqtt_to_pubsub.py` (`/opt/microgrid`, systemd `mqtt-bridge`): subscribes `microgrid/+/telemetry`, validates full schema, extracts `site_id` from payload, no allowlist → customer sites ingest with no code change.
- Dashboard: Streamlit `127.0.0.1:8501` from `/opt/microgrid` (venv `.venv`), nginx `microgrid.tinylab.ai` proxies `/` + `/_stcore/stream` to 8501.

## 13. Out of scope (v1)

- Automated/self-service onboarding (intentionally manual).
- More than one concurrent trial (sequential only).
- Hardened dashboard authentication (capability-URL only).
- Store-and-forward / offline buffering on the edge device.
- Anomaly detection / AI triage for customer sites.
