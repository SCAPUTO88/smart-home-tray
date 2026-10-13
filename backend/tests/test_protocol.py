from __future__ import annotations

import io
import json
import threading
from concurrent.futures import Future

import pytest

from smart_home_tray.models import (
    BackendError, ConnectionStatus, DeviceCapabilities, DeviceStatus,
    DeviceStateQuality, ErrorCode, LightState,
)
from smart_home_tray.protocol import JsonLinesServer


class FakeManager:
    def __init__(self):
        self.catalog_reads = 0
        self.lan_reads = 0

    def list_devices(self):
        self.catalog_reads += 1
        return (status(),)

    def get_device(self, device_id):
        if device_id != "lamp-a":
            raise BackendError(ErrorCode.INVALID_INPUT, "Unknown device ID")
        return status()

    def read_state(self, device_id):
        self.lan_reads += 1
        return status()


def status():
    return DeviceStatus(
        device_id="lamp-a", name="Lamp", address="192.0.2.10", protocol_version=3.5,
        capabilities=DeviceCapabilities(True, True, True, True, True),
        connection=ConnectionStatus.UNKNOWN,
        state=LightState(quality=DeviceStateQuality.UNKNOWN),
    )


class FakeScheduler:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.submissions = []

    def start(self):
        self.started = True

    def stop(self, *, timeout_seconds=10):
        self.stopped = True
        return True

    def submit_power(self, *args):
        return self._submit("power", *args)

    def submit_white_brightness(self, *args):
        return self._submit("white", *args)

    def submit_color_temperature(self, *args):
        return self._submit("temperature", *args)

    def submit_hsv(self, *args):
        return self._submit("hsv", *args)

    def submit_color_brightness(self, *args):
        return self._submit("color_brightness", *args)

    def _submit(self, kind, *args):
        self.submissions.append((kind, args))
        future = Future()
        future.set_result(status())
        return future


def run_lines(lines, manager=None, scheduler=None):
    manager = manager or FakeManager()
    scheduler = scheduler or FakeScheduler()
    output = io.BytesIO()
    errors = io.StringIO()
    server = JsonLinesServer(manager, scheduler)
    server.run(io.BytesIO(lines), output, errors)
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    return responses, manager, scheduler, errors.getvalue()


def test_valid_request_preserves_request_id_and_returns_one_json_line():
    responses, _, _, _ = run_lines(b'{"requestId":"r-1","command":"devices.list","payload":{}}\n')
    assert responses[0]["requestId"] == "r-1"
    assert responses[0]["result"]["devices"][0]["deviceId"] == "lamp-a"


def test_invalid_json_does_not_stop_processing_following_lines():
    responses, _, _, _ = run_lines(
        b'{bad json}\n{"requestId":"r-2","command":"devices.list","payload":{}}\n'
    )
    assert responses[0]["requestId"] is None
    assert responses[0]["error"]["code"] == "INVALID_INPUT"
    assert responses[1]["requestId"] == "r-2"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_json_constants_are_rejected(value):
    token = "NaN" if value != value else ("Infinity" if value > 0 else "-Infinity")
    responses, _, _, _ = run_lines(
        f'{{"requestId":"r-1","command":"device.whiteBrightness","payload":{{"deviceId":"lamp-a","percent":{token}}}}}\n'.encode()
    )
    assert responses[0]["error"]["code"] == "INVALID_INPUT"


def test_list_does_not_access_lan_and_status_does():
    responses, manager, _, _ = run_lines(
        b'{"requestId":"a","command":"devices.list","payload":{}}\n'
        b'{"requestId":"b","command":"device.status","payload":{"deviceId":"lamp-a"}}\n'
    )
    assert len(responses) == 2
    assert manager.catalog_reads == 1
    assert manager.lan_reads == 1


def test_read_only_serve_does_not_start_scheduler_workers():
    _, _, scheduler, _ = run_lines(
        b'{"requestId":"list","command":"devices.list","payload":{}}\n'
    )
    assert not scheduler.started
    assert not scheduler.stopped


def test_write_commands_are_forwarded_to_scheduler():
    responses, _, scheduler, _ = run_lines(
        b'{"requestId":"p","command":"device.power","payload":{"deviceId":"lamp-a","enabled":true}}\n'
        b'{"requestId":"b","command":"device.whiteBrightness","payload":{"deviceId":"lamp-a","percent":45}}\n'
    )
    assert [call[0] for call in scheduler.submissions] == ["power", "white"]
    assert scheduler.started and scheduler.stopped
    assert [response["requestId"] for response in responses] == ["p", "b"]


