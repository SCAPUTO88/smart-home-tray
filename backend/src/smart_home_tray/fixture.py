"""Deterministic JSON Lines fixture process; uses no devices, sockets, or cloud."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

LIMIT = 65_536
LOCK = threading.RLock()
TTL_SECONDS = 60.0
MAX_PENDING_PROPOSALS = 4
_RECOVERY_ACTIVE_SLOT = threading.Lock()


def _device(device_id: str, name: str, protocol: float, address: str) -> dict[str, object]:
    return {
        "deviceId": device_id,
        "name": name,
        "address": address,
        "protocolVersion": protocol,
        "capabilities": {"power": True, "whiteBrightness": True, "colorValue": True, "colorTemperature": True, "scenes": False},
        "connection": "online",
        "state": {
            "power": True,
            "workMode": "colour",
            "whiteBrightnessPercent": 55.0,
            "colorValuePercent": 70.0,
            "colorTemperaturePercent": 48.0,
            "hsv": {"hue": 194.0, "saturation": 77.0, "value": 70.0},
            "scene": None,
            "quality": "confirmed",
            "knowledge": {"power": "observed", "workMode": "observed", "whiteBrightness": "observed", "colorTemperature": "observed", "hsv": "observed", "colorValue": "observed", "scene": "unknown"},
        },
    }


DEVICES: dict[str, dict[str, object]] = {
    "fixture-desk-lamp": {"deviceId":"fixture-desk-lamp","name":"Luz Mesa (fixture)","address":"","protocolVersion":0,"capabilities":{"power":True,"whiteBrightness":True,"colorValue":True,"colorTemperature":True,"scenes":False},"connection":"online","state":{"power":True,"workMode":"colour","whiteBrightnessPercent":55,"colorValuePercent":70,"colorTemperaturePercent":48,"hsv":{"hue":194,"saturation":77,"value":70},"scene":None,"quality":"confirmed","knowledge":{"power":"observed","workMode":"observed","whiteBrightness":"observed","colorTemperature":"observed","hsv":"observed","colorValue":"observed","scene":"unknown"}}},
    "fixture-led-strip": {"deviceId":"fixture-led-strip","name":"Fita LED (fixture)","address":"","protocolVersion":0,"capabilities":{"power":True,"whiteBrightness":False,"colorValue":True,"colorTemperature":False,"scenes":False},"connection":"online","state":{"power":True,"workMode":"colour","whiteBrightnessPercent":None,"colorValuePercent":65,"colorTemperaturePercent":None,"hsv":{"hue":268,"saturation":88,"value":65},"scene":None,"quality":"confirmed","knowledge":{"power":"observed","workMode":"observed","whiteBrightness":"unknown","colorTemperature":"unknown","hsv":"observed","colorValue":"observed","scene":"unknown"}}},
}

# Fixed profiles make recovery scenarios selectable by fixture Device ID only.
# The addresses below are documentation-only IPv4 ranges, never routed.
_RECOVERY_PROFILES: dict[str, tuple[float, str, str]] = {
    "fixture-tuya35": (3.5, "PROPOSAL_READY", "198.51.100.35"),
    "fixture-tuya35-alt": (3.5, "PROPOSAL_READY", "198.51.100.36"),
    "fixture-tuya33": (3.3, "PROTOCOL_NOT_ELIGIBLE", "198.51.100.37"),
    "fixture-recovery-ambiguous": (3.5, "AMBIGUOUS", "198.51.100.38"),
    "fixture-recovery-not-found": (3.5, "NOT_FOUND", "198.51.100.39"),
    "fixture-recovery-auth-failed": (3.5, "AUTH_FAILED", "198.51.100.40"),
    "fixture-recovery-transport-failed": (3.5, "TRANSPORT_FAILED", "198.51.100.41"),
    "fixture-recovery-busy": (3.5, "BUSY", "198.51.100.42"),
    "fixture-recovery-config-changed": (3.5, "CONFIG_CHANGED", "198.51.100.43"),
    "fixture-recovery-timeout": (3.5, "TIMEOUT", "198.51.100.44"),
    "fixture-recovery-readback-failed": (3.5, "PROPOSAL_READY", "198.51.100.45"),
    "fixture-recovery-readback-superseded": (3.5, "PROPOSAL_READY", "198.51.100.46"),
    "fixture-recovery-confirm-auth-failed": (3.5, "PROPOSAL_READY", "198.51.100.47"),
    "fixture-recovery-confirm-transport-failed": (3.5, "PROPOSAL_READY", "198.51.100.48"),
    "fixture-recovery-capacity": (3.5, "PROPOSAL_READY", "198.51.100.49"),
    "fixture-recovery-confirm-config-changed": (3.5, "PROPOSAL_READY", "198.51.100.50"),
    "fixture-recovery-confirm-timeout": (3.5, "PROPOSAL_READY", "198.51.100.51"),
}
for _device_id, (_version, _status, _address) in _RECOVERY_PROFILES.items():
    DEVICES[_device_id] = _device(
        _device_id,
        f"{_device_id} (fixture sintético; não é homologação física)",
        _version,
        "",
    )


@dataclass(frozen=True)
class _Proposal:
    device_id: str
    candidate_ip: str
    expires_at: float


class RecoveryFixture:
    """In-memory deterministic stand-in for the recovery service."""

    def __init__(
        self,
        monotonic: Callable[[], float] = time.monotonic,
        *,
        active_slot: object | None = None,
    ) -> None:
        self._monotonic = monotonic
        self._active_slot = _RECOVERY_ACTIVE_SLOT if active_slot is None else active_slot
        self._lock = threading.RLock()
        self._devices = copy.deepcopy(DEVICES)
        self._next_token = 0
        self._proposals: dict[str, _Proposal] = {}

    def _purge_expired(self, now: float) -> None:
        for token, proposal in tuple(self._proposals.items()):
            if now >= proposal.expires_at:
                del self._proposals[token]

    def catalog(self) -> list[dict[str, object]]:
        with self._lock, LOCK:
            return [json.loads(json.dumps(device)) for device in self._devices.values()]

    def device(self, device_id: str) -> dict[str, object] | None:
        return self._devices.get(device_id)

    def prepare(self, device_id: str) -> dict[str, object]:
        if not isinstance(device_id, str) or not device_id.strip():
            return {"result": {"status": "INVALID_INPUT"}}
        if not self._active_slot.acquire(blocking=False):
            return {"result": {"status": "BUSY"}}
        try:
            profile = _RECOVERY_PROFILES.get(device_id)
            if profile is None:
                return {"result": {"status": "DEVICE_NOT_FOUND"}}
            _protocol, status, address = profile
            if status != "PROPOSAL_READY":
                return {"result": {"status": status}}
            with self._lock:
                now = self._monotonic()
                self._purge_expired(now)
                if any(item.device_id == device_id for item in self._proposals.values()):
                    return {"result": {"status": "BUSY"}}
                if len(self._proposals) >= MAX_PENDING_PROPOSALS:
                    return {"result": {"status": "BUSY"}}
                self._next_token += 1
                raw = hashlib.sha256(f"fixture-proposal-{self._next_token}-{device_id}".encode()).digest()
                token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
                self._proposals[token] = _Proposal(device_id, address, now + TTL_SECONDS)
            return {"result": {"status": "PROPOSAL_READY", "proposalId": token, "candidateIp": address, "ttlSeconds": TTL_SECONDS}}
        finally:
            self._active_slot.release()

    def confirm(self, proposal_id: str) -> dict[str, object]:
        if not self._active_slot.acquire(blocking=False):
            return {"result": {"recovery": {"status": "BUSY"}}}
        try:
            with self._lock:
                self._purge_expired(self._monotonic())
                proposal = self._proposals.pop(proposal_id, None)
                if proposal is None:
                    return {"result": {"recovery": {"status": "PROPOSAL_EXPIRED"}}}
            device_id = proposal.device_id
            confirm_status = {
                "fixture-recovery-confirm-auth-failed": "AUTH_FAILED",
                "fixture-recovery-confirm-transport-failed": "TRANSPORT_FAILED",
                "fixture-recovery-confirm-config-changed": "CONFIG_CHANGED",
                "fixture-recovery-confirm-timeout": "TIMEOUT",
            }.get(device_id)
            if confirm_status:
                return {"result": {"recovery": {"status": confirm_status}}}
            with self._lock, LOCK:
                self._devices[device_id]["address"] = proposal.candidate_ip
            readback_status = {
                "fixture-recovery-readback-failed": "FAILED",
                "fixture-recovery-readback-superseded": "SUPERSEDED",
            }.get(device_id, "SUCCEEDED")
            readback: dict[str, object] = {"status": readback_status}
            if readback_status == "SUCCEEDED":
                with self._lock:
                    readback["device"] = json.loads(json.dumps(self._devices[device_id]))
            return {"result": {"recovery": {"status": "ADOPTED"}, "readback": readback}}
        finally:
            self._active_slot.release()


RECOVERY = RecoveryFixture()
ALLOWED = {"devices.list", "device.get", "device.status", "device.power", "device.whiteBrightness", "device.colorTemperature", "device.hsv", "device.colorBrightness", "recovery.prepare", "recovery.confirm"}
FIELDS = {"devices.list": set(), "device.get": {"deviceId"}, "device.status": {"deviceId"}, "device.power": {"deviceId", "enabled"}, "device.whiteBrightness": {"deviceId", "percent"}, "device.colorTemperature": {"deviceId", "percent"}, "device.colorBrightness": {"deviceId", "percent"}, "device.hsv": {"deviceId", "hue", "saturation", "value"}, "recovery.prepare": {"deviceId"}, "recovery.confirm": {"proposalId"}}


def respond(value: dict[str, object]) -> None:
    line = json.dumps(value, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    with LOCK:
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()


def handle(request: object, recovery: RecoveryFixture = RECOVERY) -> None:
    request_id = request.get("requestId") if isinstance(request, dict) else None
    if not isinstance(request_id, str) or not request_id or len(request_id) > 128 or set(request) != {"requestId", "command", "payload"}:
        respond({"requestId": None, "error": {"code": "INVALID_INPUT", "message": "Request is invalid"}})
        return
    command, payload = request["command"], request["payload"]
    if command not in ALLOWED or not isinstance(payload, dict) or set(payload) != FIELDS[command]:
        respond({"requestId": request_id, "error": {"code": "INVALID_INPUT", "message": "Request is invalid"}})
        return
    if command == "devices.list":
        respond({"requestId": request_id, "result": {"devices": recovery.catalog()}})
        return
    if command == "recovery.prepare":
        device_id = payload["deviceId"]
        if not isinstance(device_id, str) or not device_id.strip():
            respond({"requestId": request_id, "error": {"code": "INVALID_INPUT", "message": "Request is invalid"}})
            return
        result = recovery.prepare(device_id)
        respond({"requestId": request_id, **result})
        return
    if command == "recovery.confirm":
        proposal_id = payload["proposalId"]
        if not isinstance(proposal_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{43}", proposal_id) is None:
            respond({"requestId": request_id, "error": {"code": "INVALID_INPUT", "message": "Request is invalid"}})
            return
        result = recovery.confirm(proposal_id)
        respond({"requestId": request_id, **result})
        return
    device_id = payload.get("deviceId")
    if recovery.device(device_id) is None:
        respond({"requestId": request_id, "error": {"code": "DEVICE_OFFLINE", "message": "Device is unreachable"}})
        return
    with LOCK:
        device = recovery.device(device_id)
        state = device["state"]
        if command == "device.power":
            state["power"] = payload["enabled"]
        elif command == "device.whiteBrightness":
            if not device["capabilities"]["whiteBrightness"]:
                respond({"requestId": request_id, "error": {"code": "UNSUPPORTED_CAPABILITY", "message": "Device does not support this operation"}})
                return
            state["whiteBrightnessPercent"] = payload["percent"]
            state["workMode"] = "white"
        elif command == "device.colorTemperature":
            state["colorTemperaturePercent"] = payload["percent"]
            state["workMode"] = "white"
        elif command in {"device.hsv", "device.colorBrightness"}:
            if not device["capabilities"]["colorValue"]:
                respond({"requestId": request_id, "error": {"code": "UNSUPPORTED_CAPABILITY", "message": "Device does not support this operation"}})
                return
            if command == "device.hsv":
                state["hsv"] = {"hue": payload["hue"], "saturation": payload["saturation"], "value": payload["value"]}
                state["colorValuePercent"] = payload["value"]
            else:
                state["colorValuePercent"] = payload["percent"]
                state["hsv"]["value"] = payload["percent"]
            state["workMode"] = "colour"
        state["quality"] = "confirmed"
        state["knowledge"]["power"] = "observed"
        state["knowledge"]["workMode"] = "observed"
        if "percent" in payload and command == "device.whiteBrightness":
            state["knowledge"]["whiteBrightness"] = "observed"
        if "percent" in payload and command == "device.colorTemperature":
            state["knowledge"]["colorTemperature"] = "observed"
        if command in {"device.hsv", "device.colorBrightness"}:
            state["knowledge"]["hsv"] = state["knowledge"]["colorValue"] = "observed"
        result = json.loads(json.dumps(device))
    respond({"requestId": request_id, "result": result})


def main() -> int:
    threads: list[threading.Thread] = []
    for raw in sys.stdin.buffer:
        if len(raw.rstrip(b"\r\n")) > LIMIT:
            respond({"requestId": None, "error": {"code": "INVALID_INPUT", "message": "Message exceeds 64 KiB"}})
            continue
        try:
            request = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            respond({"requestId": None, "error": {"code": "INVALID_INPUT", "message": "Request is invalid"}})
            continue
        thread = threading.Thread(target=handle, args=(request,), daemon=True)
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
