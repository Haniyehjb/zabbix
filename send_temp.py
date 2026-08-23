import random
import time
import json
import urllib.request

# --- CONFIGURATION ---
ZABBIX_URL = "http://127.0.0.1:8080/zabbix/api_jsonrpc.php"

USERNAME = "Admin"
PASSWORD = "zabbix"

HOST_NAME = "Server Room"  # Must match Host name in Zabbix EXACTLY

# All item keys that need mock data. Add/remove keys here to match
# whatever itemKey values your CSV / sensors actually use.
ITEM_KEYS = ["room.temp", "room.temp2", "room.temp3", "room.temp4", "room.temp5"]

# Which existing item to copy settings (type, value_type, units...) from
# when a key in ITEM_KEYS doesn't exist yet and needs to be auto-created.
TEMPLATE_KEY = "room.temp"


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
        if "error" in res:
            raise Exception(res["error"])
        return res.get("result")


def random_temp():
    # 80% chance normal temp (20-25°C), 20% chance high temp (31-38°C)
    if random.random() < 0.8:
        return round(random.uniform(20.0, 25.0), 1)
    return round(random.uniform(31.0, 38.0), 1)


def ensure_items_exist(host_id, auth_token):
    """Create any key in ITEM_KEYS that doesn't exist yet on the host,
    cloning settings from TEMPLATE_KEY. Returns {key: itemid} for all keys."""

    existing = api_call(
        "item.get",
        {"output": ["itemid", "key_"], "hostids": host_id, "filter": {"key_": ITEM_KEYS}},
        auth_token
    )
    item_ids = {it["key_"]: it["itemid"] for it in existing}

    missing = [k for k in ITEM_KEYS if k not in item_ids]
    if not missing:
        return item_ids

    template_items = api_call(
        "item.get",
        {"output": "extend", "hostids": host_id, "filter": {"key_": TEMPLATE_KEY}},
        auth_token
    )
    if not template_items:
        print(f"⚠️  Can't auto-create missing items: template '{TEMPLATE_KEY}' not found. "
              f"Skipping: {', '.join(missing)}")
        return item_ids

    template = template_items[0]
    fields_to_copy = ["type", "value_type", "delay", "history", "trends", "units", "interfaceid"]

    for key in missing:
        new_item = {"hostid": host_id, "key_": key, "name": key}
        for field in fields_to_copy:
            if field in template and template[field] not in (None, ""):
                new_item[field] = template[field]
        try:
            result = api_call("item.create", new_item, auth_token)
            item_ids[key] = result["itemids"][0]
            print(f"✅ Auto-created missing item '{key}'")
        except Exception as e:
            print(f"❌ Could not auto-create '{key}': {e}")

    return item_ids


print("🔑 Authenticating with Zabbix API...")
try:
    # 1. Login to get Auth Token
    auth_token = api_call("user.login", {"username": USERNAME, "password": PASSWORD})
    print("✅ Authenticated successfully!")

    # 2. Find the host
    hosts = api_call("host.get", {"filter": {"host": HOST_NAME}}, auth_token)
    if not hosts:
        hosts = api_call("host.get", {"filter": {"name": HOST_NAME}}, auth_token)
    if not hosts:
        print(f"❌ Host '{HOST_NAME}' not found in Zabbix!")
        exit()
    host_id = hosts[0]["hostid"]
    print(f"✅ Found host '{HOST_NAME}' -> ID {host_id}")

    # 3. Make sure every key in ITEM_KEYS exists (auto-creating if needed)
    item_ids = ensure_items_exist(host_id, auth_token)
    if not item_ids:
        print("❌ No items available to send data to. Exiting.")
        exit()

    print(f"\n🚀 Starting Mock Temperature Sensors for: {', '.join(item_ids.keys())}")
    while True:
        for key, item_id in item_ids.items():
            temp = random_temp()
            result = api_call("history.push", [{"itemid": item_id, "value": str(temp)}], auth_token)
            print(f"[{key}] Sent: {temp}°C | Status: {result}")
        time.sleep(10)

except Exception as e:
    print(f"Error: {e}")
