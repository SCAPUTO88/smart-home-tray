import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src"

def start_fixture():
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(SRC)}
    return subprocess.Popen([sys.executable, "-u", "-m", "smart_home_tray.fixture"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)

def send(process, request):
    process.stdin.write(json.dumps(request).encode() + b"\n")
    process.stdin.flush()
    return json.loads(process.stdout.readline())

def test_fixture_lists_public_devices_without_private_or_physical_fields():
    process = start_fixture()
    try:
        result = send(process, {"requestId":"list-1", "command":"devices.list", "payload":{}})
        assert result["requestId"] == "list-1"
        devices = result["result"]["devices"]
        assert {item["deviceId"] for item in devices} == {"fixture-desk-lamp", "fixture-led-strip"}
        assert devices[0]["state"]["knowledge"]["hsv"] == "observed"
        assert devices[0]["state"]["knowledge"]["colorValue"] == devices[0]["state"]["knowledge"]["hsv"]
        assert all("localKey" not in item and "dps" not in item for item in devices)
    finally:
        process.stdin.close()
        assert process.wait(timeout=3) == 0

def test_fixture_supports_existing_hsv_and_power_commands():
    process = start_fixture()
    try:
        result = send(process, {"requestId":"hsv-1", "command":"device.hsv", "payload":{"deviceId":"fixture-led-strip","hue":245,"saturation":80,"value":22}})
        assert result["result"]["state"]["hsv"] == {"hue":245,"saturation":80,"value":22}
        power = send(process, {"requestId":"power-1", "command":"device.power", "payload":{"deviceId":"fixture-led-strip","enabled":False}})
        assert power["result"]["state"]["power"] is False
    finally:
        process.stdin.close()
        assert process.wait(timeout=3) == 0

def test_fixture_allows_out_of_order_status_responses():
    process = start_fixture()
    try:
        requests = [
            {"requestId":"slow", "command":"device.status", "payload":{"deviceId":"fixture-desk-lamp"}},
            {"requestId":"fast", "command":"device.status", "payload":{"deviceId":"fixture-led-strip"}},
        ]
        process.stdin.write(b"".join(json.dumps(item).encode() + b"\n" for item in requests))
        process.stdin.flush()
        first = json.loads(process.stdout.readline())
        second = json.loads(process.stdout.readline())
        assert first["requestId"] == "fast"
        assert second["requestId"] == "slow"
    finally:
        process.stdin.close()
        assert process.wait(timeout=3) == 0
