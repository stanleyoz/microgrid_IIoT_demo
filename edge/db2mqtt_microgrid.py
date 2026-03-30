## Updated for Microgrid IIoT Demo (March 2026)
# Target: GCP Project microgrid-demo
# Features: TLS Port 8883, Site ID partitioning, Secure Auth

import json
import os
import sys
import time
import paho.mqtt.client as mqttClient
import ssl
import sqlite3
import uuid
from datetime import datetime

# --- GCP CONFIGURATION ---
GCP_BROKER_IP = "34.87.254.184" 
MQTT_PORT = 8883  
SITE_ID = "hw-node-01" # This identifies this hardware in BigQuery
MQTT_TOPIC = f"microgrid/{SITE_ID}/telemetry"
MQTT_USER = "hw-node-01"
MQTT_PASS = "node-pass-secret"

# Paths on nodeG5
TLS_CA_PATH = "/user/mqtt/ca.crt" # Ensure you copy the CA cert here
DB_PATH = "/amp/var/dataout.db"
GPS_DB_PATH = "/amp/var/gpsdata.db"

connected = False

def on_connect(client, userdata, flags, rc, properties=None):
    global connected
    if rc == 0:
        print(f"[INFO] Connected to Microgrid Broker as {SITE_ID}")
        connected = True
    else:
        print(f"[ERROR] Connection failed, rc={rc}")
        connected = False

def on_disconnect(client, userdata, rc, properties=None):
    global connected
    connected = False
    print("[WARN] Disconnected from broker")

def main():
    global connected
    # Use Callback Version 2 for newer paho-mqtt if available
    try:
        mqtt_client = mqttClient.Client(mqttClient.CallbackAPIVersion.VERSION2)
    except AttributeError:
        mqtt_client = mqttClient.Client()

    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)

    # TLS Setup
    print(f"[INFO] Loading TLS CA from {TLS_CA_PATH}")
    mqtt_client.tls_set(ca_certs=TLS_CA_PATH, cert_reqs=ssl.CERT_REQUIRED)
    mqtt_client.tls_insecure_set(True) # Set to True if using a self-signed cert

    print(f"[INFO] Connecting to {GCP_BROKER_IP}:{MQTT_PORT}...")
    
    try:
        mqtt_client.connect(GCP_BROKER_IP, MQTT_PORT, keepalive=60)
        mqtt_client.loop_start()
    except Exception as e:
        print(f"[ERROR] Could not initiate connection: {e}")
        sys.exit(1)

    while True:
        if not connected:
            time.sleep(1)
            continue

        try:
            # 1. Process Telemetry (FIFO)
            db = sqlite3.connect(DB_PATH)
            cursor = db.cursor()
            cursor.execute("SELECT ROWID, RecOn, DeviceId, Key, Val FROM dataout ORDER BY ROWID ASC LIMIT 1")
            row = cursor.fetchone()

            if row:
                row_id, rec_on, dev_id, key, val = row
                
                # Format payload to match the new 13-feature schema requirements
                payload = {
                    "site_id": SITE_ID,
                    "timestamp": rec_on,
                    "device_id": dev_id,
                    key: float(val) 
                }

                print(f"[SEND] {key}: {val}")
                res = mqtt_client.publish(MQTT_TOPIC, json.dumps(payload), qos=1)
                res.wait_for_publish()

                cursor.execute(f"DELETE FROM dataout WHERE ROWID = {row_id}")
                db.commit()
            db.close()

            # 2. Process GPS
            gps_db = sqlite3.connect(GPS_DB_PATH)
            g_cursor = gps_db.cursor()
            g_cursor.execute("SELECT ROWID, altitude, latitude, longitude, RecOn FROM gpsdata ORDER BY ROWID ASC LIMIT 1")
            g_row = g_cursor.fetchone()

            if g_row:
                grid, alt, lat, lon, g_ts = g_row
                gps_payload = {
                    "site_id": SITE_ID,
                    "timestamp": g_ts,
                    "lat": lat,
                    "lng": lon,
                    "alt": alt
                }
                print(f"[GPS] {lat}, {lon}")
                mqtt_client.publish(f"microgrid/{SITE_ID}/gps", json.dumps(gps_payload), qos=1)
                
                g_cursor.execute(f"DELETE FROM gpsdata WHERE ROWID = {grid}")
                gps_db.commit()
            gps_db.close()

        except Exception as e:
            print(f"[ERROR] Loop error: {e}")
        
        time.sleep(0.5)

if __name__ == "__main__":
    main()
