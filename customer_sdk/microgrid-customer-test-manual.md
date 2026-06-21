# Microgrid Customer Trial — Test Manual

**Platform:** Microgrid IIoT + Agentic AI · **Operator:** tinylab.ai (Amplified Engineering)
**Live dashboard:** `https://microgrid.tinylab.ai`

This manual has two parts:

1. **Vendor side** — how tinylab builds and issues a customer SDK package.
2. **Customer side** — how the customer installs the SDK and feeds data, either
   with the bundled test feeder or from their own sensor gateway.

---

# Part 1 — Vendor Side: Building & Issuing the SDK Package

*(tinylab operator activities — performed once per customer / per device)*

## 1.1 Prerequisites (operator workstation)
- Repo checkout of `microgrid_IIoT_demo`.
- `gcloud` authenticated with IAP access to the broker VM (`microgrid-broker`).
- An active SSH agent for the VM key.

## 1.2 One-command build (recommended)
From `customer_sdk/`:

```bash
./build_customer_sdk.sh "<customer_name>" [--devices N] [--interval S] [--format zip|tgz]
# example:
./build_customer_sdk.sh "customer-test-001"
```

This single command:
1. **Provisions on the broker VM** (`onboard_customer.sh`): generates a GUID,
   issues an MQTT credential per device (`cust-<guid>-<NN>`), writes the customer
   registry entry, and schedules a **12-hour auto-revoke** timer.
2. **Packages** the installer (`build_bundle.sh`) into
   `dist/microgrid-sdk-<guid>.zip`.

Output includes the bundle path and the customer's dashboard URL.

## 1.3 Two-step alternative (manual)
```bash
# on the broker VM:
sudo bash onboard_customer.sh "<customer_name>" 12 1   > onboard.json
# on the operator workstation:
./build_bundle.sh onboard.json --interval 30 --feeder --format zip
```

## 1.4 What the bundle contains
```
microgrid-sdk-<guid>/
  install.sh                 customer installer (local broker + forwarder service)
  uninstall.sh               clean removal
  forwarder.py               local-broker → tinylab-broker forwarder (TLS, 12h self-stop)
  microgrid-gateway.service  systemd unit
  gateway.conf               PRE-FILLED identity (site_id, credential, broker host)
  ca.crt                     TLS CA for the tinylab broker
  sensor_feed.sh             optional test feeder (mosquitto_pub based)
  INSTALL.txt                quick-start for the customer
```

## 1.5 Deliver to the customer
- Email / transfer `dist/microgrid-sdk-<guid>.zip`.
- Provide the **dashboard URL**: `https://microgrid.tinylab.ai/c/?c=<guid>`.
- The trial runs **12 hours** from provisioning, then the credential auto-revokes.

> ⚠️ `dist/` bundles contain a **live MQTT credential**. They are git-ignored —
> do not commit or share beyond the intended customer.

## 1.6 Lifecycle management (operator, on the VM)
| Action | Command |
|---|---|
| Scale up a happy customer (add a device) | `sudo bash add_device.sh <guid> [count]` |
| Off-board a customer (full reversal) | `sudo bash offboard_customer.sh <guid> [--purge-data]` |
| Revoke a single device early | `sudo bash deprovision_customer.sh <site_id>` |

Off-boarding removes every `cust-<guid>-*` credential, cancels timers, and deletes
the registry entry — other customers are unaffected, no VM reconfiguration.

<div style="page-break-after: always;"></div>

---

# Part 2 — Customer Side: Deployment & Data Feed

*(performed by the customer on their remote site computer)*

## 2.1 Requirements
- **OS:** Linux (x86-64, ARM64/ARM32, or RISC-V) — e.g. Ubuntu, Debian, Raspberry Pi OS.
- **Privileges:** `sudo` (installs packages + a system service).
- **Network:** internet access, and **outbound TCP 8883** allowed to
  `34.87.254.184` (the tinylab MQTT broker).
- **Clock:** system time correct / NTP-synced (required for TLS). Important on a
  Raspberry Pi with no RTC.
- **Tools:** `unzip` (`sudo apt install unzip` if missing).

## 2.2 Install
```bash
unzip microgrid-sdk-<guid>.zip
cd microgrid-sdk-<guid>
sudo bash install.sh
```
`install.sh` will:
- install a **local** MQTT broker (mosquitto) + a Python venv,
- pick a free local port — **1883 by default, auto-bumped if busy** (it prints
  the chosen **LOCAL_PORT** — note it),
- register and start the **forwarder** as a systemd service (`Restart=always`),
- print a summary with the local broker endpoint, the trial expiry, and a
  ready-to-run test-feed command.

> The forwarder starts immediately and **waits** until it has seen all five
> metrics at least once before sending anything upstream (no all-null messages).

