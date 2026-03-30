import json
import logging
import os
import time
import random
import math
from datetime import datetime
import paho.mqtt.client as mqtt
import ssl

# Configuration from Environment
BROKER_HOST = os.getenv('BROKER_HOST', 'localhost')
BROKER_PORT = int(os.getenv('BROKER_PORT', 8883))
SITE_ID = os.getenv('SITE_ID', 'sim-site-01')
INTERVAL_S = float(os.getenv('INTERVAL_S', 10))
TIME_SCALE = float(os.getenv('TIME_SCALE', 1.0))
MQTT_USER = os.getenv('MQTT_USER', 'site-01')
MQTT_PASS = os.getenv('MQTT_PASS', 'site-pass-secret')

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(f'sim-{SITE_ID}')

# State variables for simulation
# Derive a unique seed from SITE_ID so each container gets a stable but distinct profile
_site_num = int(''.join(filter(str.isdigit, SITE_ID)) or 1)
random.seed(_site_num)

# Stagger starting SOC: sites span 15%–95% so charts diverge immediately
battery_soc = 15.0 + (_site_num % 11) * 7.5 + random.uniform(-3, 3)
battery_v = 24.0 + (battery_soc / 100.0) * 3.5

# Phase-shift each site's solar clock by up to 4 simulated hours so cycles are offset
sim_time_offset = _site_num * (4 * 3600)  # seconds — shifts hour_of_day per site

random.seed()  # Restore true randomness for runtime noise

def generate_telemetry():
    global battery_soc, battery_v, sim_time_offset
    
    # Simulate time of day for solar (0 to 24h)
    # Using real time scaled by TIME_SCALE
    now_epoch = (time.time() + sim_time_offset) * TIME_SCALE
    hour_of_day = (now_epoch / 3600) % 24
    
    # Solar generation (sinusoidal during day)
    solar_w = 0
    if 6 < hour_of_day < 18:
        solar_w = 3000 * math.sin(math.pi * (hour_of_day - 6) / 12) + random.uniform(-100, 100)
        solar_w = max(0, solar_w)
    
    # Load (base load + spikes)
    load_w = 500 + 1000 * random.random()
    if 18 < hour_of_day < 21: # Evening peak
        load_w += 2000
        
    # Power balance
    power_balance_w = solar_w - load_w
    
    # Battery dynamics (simplified)
    # 24V system, 200Ah = 4800Wh
    capacity_wh = 4800
    charge_efficiency = 0.95
    
    delta_wh = (power_balance_w * (INTERVAL_S / 3600)) * (charge_efficiency if power_balance_w > 0 else 1.0)
    battery_soc += (delta_wh / capacity_wh) * 100
    battery_soc = max(5, min(100, battery_soc))
    
    # Voltage follows SOC
    battery_v = 24.0 + (battery_soc / 100.0) * 3.5 + random.uniform(-0.05, 0.05)
    battery_current = -power_balance_w / battery_v # negative is discharging
    
    # Other fields
    ac_input_v = 230.0 + random.uniform(-2, 2)
    ac_output_v = 231.0 + random.uniform(-1, 1)
    ac_output_i = load_w / ac_output_v
    ac_input_power = 0.0 # Off-grid simulation
    ac_output_power = load_w
    
    inverter_temp = 30.0 + (load_w / 4000) * 20.0 + random.uniform(-1, 1)
    battery_temp = 22.0 + (abs(battery_current) / 50) * 10.0
    
    inverter_state = 9 # 'Inverting'
    if battery_soc < 10:
        inverter_state = 10 # 'Low battery'
    
    payload = {
        "site_id": SITE_ID,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "battery_v": round(battery_v, 2),
        "battery_soc": round(battery_soc, 1),
        "battery_current": round(battery_current, 2),
        "battery_temp": round(battery_temp, 1),
        "ac_input_v": round(ac_input_v, 1),
        "ac_output_v": round(ac_output_v, 1),
        "ac_output_i": round(ac_output_i, 2),
        "ac_input_power": round(ac_input_power, 1),
        "ac_output_power": round(ac_output_power, 1),
        "solar_w": round(solar_w, 1),
        "load_w": round(load_w, 1),
        "inverter_state": inverter_state,
        "inverter_temp": round(inverter_temp, 1),
        "fault_code": 0,
        "power_balance_w": round(power_balance_w, 1)
    }
    
    return payload

def run():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    
    # TLS Configuration
    # Assumes ca.crt is in the same directory or mapped in container
    if BROKER_PORT == 8883:
        client.tls_set(ca_certs='ca.crt', cert_reqs=ssl.CERT_REQUIRED)
        client.tls_insecure_set(True)

    log.info(f"Connecting to {BROKER_HOST}:{BROKER_PORT}...")
    client.connect(BROKER_HOST, BROKER_PORT, 60)
    client.loop_start()

    topic = f"microgrid/{SITE_ID}/telemetry"
    
    while True:
        payload = generate_telemetry()
        log.info(f"Publishing telemetry to {topic}")
        client.publish(topic, json.dumps(payload), qos=1)
        
        # Scale sleep by TIME_SCALE
        time.sleep(INTERVAL_S / TIME_SCALE)

if __name__ == '__main__':
    run()
