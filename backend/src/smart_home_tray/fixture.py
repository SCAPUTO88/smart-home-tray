"""Deterministic JSON Lines fixture process for the Tauri bridge; never uses devices."""
from __future__ import annotations

import json
import sys
import threading
import time

LIMIT = 65_536
LOCK = threading.RLock()
DEVICES = {
    "fixture-desk-lamp": {"deviceId":"fixture-desk-lamp","name":"Luz Mesa (fixture)","address":"","protocolVersion":0,"capabilities":{"power":True,"whiteBrightness":True,"colorValue":True,"colorTemperature":True,"scenes":False},"connection":"online","state":{"power":True,"workMode":"colour","whiteBrightnessPercent":55,"colorValuePercent":70,"colorTemperaturePercent":48,"hsv":{"hue":194,"saturation":77,"value":70},"scene":None,"quality":"confirmed"}},
    "fixture-led-strip": {"deviceId":"fixture-led-strip","name":"Fita LED (fixture)","address":"","protocolVersion":0,"capabilities":{"power":True,"whiteBrightness":False,"colorValue":True,"colorTemperature":False,"scenes":False},"connection":"online","state":{"power":True,"workMode":"colour","whiteBrightnessPercent":None,"colorValuePercent":65,"colorTemperaturePercent":None,"hsv":{"hue":268,"saturation":88,"value":65},"scene":None,"quality":"confirmed"}},
}
ALLOWED = {"devices.list", "device.get", "device.status", "device.power", "device.whiteBrightness", "device.colorTemperature", "device.hsv", "device.colorBrightness"}
FIELDS = {"devices.list": set(), "device.get": {"deviceId"}, "device.status": {"deviceId"}, "device.power": {"deviceId", "enabled"}, "device.whiteBrightness": {"deviceId", "percent"}, "device.colorTemperature": {"deviceId", "percent"}, "device.colorBrightness": {"deviceId", "percent"}, "device.hsv": {"deviceId", "hue", "saturation", "value"}}
def respond(value: dict[str, object]) -> None:
    line = json.dumps(value, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    with LOCK:
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()

def handle(request: object) -> None:
    request_id = request.get("requestId") if isinstance(request, dict) else None
    if not isinstance(request_id, str) or not request_id or len(request_id) > 128 or set(request) != {"requestId", "command", "payload"}:
        respond({"requestId": None, "error": {"code":"INVALID_INPUT","message":"Request is invalid"}}); return
    command, payload = request["command"], request["payload"]
    if command not in ALLOWED or not isinstance(payload, dict) or set(payload) != FIELDS[command]:
        respond({"requestId":request_id,"error":{"code":"INVALID_INPUT","message":"Request is invalid"}}); return
    if command == "devices.list":
        respond({"requestId":request_id,"result":{"devices":list(DEVICES.values())}}); return
    device_id = payload.get("deviceId")
    if device_id not in DEVICES:
        respond({"requestId":request_id,"error":{"code":"DEVICE_OFFLINE","message":"Device is unreachable"}}); return
    if command == "device.status" and device_id == "fixture-desk-lamp": time.sleep(0.08)
    with LOCK:
        device = DEVICES[device_id]
        state = device["state"]
        if command == "device.power": state["power"] = payload["enabled"]
        elif command == "device.whiteBrightness":
            if not device["capabilities"]["whiteBrightness"]: respond({"requestId":request_id,"error":{"code":"UNSUPPORTED_CAPABILITY","message":"Device does not support this operation"}}); return
            state["whiteBrightnessPercent"] = payload["percent"]; state["workMode"] = "white"
        elif command == "device.colorTemperature": state["colorTemperaturePercent"] = payload["percent"]; state["workMode"] = "white"
        elif command in {"device.hsv", "device.colorBrightness"}:
            if not device["capabilities"]["colorValue"]: respond({"requestId":request_id,"error":{"code":"UNSUPPORTED_CAPABILITY","message":"Device does not support this operation"}}); return
            if command == "device.hsv": state["hsv"] = {"hue":payload["hue"],"saturation":payload["saturation"],"value":payload["value"]}; state["colorValuePercent"] = payload["value"]
            else: state["colorValuePercent"] = payload["percent"]; state["hsv"]["value"] = payload["percent"]
            state["workMode"] = "colour"
        state["quality"] = "confirmed"
        result = json.loads(json.dumps(device))
    respond({"requestId":request_id,"result":result})

def main() -> int:
    threads: list[threading.Thread] = []
    for raw in sys.stdin.buffer:
        if len(raw.rstrip(b"\r\n")) > LIMIT:
            respond({"requestId":None,"error":{"code":"INVALID_INPUT","message":"Message exceeds 64 KiB"}}); continue
        try: request = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError): respond({"requestId":None,"error":{"code":"INVALID_INPUT","message":"Request is invalid"}}); continue
        thread = threading.Thread(target=handle, args=(request,), daemon=True); thread.start(); threads.append(thread)
    for thread in threads: thread.join()
    return 0

if __name__ == "__main__": raise SystemExit(main())
