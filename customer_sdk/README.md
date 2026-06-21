# Customer Trial SDK

Per-customer trial gateway: a customer installs this on their own Linux edge
device; it runs a local MQTT broker, accepts five sensor metrics, and forwards
them to the tinylab VM broker so the device appears as a private `customer_name`
Site on `microgrid.tinylab.ai/c/<guid>`.

Full spec: [`docs/customer_sdk_requirements.md`](../docs/customer_sdk_requirements.md).

## Status

- **Phase 1 — forwarder + local contract — DONE & tested** (this directory).
- **Phase 2 — installer (`install.sh`, port-bump, systemd) — DONE & tested**
  (verified end-to-end in a clean Ubuntu 24.04 container).
- Phase 3 — VM provisioning (mosquitto user + ACL + 12h revocation) — pending.
- Phase 4 — main-dashboard exclusion + scoped `/c/<guid>` dashboard — pending.
- Phase 5 — bundle generator + end-to-end dry run — pending.

## Layout

```
templates/
  forwarder.py        local-broker → VM forwarder (paho, TLS, 12h self-stop)
  install.sh          customer installer (multi-arch deps, port-bump, systemd)
  uninstall.sh        removes service, broker drop-in, install dir
  microgrid-gateway.service  systemd unit for the forwarder
  gateway.conf.tmpl   config template (generator fills {{PLACEHOLDERS}})
  requirements.txt    paho-mqtt>=2.0
test/
  publish_sensors.py  fake edge sensors (5 local topics)
  verify_uplink.py    validates uplink against the 17-field sim_site schema
```

## Local contract (customer → local broker)

Plain numeric string payloads, last-value-wins:

| Local topic | Schema field | Unit |
|---|---|---|
| `battery_soc` | `battery_soc` | % |
| `battery_voltage` | `battery_v` | V |
| `solar_output` | `solar_w` | W |
| `load_demand` | `load_w` | W |
| `inverter_temp` | `inverter_temp` | °C |

The forwarder builds the full 17-field `edge/sim_site.py` schema (deriving
`power_balance_w`, `battery_current`, `ac_output_i`; neutral defaults for the
rest) and publishes to `microgrid/<site_id>/telemetry`.

## Test it locally (no VM needed)

```bash
cd customer_sdk
python3 -m venv .venv && .venv/bin/pip install -r templates/requirements.txt

# 1. local broker on a free port (host 1883 may be busy — example uses 18830)
docker run -d --name mqtt-test -p 18830:1883 \
  -v "$PWD/test/mosquitto.test.conf:/mosquitto/config/mosquitto.conf:ro" \
  eclipse-mosquitto:latest

# 2. point test/gateway.test.conf at that port (local + vm_broker_port = 18830)

# 3. run forwarder + fake sensors, then verify
MICROGRID_GATEWAY_CONF=test/gateway.test.conf .venv/bin/python templates/forwarder.py &
.venv/bin/python test/publish_sensors.py --port 18830 --interval 0.5 &
.venv/bin/python test/verify_uplink.py --port 18830 --site-id cust-test-0001 --samples 3
# expect: "PASS — 3 messages match the sim_site schema."

docker rm -f mqtt-test
```

### Verified behaviours (Phase 1)
- 5 sensors → exact 17-field schema, correct derived values — **PASS**.
- Missing any sensor → withholds publishing (no all-null messages) — **PASS**.
- `trial_hours` deadline → clean self-termination (exit 0) — **PASS**.
