"""Safe JSON Lines request/response transport for the local sidecar."""

from __future__ import annotations

import contextlib
import json
import queue
import re
import threading
import time
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import BinaryIO, Callable, TextIO

from smart_home_tray.models import (
    BackendError,
    DeviceStatus,
    ErrorCode,
    device_status_to_public_dict,
)

MAX_MESSAGE_BYTES = 64 * 1024
MAX_REQUEST_ID_LENGTH = 128
_STATUS_WORKERS = 8
_WRITER_STOP = object()
_ERRORS = {
    ErrorCode.TIMEOUT: "Device request timed out",
    ErrorCode.DEVICE_OFFLINE: "Device is unreachable",
    ErrorCode.AUTH_FAILED: "Device authentication failed",
    ErrorCode.INVALID_INPUT: "Request is invalid",
    ErrorCode.UNSUPPORTED_CAPABILITY: "Device does not support this operation",
    ErrorCode.DEVICE_ERROR: "Device operation failed",
    ErrorCode.COMMAND_CANCELED: "Command was canceled before completion",
}


@dataclass(frozen=True)
class _ResponseEvent:
    response: dict[str, object]
    request_id: str | None
    tracked: bool


class _DiscardingStdout:
    """Suppress accidental Python prints so they cannot corrupt or leak into IPC."""

    encoding = "utf-8"

    def write(self, value: str) -> int:
        return len(value)

    def flush(self) -> None:
        return None


