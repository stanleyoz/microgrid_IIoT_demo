import csv
import math
import random
from datetime import datetime, timedelta

def generate_telemetry(site_id, ts):
    # Reuse sim_site.py logic
    hour_of_day = ts.hour + ts.minute / 60.0
    
    solar_w = 0
    if 6 < hour_of_day < 18:
        solar_w = 3000 * math.sin(math.pi * (hour_of_day - 6) / 12) + random.uniform(-100, 100)
        solar_w = max(0, solar_w)
    
    load_w = 500 + 1000 * random.random()
    if 18 < hour_of_day < 21:
        load_w += 2000
        
    power_balance_w = solar_w - load_w
    battery_soc = 50 + 40 * math.sin(math.pi * (hour_of_day - 12) / 24) # Realistic cycle
    battery_v = 24.0 + (battery_soc / 100.0) * 3.5
    battery_current = -power_balance_w / battery_v
    
    ac_input_v = 230.0 + random.uniform(-2, 2)
    ac_output_v = 231.0 + random.uniform(-1, 1)
    ac_output_i = load_w / ac_output_v
    ac_input_power = 0.0
    ac_output_power = load_w
    inverter_temp = 30.0 + (load_w / 4000) * 20.0
    battery_temp = 22.0 + (abs(battery_current) / 50) * 10.0
    inverter_state = 9 if battery_soc > 10 else 10
    
    return {
        "site_id": site_id,
        "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
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
        "power_balance_w": round(power_balance_w, 1),
        "data": "{}" # Placeholder
    }

sites = [f"site-{i:02d}" for i in range(1, 12)] + ["hw-node-01"]
end_time = datetime.utcnow()
start_time = end_time - timedelta(hours=24)

with open('historical_data.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=["site_id", "timestamp", "battery_v", "battery_soc", "battery_current", "battery_temp", "ac_input_v", "ac_output_v", "ac_output_i", "ac_input_power", "ac_output_power", "solar_w", "load_w", "inverter_state", "inverter_temp", "fault_code", "power_balance_w", "data"])
    
    curr = start_time
    while curr <= end_time:
        for site in sites:
            writer.writerow(generate_telemetry(site, curr))
        curr += timedelta(minutes=1)
