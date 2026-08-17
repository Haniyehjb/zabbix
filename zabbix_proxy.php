<?php
// =========================================================================
// Zabbix Proxy - a safe middle-man between the website and the Zabbix API.
// The API token stays on the server only, it is never sent to the browser.
// =========================================================================

header('Content-Type: application/json');

// ---- CONFIG: fill these in ---------------------------------------------
$ZABBIX_API_URL   = 'http://127.0.0.1/api_jsonrpc.php'; // Zabbix API endpoint on this same server
$ZABBIX_API_TOKEN = '81619b8103c4b713cd76c675892896b410b494b7cd3a07c1ad84c6dd633a06c9';   // Users > API tokens in Zabbix
$ZABBIX_HOST_GROUP_ID = '2'; // default "Linux servers" group id, change if needed
// -------------------------------------------------------------------------

function zabbix_call($method, $params, $apiUrl, $token) {
    $payload = [
        'jsonrpc' => '2.0',
        'method'  => $method,
        'params'  => $params,
        'id'      => 1,
    ];

    $ch = curl_init($apiUrl);
    curl_setopt($ch, CURLOPT_POST, true);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_HTTPHEADER, [
        'Content-Type: application/json-rpc',
        'Authorization: Bearer ' . $token,
    ]);
    curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($payload));
    $response = curl_exec($ch);
    $err = curl_error($ch);
    curl_close($ch);

    if ($err) {
        return ['error' => $err];
    }
    return json_decode($response, true);
}

function create_trigger_for_item($hostName, $itemId, $type, $sensorId, $apiUrl, $token) {
    // Build the trigger expression + description based on sensor type.
    // Zabbix trigger expressions reference the host by its technical name, not its numeric id.
    if ($type === 'temperature') {
        $expression = "last(/{$hostName}/sensor.temperature.{$sensorId})>25";
        $name = "High temperature on sensor {$sensorId} (>25°)";
        zabbix_call('trigger.create', [
            'description' => $name,
            'expression' => $expression,
            'priority' => 2, // Warning
        ], $apiUrl, $token);
    } elseif ($type === 'humidity') {
        $exprLow = "last(/{$hostName}/sensor.humidity.{$sensorId})<20";
        $exprHigh = "last(/{$hostName}/sensor.humidity.{$sensorId})>80";
        zabbix_call('trigger.create', [
            'description' => "Low humidity on sensor {$sensorId} (<20%)",
            'expression' => $exprLow,
            'priority' => 2,
        ], $apiUrl, $token);
        zabbix_call('trigger.create', [
            'description' => "High humidity on sensor {$sensorId} (>80%)",
            'expression' => $exprHigh,
            'priority' => 2,
        ], $apiUrl, $token);
    }
}

$input = json_decode(file_get_contents('php://input'), true);
$action = $input['action'] ?? '';

// -------------------------------------------------------------------------
// ACTION: create_sensor
// Creates a Zabbix host (per room, reused if it already exists) and a
// trapper item (per sensor type) inside it.
// -------------------------------------------------------------------------
if ($action === 'create_sensor') {
    $room = preg_replace('/[^a-zA-Z0-9 _\-]/', '', $input['room'] ?? 'UnknownRoom');
    $type = preg_replace('/[^a-zA-Z0-9_]/', '', $input['type'] ?? 'sensor');
    $sensorId = preg_replace('/[^a-zA-Z0-9_]/', '', $input['sensorId'] ?? uniqid());

    $hostName = 'FloorPlan - ' . $room;
    $itemKey = 'sensor.' . $type . '.' . $sensorId;

    // 1. Find or create the host for this room
    $hostSearch = zabbix_call('host.get', [
        'filter' => ['host' => $hostName],
        'output' => ['hostid'],
    ], $ZABBIX_API_URL, $ZABBIX_API_TOKEN);

    $hostId = null;
    if (!empty($hostSearch['result'])) {
        $hostId = $hostSearch['result'][0]['hostid'];
    } else {
        $hostCreate = zabbix_call('host.create', [
            'host' => $hostName,
            'groups' => [['groupid' => $ZABBIX_HOST_GROUP_ID]],
            'interfaces' => [],
        ], $ZABBIX_API_URL, $ZABBIX_API_TOKEN);

        if (!empty($hostCreate['result']['hostids'][0])) {
            $hostId = $hostCreate['result']['hostids'][0];
        } else {
            echo json_encode(['success' => false, 'error' => $hostCreate['error'] ?? 'Could not create host']);
            exit;
        }
    }

    // 2. Create the trapper item for this sensor (skip if it already exists)
    $itemSearch = zabbix_call('item.get', [
        'hostids' => [$hostId],
        'filter' => ['key_' => $itemKey],
        'output' => ['itemid'],
    ], $ZABBIX_API_URL, $ZABBIX_API_TOKEN);

    $itemId = null;
    $isNewItem = false;
    if (!empty($itemSearch['result'])) {
        $itemId = $itemSearch['result'][0]['itemid'];
    } else {
        $itemCreate = zabbix_call('item.create', [
            'name' => ucfirst($type) . ' - ' . $sensorId,
            'key_' => $itemKey,
            'hostid' => $hostId,
            'type' => 2,        // 2 = Zabbix trapper (values pushed in, not polled)
            'value_type' => 0,  // 0 = float
        ], $ZABBIX_API_URL, $ZABBIX_API_TOKEN);

        if (!empty($itemCreate['result']['itemids'][0])) {
            $itemId = $itemCreate['result']['itemids'][0];
            $isNewItem = true;
        } else {
            echo json_encode(['success' => false, 'error' => $itemCreate['error'] ?? 'Could not create item']);
            exit;
        }
    }

    // 3. Create the alert trigger(s) for this sensor, only the first time it's made.
    if ($isNewItem) {
        create_trigger_for_item($hostName, $itemId, $type, $sensorId, $ZABBIX_API_URL, $ZABBIX_API_TOKEN);
    }

    echo json_encode([
        'success' => true,
        'hostId'  => $hostId,
        'itemId'  => $itemId,
        'itemKey' => $itemKey,
        'hostName' => $hostName,
    ]);
    exit;
}