class JsonLinesServer:
    """Read requests continuously and publish terminal responses on one writer."""

    def __init__(
        self,
        device_manager: object,
        command_scheduler: object,
        recovery_service: object | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(monotonic):
            raise TypeError("monotonic clock must be callable")
        self._manager = device_manager
        self._scheduler = command_scheduler
        self._monotonic = monotonic
        if recovery_service is None:
            from smart_home_tray.lan_discovery import TinyTuyaLanDiscoveryProvider
            from smart_home_tray.recovery import DeviceManagerRecoveryCatalog, RecoveryService

            recovery_service = RecoveryService(
                catalog=DeviceManagerRecoveryCatalog(device_manager),
                provider=TinyTuyaLanDiscoveryProvider(),
            )
        self._recovery = recovery_service
        self._events: queue.Queue[object] = queue.Queue()
        self._condition = threading.Condition()
        self._active_ids: set[str] = set()
        self._pending_responses = 0
        self._scheduler_started = False

    def run(
        self,
        input_stream: BinaryIO,
        output_stream: BinaryIO,
        error_stream: TextIO,
    ) -> None:
        """Serve until EOF; active LAN calls finish, queued scheduler work cancels."""
        # Third-party print/debug output is suppressed, never mixed into JSONL or
        # copied verbatim to diagnostics where private adapter data might appear.
        with contextlib.redirect_stdout(_DiscardingStdout()):
            self._serve(input_stream, output_stream, error_stream)

    def _serve(
        self,
        input_stream: BinaryIO,
        output_stream: BinaryIO,
        error_stream: TextIO,
    ) -> None:
        writer = threading.Thread(
            target=self._writer, args=(output_stream,), name="smart-home-tray-ipc-writer", daemon=False
        )
        writer.start()
        executor = ThreadPoolExecutor(max_workers=_STATUS_WORKERS, thread_name_prefix="tray-status")
        try:
            self._scheduler_started = False
            while True:
                raw_line, too_long = self._read_line(input_stream)
                if raw_line is None:
                    break
                if too_long:
                    self._emit_error(None, ErrorCode.INVALID_INPUT, "Message exceeds 64 KiB")
                    continue
                self._accept_line(raw_line, executor, error_stream)
        finally:
            # Closing cancels not-yet-started recovery stages and retracts only
            # proposals owned by this serve instance. Active work is then drained.
            try:
                self._recovery.close(timeout_seconds=0.0)
            except Exception:
                pass
            # Repeated bounded waits permit an already-started LAN operation to finish.
            if self._scheduler_started:
                while not self._scheduler.stop(timeout_seconds=10.0):
                    pass
            # Accepted catalog/status reads must finish, even if they were queued
            # behind another read when stdin reached EOF.
            executor.shutdown(wait=True, cancel_futures=False)
            with self._condition:
                self._condition.wait_for(lambda: self._pending_responses == 0)
            self._events.put(_WRITER_STOP)
            writer.join()

    @staticmethod
    def _read_line(stream: BinaryIO) -> tuple[bytes | None, bool]:
        """Read no more than the limit plus framing, draining oversized lines."""
        first = stream.readline(MAX_MESSAGE_BYTES + 2)
        if not first:
            return None, False
        if first.endswith(b"\n"):
            content = first[:-1]
            if content.endswith(b"\r"):
                content = content[:-1]
            return content, len(content) > MAX_MESSAGE_BYTES
        if len(first) <= MAX_MESSAGE_BYTES:
            return first, False
        while True:
            chunk = stream.readline(8192)
            if not chunk or chunk.endswith(b"\n"):
                break
        return b"", True

    def _accept_line(self, raw_line: bytes, executor: ThreadPoolExecutor, error_stream: TextIO) -> None:
        try:
            text = raw_line.decode("utf-8", errors="strict")
            request = json.loads(text, parse_constant=self._reject_constant)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            self._emit_error(None, ErrorCode.INVALID_INPUT, "Request is not valid JSON")
            return
        if not isinstance(request, dict):
            self._emit_error(None, ErrorCode.INVALID_INPUT, "Request fields are invalid")
            return
        request_id = request.get("requestId")
        if (
            not isinstance(request_id, str)
            or not request_id.strip()
            or len(request_id) > MAX_REQUEST_ID_LENGTH
        ):
            self._emit_error(None, ErrorCode.INVALID_INPUT, "requestId is invalid")
            return
        with self._condition:
            if request_id in self._active_ids:
                self._queue_response({
                    "requestId": None,
                    "error": {"code": ErrorCode.INVALID_INPUT.value, "message": "requestId is already in use"},
                }, tracked=False)
                return
            self._active_ids.add(request_id)
            self._pending_responses += 1

        if set(request) != {"requestId", "command", "payload"}:
            self._emit_accepted_error(request_id, ErrorCode.INVALID_INPUT, "Request fields are invalid")
            return

        command, payload = request["command"], request["payload"]
        if not isinstance(command, str) or not isinstance(payload, dict):
            self._emit_accepted_error(request_id, ErrorCode.INVALID_INPUT, "Command or payload is invalid")
            return
        try:
            self._dispatch(request_id, command, payload, executor)
        except BackendError as error:
            self._emit_accepted_error(request_id, error.code, error.message)
        except Exception:
            # Keep stderr useful without echoing exception strings or tracebacks.
            try:
                error_stream.write("Unexpected JSON Lines request failure\n")
                error_stream.flush()
            except Exception:
                pass
            self._emit_accepted_error(request_id, ErrorCode.DEVICE_ERROR, "Request could not be completed")

    @staticmethod
    def _reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    def _dispatch(self, request_id: str, command: str, payload: dict[str, object], executor: ThreadPoolExecutor) -> None:
        schemas: dict[str, set[str]] = {
            "devices.list": set(),
            "device.get": {"deviceId"},
            "device.status": {"deviceId"},
            "device.power": {"deviceId", "enabled"},
            "device.whiteBrightness": {"deviceId", "percent"},
            "device.colorTemperature": {"deviceId", "percent"},
            "device.hsv": {"deviceId", "hue", "saturation", "value"},
            "device.colorBrightness": {"deviceId", "percent"},
            "recovery.prepare": {"deviceId"},
            "recovery.confirm": {"proposalId"},
        }
        if command not in schemas:
            raise BackendError(ErrorCode.INVALID_INPUT, "Unknown command")
        if set(payload) != schemas[command]:
            raise BackendError(ErrorCode.INVALID_INPUT, "Payload fields are invalid")
        if command == "devices.list":
            future = executor.submit(self._manager.list_devices)
            self._attach_future(request_id, future, self._public_devices)
            return

        if command == "recovery.prepare":
            device_id = payload["deviceId"]
            if not isinstance(device_id, str) or not device_id.strip():
                raise BackendError(ErrorCode.INVALID_INPUT, "deviceId is invalid")
            self._ensure_scheduler_started()
            future = executor.submit(self._recovery.prepare_internal, device_id, self._scheduler)
            self._attach_future(
                request_id,
                future,
                lambda outcome: self._public_preparation(outcome, monotonic=self._monotonic),
            )
            return

        if command == "recovery.confirm":
            proposal_id = payload["proposalId"]
            if not isinstance(proposal_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{43}", proposal_id) is None:
                raise BackendError(ErrorCode.INVALID_INPUT, "proposalId is invalid")
            self._ensure_scheduler_started()
            future = executor.submit(self._recovery.confirm_internal, proposal_id, self._scheduler)
            self._attach_future(request_id, future, self._public_confirmation)
            return

        device_id = payload["deviceId"]
        if not isinstance(device_id, str) or not device_id.strip():
            raise BackendError(ErrorCode.INVALID_INPUT, "deviceId is invalid")
        if command == "device.get":
            future = executor.submit(self._manager.get_device, device_id)
            self._attach_future(request_id, future, self._public_status)
            return
        if command == "device.status":
            future = executor.submit(self._manager.read_state, device_id)
            self._attach_future(request_id, future, self._public_status)
            return

        if command == "device.power":
            value = payload["enabled"]
            if not isinstance(value, bool):
                raise BackendError(ErrorCode.INVALID_INPUT, "enabled must be a boolean")
            self._ensure_scheduler_started()
            future = self._scheduler.submit_power(device_id, value)
        elif command in {"device.whiteBrightness", "device.colorTemperature", "device.colorBrightness"}:
            value = self._finite_number(payload["percent"], "percent")
            if not 0 <= value <= 100:
                raise BackendError(ErrorCode.INVALID_INPUT, "percent must be between 0 and 100")
            method = {
                "device.whiteBrightness": self._scheduler.submit_white_brightness,
                "device.colorTemperature": self._scheduler.submit_color_temperature,
                "device.colorBrightness": self._scheduler.submit_color_brightness,
            }[command]
            self._ensure_scheduler_started()
            future = method(device_id, value)
        else:
            hue = self._finite_number(payload["hue"], "hue")
            saturation = self._finite_number(payload["saturation"], "saturation")
            value = self._finite_number(payload["value"], "value")
            if not 0 <= hue <= 360 or not 0 <= saturation <= 100 or not 0 <= value <= 100:
                raise BackendError(ErrorCode.INVALID_INPUT, "HSV values are outside their valid ranges")
            self._ensure_scheduler_started()
            future = self._scheduler.submit_hsv(device_id, hue, saturation, value)
        self._attach_future(request_id, future, self._public_status)

    def _ensure_scheduler_started(self) -> None:
        if self._scheduler_started:
            return
        # Mark first so partial worker startup is still cleaned up in finally.
        self._scheduler_started = True
        self._scheduler.start()

    @staticmethod
    def _finite_number(value: object, name: str) -> float:
        import math

        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise BackendError(ErrorCode.INVALID_INPUT, f"{name} must be a finite number")
        return float(value)

    @staticmethod
    def _public_status(status: object) -> dict[str, object]:
        if not isinstance(status, DeviceStatus):
            raise BackendError(ErrorCode.DEVICE_ERROR, "Device returned an invalid status")
        return device_status_to_public_dict(status)

    @classmethod
    def _public_devices(cls, statuses: object) -> dict[str, object]:
        if not isinstance(statuses, (tuple, list)):
            raise BackendError(ErrorCode.DEVICE_ERROR, "Device catalog returned an invalid result")
        return {"devices": [cls._public_status(status) for status in statuses]}

    @staticmethod
    def _public_preparation(
        outcome: object, *, monotonic: Callable[[], float] = time.monotonic
    ) -> dict[str, object]:
        from smart_home_tray.recovery import PreparationStatus

        if not hasattr(outcome, "status"):
            raise BackendError(ErrorCode.DEVICE_ERROR, "Recovery returned an invalid result")
        status = outcome.status
        validation = getattr(outcome, "validation_status", None)
        if status is PreparationStatus.PROPOSAL_READY_INTERNAL:
            proposal = outcome.proposal
            return {
                "status": "PROPOSAL_READY",
                "proposalId": proposal.token,
                "candidateIp": str(proposal.candidate_address),
                "ttlSeconds": round(max(0.0, proposal.expires_at - monotonic()), 3),
            }
        if status is PreparationStatus.VALIDATION_FAILED:
            public = {
                "auth_failed": "AUTH_FAILED",
                "transport_failed": "TRANSPORT_FAILED",
                "timeout": "TIMEOUT",
            }.get(validation, "VALIDATION_FAILED")
        else:
            public = {
                PreparationStatus.NOT_FOUND: "NOT_FOUND",
                PreparationStatus.AMBIGUOUS: "AMBIGUOUS",
                PreparationStatus.TIMEOUT: "TIMEOUT",
                PreparationStatus.DISCOVERY_FAILED: "TRANSPORT_FAILED",
                PreparationStatus.CATALOG_FAILED: "VALIDATION_FAILED",
                PreparationStatus.DEVICE_NOT_FOUND: "DEVICE_NOT_FOUND",
                PreparationStatus.PROTOCOL_NOT_ELIGIBLE: "PROTOCOL_NOT_ELIGIBLE",
                PreparationStatus.BUSY: "BUSY",
                PreparationStatus.INVALID_REQUEST: "INVALID_INPUT",
                PreparationStatus.CONFIG_CHANGED: "CONFIG_CHANGED",
                PreparationStatus.CLOSED: "SHUTDOWN",
                PreparationStatus.PROPOSAL_CAPACITY: "BUSY",
                PreparationStatus.PROPOSAL_PENDING: "BUSY",
                PreparationStatus.TOKEN_COLLISION: "VALIDATION_FAILED",
                PreparationStatus.INTERNAL_ERROR: "VALIDATION_FAILED",
            }.get(status, "VALIDATION_FAILED")
        return {"status": public}

    @classmethod
    def _public_confirmation(cls, outcome: object) -> dict[str, object]:
        from smart_home_tray.recovery import ConfirmationStatus

        if not hasattr(outcome, "status"):
            raise BackendError(ErrorCode.DEVICE_ERROR, "Recovery returned an invalid result")
        if outcome.status is not ConfirmationStatus.ADOPTED:
            validation = getattr(outcome, "validation_status", None)
            public = {
                ConfirmationStatus.PROPOSAL_UNAVAILABLE: "PROPOSAL_EXPIRED",
                ConfirmationStatus.PROPOSAL_EXPIRED: "PROPOSAL_EXPIRED",
                ConfirmationStatus.BUSY: "BUSY",
                ConfirmationStatus.INVALID_REQUEST: "INVALID_INPUT",
                ConfirmationStatus.TIMEOUT: "TIMEOUT",
                ConfirmationStatus.CLOSED: "SHUTDOWN",
                ConfirmationStatus.CONFIG_CHANGED: "CONFIG_CHANGED",
                ConfirmationStatus.PROTOCOL_NOT_ELIGIBLE: "PROTOCOL_NOT_ELIGIBLE",
                ConfirmationStatus.AUTH_FAILED: "AUTH_FAILED",
                ConfirmationStatus.VALIDATION_FAILED: "VALIDATION_FAILED",
                ConfirmationStatus.CLEANUP_FAILED: "VALIDATION_FAILED",
                ConfirmationStatus.INTERNAL_ERROR: "VALIDATION_FAILED",
            }.get(outcome.status, "VALIDATION_FAILED")
            if validation == "transport_failed":
                public = "TRANSPORT_FAILED"
            elif validation == "timeout":
                public = "TIMEOUT"
            return {"recovery": {"status": public}}
        readback_status = {
            "succeeded": "SUCCEEDED",
            "failed": "FAILED",
            "superseded": "SUPERSEDED",
        }.get(getattr(outcome.readback_status, "value", ""), "FAILED")
        readback: dict[str, object] = {"status": readback_status}
        if readback_status == "SUCCEEDED" and outcome.readback is not None:
            readback["device"] = cls._public_status(outcome.readback)
        return {"recovery": {"status": "ADOPTED"}, "readback": readback}

    def _attach_future(
        self,
        request_id: str,
        future: Future[object],
        result_mapper: Callable[[object], object],
    ) -> None:
        # Future callbacks may run on a scheduler worker; only enqueue a tiny event.
        future.add_done_callback(
            lambda completed: self._events.put((request_id, completed, result_mapper))
        )

    def _emit_result(self, request_id: str, result: object) -> None:
        self._queue_response({"requestId": request_id, "result": result})

    def _emit_accepted_error(self, request_id: str, code: ErrorCode, message: str) -> None:
        # BackendError messages are internal; only publish the stable safe mapping.
        safe_message = _ERRORS.get(code, "Request could not be completed")
        self._queue_response({
            "requestId": request_id,
            "error": {"code": code.value, "message": safe_message},
        })

    def _emit_error(self, request_id: None, code: ErrorCode, message: str) -> None:
        self._queue_response({"requestId": request_id, "error": {"code": code.value, "message": message}}, tracked=False)

    def _queue_response(self, response: dict[str, object], *, tracked: bool = True) -> None:
        request_id = response.get("requestId")
        self._events.put(_ResponseEvent(
            response=response,
            request_id=request_id if isinstance(request_id, str) else None,
            tracked=tracked,
        ))

    def _writer(self, stream: BinaryIO) -> None:
        while True:
            event = self._events.get()
            if event is _WRITER_STOP:
                return
            if isinstance(event, _ResponseEvent):
                response, tracked, request_id = event.response, event.tracked, event.request_id
            else:
                request_id, future, result_mapper = event
                try:
                    result = result_mapper(future.result())
                    response = {"requestId": request_id, "result": result}
                except CancelledError:
                    response = {"requestId": request_id, "error": {
                        "code": ErrorCode.COMMAND_CANCELED.value,
                        "message": _ERRORS[ErrorCode.COMMAND_CANCELED],
                    }}
                except BackendError as error:
                    response = {"requestId": request_id, "error": {
                        "code": error.code.value,
                        "message": _ERRORS.get(error.code, "Request could not be completed"),
                    }}
                except Exception:
                    response = {"requestId": request_id, "error": {
                        "code": ErrorCode.DEVICE_ERROR.value, "message": "Request could not be completed",
                    }}
                tracked = True
            try:
                encoded = json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                stream.write((encoded + "\n").encode("utf-8"))
                stream.flush()
            except Exception:
                # The pipe may close when the host exits; do not expose diagnostics on stdout.
                pass
            finally:
                if tracked:
                    with self._condition:
                        if request_id is not None:
                            self._active_ids.discard(request_id)
                        self._pending_responses -= 1
                        self._condition.notify_all()
