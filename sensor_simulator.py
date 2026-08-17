#!/usr/bin/env python3
"""
Random sensor data generator for the Zabbix Floor Plan integration.

What this does:
1. Asks the Zabbix API for every sensor item that was created by the
   floor plan page (their keys look like: sensor.temperature.abc123).
2. Every few seconds, makes up a random value for each sensor
   (a realistic range depending on whether it's temperature or humidity).
3. Sends that value to Zabbix using the "Zabbix sender" protocol,
   the same protocol the official zabbix_sender tool uses.

Run it with:  python sensor_simulator.py
Stop it with: Ctrl+C
"""

import json
import random
import socket
import struct
import time
import urllib.request

# ---- CONFIG: edit these if your setup is different -----------------------
ZABBIX_API_URL   = 'http://127.0.0.1:8080/api_jsonrpc.php'  # reachable from Windows
ZABBIX_API_TOKEN = '81619b8103c4b713cd76c675892896b410b494b7cd3a07c1ad84c6dd633a06c9'

ZABBIX_SENDER_HOST = '127.0.0.1'  # forwarded to the VM's port 10051 (see "Rule 1")
ZABBIX_SENDER_PORT = 10051

PROXY_URL = 'http://127.0.0.1:8080/floorplan/zabbix_proxy.php'  # same proxy the website uses

SEND_INTERVAL_SECONDS = 10  # how often to send new random values
# ----------------------------------------------------------------------------

# Realistic random ranges per sensor type, wide enough that the value
# occasionally crosses the alert thresholds (temperature > 25, humidity
# < 20 or > 80) so the Zabbix "Warnings" widget actually has something
# to show during a demo, instead of sitting empty forever.
VALUE_RANGES = {
    'temperature': (18.0, 33.0),
    'humidity':    (10.0, 90.0),
}
DEFAULT_RANGE = (0.0, 100.0)


def api_call(method, params):
    payload = {
        'jsonrpc': '2.0',
        'method': method,
        'params': params,
        'id': 1,
    }
    req = urllib.request.Request(
        ZABBIX_API_URL,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Content-Type': 'application/json-rpc',
            'Authorization': f'Bearer {ZABBIX_API_TOKEN}',
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read().decode('utf-8'))
    if 'error' in result:
        raise RuntimeError(result['error'])
    return result['result']


def get_floorplan_sensors():
    """Return a list of {host, key, type} for only the sensors that are
    CURRENTLY on the floor plan map right now (reads the same saved state
    file the website uses), not every sensor ever created during testing."""
    result = api_call_raw({'action': 'load_state'})
    if not result.get('success') or not result.get('data'):
        return []

    project = result['data']
    sensors = []
    for floor in project.get('floors', {}).values():
        for s in floor.get('sensors', []):
            item_id = s.get('zabbixItemId')
            host_name = s.get('zabbixHostName')
            sensor_type = s.get('type')
            sensor_id = s.get('id')
            if item_id and host_name and sensor_type and sensor_id:
                key = f'sensor.{sensor_type}.{sensor_id}'
                sensors.append({'host': host_name, 'key': key, 'type': sensor_type})
    return sensors


def api_call_raw(payload):
    """Calls our own PHP proxy (zabbix_proxy.php), not the raw Zabbix API."""
    req = urllib.request.Request(
        PROXY_URL,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))


def send_to_zabbix(values):
    """values: list of {host, key, value}. Speaks the Zabbix sender protocol."""
    data = {
        'request': 'sender data',
        'data': [
            {'host': v['host'], 'key': v['key'], 'value': str(v['value'])}
            for v in values
        ],
    }
    body = json.dumps(data).encode('utf-8')
    header = b'ZBXD\x01' + struct.pack('<Q', len(body))
    packet = header + body

    with socket.create_connection((ZABBIX_SENDER_HOST, ZABBIX_SENDER_PORT), timeout=10) as sock:
        sock.sendall(packet)
        # read the response header + body (just for confirmation, ignored here)
        sock.recv(1024)


def main():
    print('Starting sensor simulator...')
    print('(The sensor list is re-checked every cycle, so new sensors are picked up automatically.)\n')

    try:
        while True:
            sensors = get_floorplan_sensors()

            if not sensors:
                print('No floor plan sensors found right now. Waiting...')
                time.sleep(SEND_INTERVAL_SECONDS)
                continue

            values = []
            for s in sensors:
                low, high = VALUE_RANGES.get(s['type'], DEFAULT_RANGE)
                value = round(random.uniform(low, high), 1)
                values.append({'host': s['host'], 'key': s['key'], 'value': value})
                print(f"  {s['host']} / {s['key']} = {value}")

            send_to_zabbix(values)
            print('-- sent --\n')
            time.sleep(SEND_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print('\nStopped.')


if __name__ == '__main__':
    main()