// -------------------------------------------------------------------------
// ACTION: get_value
// Reads the latest value for a given itemId, to show live on the map.
// -------------------------------------------------------------------------
if ($action === 'get_value') {
    $itemId = preg_replace('/[^0-9]/', '', $input['itemId'] ?? '');
    if (!$itemId) {
        echo json_encode(['success' => false, 'error' => 'Missing itemId']);
        exit;
    }

    $history = zabbix_call('history.get', [
        'itemids' => [$itemId],
        'history' => 0, // float history
        'sortfield' => 'clock',
        'sortorder' => 'DESC',
        'limit' => 1,
    ], $ZABBIX_API_URL, $ZABBIX_API_TOKEN);

    if (!empty($history['result'])) {
        echo json_encode(['success' => true, 'value' => $history['result'][0]['value'], 'clock' => $history['result'][0]['clock']]);
    } else {
        echo json_encode(['success' => true, 'value' => null]);
    }
    exit;
}

// -------------------------------------------------------------------------
// ACTION: save_state
// Saves the whole floor plan project (rooms, sensors, positions) to a file
// on the server, so every visitor sees the same map.
// -------------------------------------------------------------------------
if ($action === 'save_state') {
    $stateDir = __DIR__ . '/data';
    if (!is_dir($stateDir)) {
        mkdir($stateDir, 0755, true);
    }
    $file = $stateDir . '/project_state.json';
    $ok = file_put_contents($file, json_encode($input['data'] ?? new stdClass()));
    echo json_encode(['success' => $ok !== false]);
    exit;
}

// -------------------------------------------------------------------------
// ACTION: load_state
// Reads back the project saved by save_state.
// -------------------------------------------------------------------------
if ($action === 'load_state') {
    $file = __DIR__ . '/data/project_state.json';
    if (!file_exists($file)) {
        echo json_encode(['success' => true, 'data' => null]);
        exit;
    }
    $content = file_get_contents($file);
    echo json_encode(['success' => true, 'data' => json_decode($content, true)]);
    exit;
}

// -------------------------------------------------------------------------
// ACTION: backfill_triggers
// One-off helper: scans every "FloorPlan - ..." host and creates missing
// triggers for sensors that were created before triggers existed.
// -------------------------------------------------------------------------
if ($action === 'backfill_triggers') {
    $hosts = zabbix_call('host.get', [
        'output' => ['hostid', 'host'],
        'search' => ['host' => 'FloorPlan - '],
        'startSearch' => true,
    ], $ZABBIX_API_URL, $ZABBIX_API_TOKEN);

    $created = [];
    foreach (($hosts['result'] ?? []) as $host) {
        $items = zabbix_call('item.get', [
            'hostids' => [$host['hostid']],
            'search' => ['key_' => 'sensor.'],
            'startSearch' => true,
            'output' => ['itemid', 'key_'],
        ], $ZABBIX_API_URL, $ZABBIX_API_TOKEN);

        foreach (($items['result'] ?? []) as $item) {
            $parts = explode('.', $item['key_']); // sensor.<type>.<sensorId>
            if (count($parts) < 3) continue;
            $type = $parts[1];
            $sensorId = $parts[2];

            $existingTriggers = zabbix_call('trigger.get', [
                'itemids' => [$item['itemid']],
                'output' => ['triggerid'],
            ], $ZABBIX_API_URL, $ZABBIX_API_TOKEN);

            if (empty($existingTriggers['result'])) {
                create_trigger_for_item($host['host'], $item['itemid'], $type, $sensorId, $ZABBIX_API_URL, $ZABBIX_API_TOKEN);
                $created[] = $host['host'] . ' / ' . $item['key_'];
            }
        }
    }

    echo json_encode(['success' => true, 'created' => $created]);
    exit;
}

echo json_encode(['success' => false, 'error' => 'Unknown action']);