import random
import time
import json
import urllib.request

# --- CONFIGURATION ---
# http://localhost:8080/zabbix or http://127.0.0.1:8080/zabbix
ZABBIX_URL = "http://127.0.0.1:8080/zabbix/api_jsonrpc.php"

# Default admin login credentials
USERNAME = "Admin"
PASSWORD = "zabbix"

HOST_NAME = "Server Room"  # Must match Host name in Zabbix EXACTLY
ITEM_KEY = "room.temp"  # Must match Item key in Zabbix EXACTLY


def api_call(method, params, auth_token=None):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1
    }
    if auth_token:
        payload["auth"] = auth_token

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(ZABBIX_URL, data=data, headers={'Content-Type': 'application/json-rpc'})

    with urllib.request.urlopen(req) as response:
        res = json.loads(response.read().decode('utf-8'))
        return res.get("result")


print("🔑 Authenticating with Zabbix API...")
try:
    # 1. Login to get Auth Token
    auth_token = api_call("user.login", {"username": USERNAME, "password": PASSWORD})
    print("✅ Authenticated successfully!")

    # 2. Get Item ID for room.temp
    items = api_call("item.get", {"filter": {"host": HOST_NAME, "key_": ITEM_KEY}}, auth_token)
    if not items:
        print(f"❌ Could not find host '{HOST_NAME}' or item key '{ITEM_KEY}' in Zabbix!")
        exit()

    item_id = items[0]["itemid"]
    print(f"✅ Found Item ID: {item_id}")

    print("\n🚀 Starting Mock Temperature Sensor...")
    while True:
        # 80% chance normal temp (20-25°C), 20% chance high temp (31-38°C)
        if random.random() < 0.8:
            temp = round(random.uniform(20.0, 25.0), 1)
        else:
            temp = round(random.uniform(31.0, 38.0), 1)

        # Send history data directly via Zabbix API
        # (For Trapper items or direct history push)
        result = api_call("history.push", [{"itemid": item_id, "value": str(temp)}], auth_token)

        print(f"Sent: {temp}°C | Status: {result}")
        time.sleep(10)

except Exception as e:
    print(f"Error: {e}")