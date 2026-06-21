#!/usr/bin/env bash
#
# Test sensor feeder — publishes realistic values to the five local gateway
# topics using mosquitto_pub (no Python/paho dependency; mosquitto-clients is
# installed by install.sh). Auto-detects the local broker port from the
# installed gateway.conf, so there is nothing to remember.
#
# Usage:  bash sensor_feed.sh [--port N] [--host H] [--interval S]
#
set -euo pipefail
HOST=127.0.0.1; INTERVAL=2; PORT=""
while [ $# -gt 0 ]; do case "$1" in
  --port) PORT="$2"; shift 2;;
  --host) HOST="$2"; shift 2;;
  --interval) INTERVAL="$2"; shift 2;;
  *) echo "unknown arg: $1"; exit 1;; esac; done

# Resolve the local broker port from the installed/local gateway.conf if not given.
if [ -z "$PORT" ]; then
    for f in /opt/microgrid-gateway/gateway.conf ./gateway.conf; do
        if [ -f "$f" ]; then
            PORT="$(awk -F'= *' '/^local_broker_port/{print $2}' "$f" | tr -d '[:space:]')"
            [ -n "$PORT" ] && break
        fi
    done
fi
PORT="${PORT:-1883}"

command -v mosquitto_pub >/dev/null || { echo "mosquitto_pub not found — install mosquitto-clients."; exit 1; }

echo "Feeding test sensor data to $HOST:$PORT every ${INTERVAL}s (Ctrl-C to stop)…"
i=0
while true; do
    soc=$(awk   -v i="$i" 'BEGIN{printf "%.1f", 60+20*sin(i/15)}')
    volt=$(awk  -v s="$soc" 'BEGIN{printf "%.2f", 24+s/100*3.5}')
    solar=$(awk -v i="$i" 'BEGIN{v=2000*sin(i/10); if(v<0)v=0; printf "%.0f", v}')
    load=$(awk  'BEGIN{srand(); printf "%.0f", 400+rand()*400}')
    temp=$(awk  'BEGIN{srand(); printf "%.1f", 30+rand()*6}')
    mosquitto_pub -h "$HOST" -p "$PORT" -t battery_soc     -m "$soc"
    mosquitto_pub -h "$HOST" -p "$PORT" -t battery_voltage -m "$volt"
    mosquitto_pub -h "$HOST" -p "$PORT" -t solar_output    -m "$solar"
    mosquitto_pub -h "$HOST" -p "$PORT" -t load_demand     -m "$load"
    mosquitto_pub -h "$HOST" -p "$PORT" -t inverter_temp   -m "$temp"
    echo "fed  soc=$soc  volt=$volt  solar=$solar  load=$load  temp=$temp"
    i=$((i+1)); sleep "$INTERVAL"
done