def test_duplicate_inflight_id_is_rejected_without_consuming_original():
    class BlockedManager(FakeManager):
        def read_state(self, device_id):
            import threading
            self.entered.set()
            self.release.wait(timeout=2)
            return status()

        entered = __import__("threading").Event()
        release = __import__("threading").Event()

    manager = BlockedManager()
    output = io.BytesIO()
    errors = io.StringIO()
    server = JsonLinesServer(manager, FakeScheduler())
    # The status Future remains active while the duplicate line is parsed.
    class Input:
        def __init__(self):
            self.lines = iter([
                b'{"requestId":"same","command":"device.status","payload":{"deviceId":"lamp-a"}}\n',
                b'{"requestId":"same","command":"devices.list","payload":{}}\n',
                b"",
            ])

        def readline(self, size=-1):
            line = next(self.lines)
            if line == b"":
                manager.release.set()
            return line

    server.run(Input(), output, errors)
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert {response.get("requestId") for response in responses} == {"same", None}
    duplicate = next(response for response in responses if response.get("requestId") is None)
    assert duplicate["error"]["code"] == "INVALID_INPUT"


def test_oversized_line_is_drained_and_server_continues():
    oversized = b" " * (64 * 1024 + 10) + b"\n"
    responses, _, _, _ = run_lines(
        oversized + b'{"requestId":"after","command":"devices.list","payload":{}}\n'
    )
    assert responses[0]["requestId"] is None
    assert responses[0]["error"]["code"] == "INVALID_INPUT"
    assert responses[1]["requestId"] == "after"


def test_invalid_id_uses_null_request_id():
    responses, _, _, _ = run_lines(
        b'{"requestId":"","command":"devices.list","payload":{}}\n'
    )
    assert responses[0]["requestId"] is None
    assert responses[0]["error"]["code"] == "INVALID_INPUT"


def test_missing_request_id_is_rejected_without_stopping_server():
    responses, _, _, _ = run_lines(
        b'{"command":"devices.list","payload":{}}\n'
        b'{"requestId":"next","command":"devices.list","payload":{}}\n'
    )
    assert responses[0]["requestId"] is None
    assert responses[0]["error"]["code"] == "INVALID_INPUT"
    assert responses[1]["requestId"] == "next"


def test_credential_and_arbitrary_dps_fields_are_rejected_without_echoing_values():
    secret = "sample-secret-not-real"
    line = json.dumps({
        "requestId": "secret-test", "command": "device.power",
        "payload": {"deviceId": "lamp-a", "enabled": True, "localKey": secret},
    }).encode() + b"\n"
    responses, _, _, errors = run_lines(line)
    assert responses[0]["error"]["code"] == "INVALID_INPUT"
    assert secret not in json.dumps(responses) + errors


def test_public_status_is_allowlisted_and_never_contains_private_config():
    responses, _, _, _ = run_lines(
        b'{"requestId":"public","command":"device.get","payload":{"deviceId":"lamp-a"}}\n'
    )
    assert set(responses[0]["result"]) == {
        "deviceId", "name", "address", "protocolVersion", "capabilities", "connection", "state"
    }


def test_status_responses_can_complete_out_of_request_order():
    class Manager(FakeManager):
        first_entered = threading.Event()
        release_first = threading.Event()
        second_done = threading.Event()

        def read_state(self, device_id):
            if device_id == "first":
                self.first_entered.set()
                assert self.release_first.wait(timeout=2)
            else:
                self.second_done.set()
            return status()

    manager = Manager()
    output, errors = io.BytesIO(), io.StringIO()
    server = JsonLinesServer(manager, FakeScheduler())

    class Input:
        lines = iter([
            b'{"requestId":"one","command":"device.status","payload":{"deviceId":"first"}}\n',
            b'{"requestId":"two","command":"device.status","payload":{"deviceId":"second"}}\n',
            b"",
        ])

        def readline(self, size=-1):
            line = next(self.lines)
            if line == b"":
                assert manager.second_done.wait(timeout=2)
                manager.release_first.set()
            return line

    server.run(Input(), output, errors)
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [response["requestId"] for response in responses] == ["two", "one"]