View live data at: **`https://microgrid.tinylab.ai/c/?c=<guid>`**

---

## 2.3 Option A — Use the bundled test feeder (no sensors needed)
```bash
bash sensor_feed.sh
```
- Uses `mosquitto_pub` (already installed) — **no Python/paho needed**.
- **Auto-detects** the local broker port from `gateway.conf`.
- Publishes realistic values to all five topics every ~2 s.
- Stop with `Ctrl-C`.

Within ~30–60 s your site appears on the dashboard.

---

## 2.4 Option B — Feed your OWN sensor data

This is the integration contract for a customer's own data gateway (a script or
device that reads sensors and publishes to the **local** MQTT broker). The
installed forwarder takes care of TLS, schema, and uplink to tinylab — your
gateway only needs to publish five values locally.

### 2.4.1 Local broker endpoint
| Property | Value |
|---|---|
| Host | `127.0.0.1` (or this device's LAN IP) |
| Port | **LOCAL_PORT** (default `1883`; check install output or `gateway.conf`) |
| Transport | plain TCP, **no TLS**, **anonymous** (local/trusted network) |

Find the port any time:
```bash
grep local_broker_port /opt/microgrid-gateway/gateway.conf
```

### 2.4.2 Topics, payload & units
Publish a **plain numeric string** to each topic (e.g. `84.2`). Last value wins;
publish each at least as often as your desired refresh (≤ 30 s recommended).

| MQTT topic (local) | Meaning | Unit | Example payload |
|---|---|---|---|
| `battery_soc` | Battery state of charge | % (0–100) | `84.2` |
| `battery_voltage` | Battery voltage | volts | `25.4` |
| `solar_output` | Solar generation | watts | `1850` |
| `load_demand` | Load consumption | watts | `540` |
| `inverter_temp` | Inverter temperature | °C | `34.1` |

> All five must be published at least once before the first upstream message.
> The forwarder maps these to the platform schema (`battery_soc`, `battery_v`,
> `solar_w`, `load_w`, `inverter_temp`) and derives the rest.

### 2.4.3 Example — shell (mosquitto_pub)
```bash
PORT=$(grep local_broker_port /opt/microgrid-gateway/gateway.conf | awk -F'= *' '{print $2}')
mosquitto_pub -h 127.0.0.1 -p "$PORT" -t battery_soc     -m 84.2
mosquitto_pub -h 127.0.0.1 -p "$PORT" -t battery_voltage -m 25.4
mosquitto_pub -h 127.0.0.1 -p "$PORT" -t solar_output    -m 1850
mosquitto_pub -h 127.0.0.1 -p "$PORT" -t load_demand     -m 540
mosquitto_pub -h 127.0.0.1 -p "$PORT" -t inverter_temp   -m 34.1
```

### 2.4.4 Example — Python (paho) gateway skeleton
Use your gateway's own Python environment (install paho there:
`pip install paho-mqtt` inside a venv, since system Python is PEP-668 managed).
```python
import time, paho.mqtt.client as mqtt

LOCAL_PORT = 1883  # set to your installed LOCAL_PORT
c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
c.connect("127.0.0.1", LOCAL_PORT, 60)
c.loop_start()

while True:
    soc, volt, solar, load, temp = read_my_sensors()  # your code
    c.publish("battery_soc",     str(soc))
    c.publish("battery_voltage", str(volt))
    c.publish("solar_output",    str(solar))
    c.publish("load_demand",     str(load))
    c.publish("inverter_temp",   str(temp))
    time.sleep(10)
```

---

## 2.5 Verify
```bash
# forwarder should log "Published cust-<guid>-NN ..."
journalctl -u microgrid-gateway -n 20 --no-pager
```
Then open `https://microgrid.tinylab.ai/c/?c=<guid>` — your site shows live KPIs
and charts, refreshing ~30 s.

## 2.6 Troubleshooting
| Symptom | Likely cause / fix |
|---|---|
| Dashboard empty | Not all 5 topics fed yet, or wrong port. Confirm LOCAL_PORT. |
| Feeder "connection refused" | Wrong port — use the installed LOCAL_PORT, not 1883. |
| Forwarder log: `not authorised` | Trial expired/revoked, or credential mismatch — contact tinylab. |
| TLS / certificate error | System clock wrong — sync time (NTP), then restart the service. |
| No `Published` lines | `systemctl status microgrid-gateway`; confirm the service is active. |

## 2.7 Stop / uninstall
```bash
# stop feeding: Ctrl-C the feeder / your gateway
sudo bash uninstall.sh        # removes the service, local broker config, install dir
```
The trial also stops automatically at the 12-hour mark.

---

*Document generated for the Microgrid Customer Trial SDK · tinylab.ai*