def test_shutdown_cancels_queued_command_with_terminal_error_response():
    class Scheduler(FakeScheduler):
        def _submit(self, kind, *args):
            self.submissions.append((kind, args))
            self.pending = Future()
            return self.pending

        def stop(self, *, timeout_seconds=10):
            self.stopped = True
            self.pending.cancel()
            return True

    scheduler = Scheduler()
    responses, _, _, _ = run_lines(
        b'{"requestId":"cancel-me","command":"device.power","payload":{"deviceId":"lamp-a","enabled":true}}\n',
        scheduler=scheduler,
    )
    assert responses[0]["requestId"] == "cancel-me"
    assert responses[0]["error"]["code"] == "COMMAND_CANCELED"


@pytest.mark.parametrize(
    "command,payload",
    [
        ("device.power", {"deviceId": "lamp-a", "enabled": 1}),
        ("device.whiteBrightness", {"deviceId": "lamp-a", "percent": True}),
        ("device.whiteBrightness", {"deviceId": "lamp-a", "percent": 101}),
        ("device.hsv", {"deviceId": "lamp-a", "hue": 361, "saturation": 10, "value": 10}),
        ("device.power", {"deviceId": "lamp-a", "enabled": True, "dps": {"20": True}}),
    ],
)
def test_invalid_values_and_unapproved_payload_fields_are_rejected(command, payload):
    line = json.dumps({"requestId": "invalid", "command": command, "payload": payload}).encode() + b"\n"
    responses, _, scheduler, _ = run_lines(line)
    assert responses[0]["error"]["code"] == "INVALID_INPUT"
    assert scheduler.submissions == []


def test_backend_errors_are_safe_and_unexpected_errors_have_no_traceback():
    class Scheduler(FakeScheduler):
        def submit_power(self, *args):
            raise BackendError(ErrorCode.UNSUPPORTED_CAPABILITY, "private sample-secret-not-real")

    responses, _, _, errors = run_lines(
        b'{"requestId":"failed","command":"device.power","payload":{"deviceId":"lamp-a","enabled":true}}\n',
        scheduler=Scheduler(),
    )
    assert responses[0]["error"]["code"] == "UNSUPPORTED_CAPABILITY"
    assert "sample-secret" not in json.dumps(responses) + errors
    assert "traceback" not in errors.lower()


def test_unexpected_manager_error_is_generic_and_does_not_leak_to_stdout_or_stderr():
    class Manager(FakeManager):
        def list_devices(self):
            raise RuntimeError("private sample-secret-not-real")

    responses, _, _, errors = run_lines(
        b'{"requestId":"unexpected","command":"devices.list","payload":{}}\n',
        manager=Manager(),
    )
    assert responses[0]["error"]["code"] == "DEVICE_ERROR"
    assert "sample-secret" not in json.dumps(responses) + errors
    assert "traceback" not in errors.lower()


def test_dependency_stdout_prints_cannot_contaminate_ipc_or_diagnostics(capsys):
    class NoisyManager(FakeManager):
        def list_devices(self):
            print("private sample-secret-not-real")
            return super().list_devices()

    responses, _, _, errors = run_lines(
        b'{"requestId":"quiet","command":"devices.list","payload":{}}\n',
        manager=NoisyManager(),
    )
    assert responses[0]["requestId"] == "quiet"
    assert "sample-secret" not in json.dumps(responses) + errors + capsys.readouterr().out


def test_deeply_nested_json_is_rejected_without_terminating_server():
    too_deep = b"[" * 3000 + b"]" * 3000 + b"\n"
    responses, _, _, _ = run_lines(
        too_deep + b'{"requestId":"after-depth","command":"devices.list","payload":{}}\n'
    )
    assert responses[0]["requestId"] is None
    assert responses[0]["error"]["code"] == "INVALID_INPUT"
    assert responses[1]["requestId"] == "after-depth"


def test_request_id_over_128_characters_is_rejected_with_null_id():
    request_id = "x" * 129
    responses, _, _, _ = run_lines(
        json.dumps({"requestId": request_id, "command": "devices.list", "payload": {}}).encode() + b"\n"
    )
    assert responses[0]["requestId"] is None
    assert responses[0]["error"]["code"] == "INVALID_INPUT"
