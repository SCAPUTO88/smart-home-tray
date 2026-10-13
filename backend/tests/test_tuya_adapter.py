import socket
import traceback

import pytest

from smart_home_tray.models import BackendError, DeviceConfig, DPSMap, ErrorCode
from smart_home_tray.tuya_adapter import TuyaAdapter


def make_config():
    return DeviceConfig(
        device_id="test-device",
        name="Test light",
        address="192.0.2.10",
        protocol_version=3.5,
        local_key="unit-test-key-not-real",
        dps=DPSMap(power=20, hsv=24),
        connection_timeout_seconds=2,
    )


class FakeTuyaDevice:
    def __init__(self, status_result=None, write_result=None, status_error=None):
        self.status_result = status_result
        self.write_result = write_result
        self.status_error = status_error
        self.writes = []

    def status(self):
        if self.status_error:
            raise self.status_error
        return self.status_result

    def set_value(self, dps_index, value):
        self.writes.append((dps_index, value))
        return self.write_result


def test_adapter_constructs_tinytuya_device_with_bounded_connection_settings():
    config = make_config()
    fake = FakeTuyaDevice(status_result={"dps": {"20": True}})
    received = {}

    def factory(**kwargs):
        received.update(kwargs)
        return fake

    adapter = TuyaAdapter(config, device_factory=factory)

    assert adapter.read_status() == {"20": True}
    assert received["dev_id"] == config.device_id
    assert received["address"] == config.address
    assert received["version"] == config.protocol_version
    assert received["connection_timeout"] == 2
    assert received["connection_retry_limit"] == 1
    assert received["persist"] is False
    assert received["local_key"] == config.local_key


def test_adapter_writes_one_dps_through_tinytuya():
    fake = FakeTuyaDevice(write_result={"dps": {"20": True}})
    adapter = TuyaAdapter(make_config(), device_factory=lambda **_: fake)

    result = adapter.write_dps(24, "00006400c800")

    assert result is None
    assert fake.writes == [(24, "00006400c800")]


def test_adapter_accepts_tinytuya_null_ack_without_claiming_state_confirmation():
    fake = FakeTuyaDevice(write_result=None)
    adapter = TuyaAdapter(make_config(), device_factory=lambda **_: fake)

    result = adapter.write_dps(20, True)

    assert result is None
    assert fake.writes == [(20, True)]


@pytest.mark.parametrize(
    "response",
    [{}, {"dps": {}}, {"success": True}, "", []],
)
def test_adapter_rejects_empty_or_unexpected_write_responses(response):
    fake = FakeTuyaDevice(write_result=response)
    adapter = TuyaAdapter(make_config(), device_factory=lambda **_: fake)

    with pytest.raises(BackendError) as error:
        adapter.write_dps(20, True)

    assert error.value.code is ErrorCode.DEVICE_ERROR


def test_adapter_maps_timeout_exception_to_standard_error():
    fake = FakeTuyaDevice(status_error=socket.timeout())
    adapter = TuyaAdapter(make_config(), device_factory=lambda **_: fake)

    with pytest.raises(BackendError) as error:
        adapter.read_status()

    assert error.value.code is ErrorCode.TIMEOUT


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"Err": "905", "Error": "offline"}, ErrorCode.DEVICE_OFFLINE),
        ({"Err": "914", "Error": "bad key"}, ErrorCode.AUTH_FAILED),
        ({"Err": "902", "Error": "timeout"}, ErrorCode.TIMEOUT),
    ],
)
def test_adapter_maps_tinytuya_errors_without_forwarding_raw_message(response, expected):
    fake = FakeTuyaDevice(status_result=response)
    adapter = TuyaAdapter(make_config(), device_factory=lambda **_: fake)

    with pytest.raises(BackendError) as error:
        adapter.read_status()

    assert error.value.code is expected
    assert "bad key" not in str(error.value)


@pytest.mark.parametrize(
    ("tuya_code", "expected_code", "safe_message"),
    [
        ("903", ErrorCode.INVALID_INPUT, "outside the supported range"),
        ("904", ErrorCode.DEVICE_ERROR, "unexpected payload"),
        ("907", ErrorCode.UNSUPPORTED_CAPABILITY, "does not support"),
        ("914", ErrorCode.AUTH_FAILED, "authentication parameters"),
        ("777", ErrorCode.DEVICE_ERROR, "Tuya device returned an error"),
    ],
)
def test_adapter_maps_documented_tinytuya_write_errors_safely(
    tuya_code, expected_code, safe_message
):
    fake = FakeTuyaDevice(write_result={"Err": tuya_code, "Error": "private raw diagnostic"})
    adapter = TuyaAdapter(make_config(), device_factory=lambda **_: fake)

    with pytest.raises(BackendError) as error:
        adapter.write_dps(20, True)

    assert error.value.code is expected_code
    assert safe_message in str(error.value)
    assert "private raw diagnostic" not in str(error.value)


def test_adapter_does_not_expose_exception_text_or_chain_from_transport():
    fake = FakeTuyaDevice(status_error=RuntimeError("unit-test-key-not-real"))
    adapter = TuyaAdapter(make_config(), device_factory=lambda **_: fake)

    with pytest.raises(BackendError) as error:
        adapter.read_status()

    assert "unit-test-key-not-real" not in str(error.value)
    assert error.value.__suppress_context__ is True


def test_adapter_rejects_unexpected_status_shape():
    fake = FakeTuyaDevice(status_result={"unexpected": True})
    adapter = TuyaAdapter(make_config(), device_factory=lambda **_: fake)

    with pytest.raises(BackendError) as error:
        adapter.read_status()

    assert error.value.code is ErrorCode.DEVICE_ERROR


def test_adapter_maps_tinytuya_write_error():
    fake = FakeTuyaDevice(write_result={"Err": "905", "Error": "offline"})
    adapter = TuyaAdapter(make_config(), device_factory=lambda **_: fake)

    with pytest.raises(BackendError) as error:
        adapter.write_dps(20, True)

    assert error.value.code is ErrorCode.DEVICE_OFFLINE


@pytest.mark.parametrize(
    ("initialization_error", "expected_code"),
    [
        (socket.timeout("unit-test-key-not-real"), ErrorCode.TIMEOUT),
        (OSError("unit-test-key-not-real"), ErrorCode.DEVICE_OFFLINE),
        (RuntimeError("unit-test-key-not-real"), ErrorCode.DEVICE_ERROR),
    ],
)
def test_adapter_normalizes_factory_initialization_errors_safely(
    initialization_error, expected_code
):
    def failing_factory(**_kwargs):
        raise initialization_error

    with pytest.raises(BackendError) as error:
        TuyaAdapter(make_config(), device_factory=failing_factory)

    assert error.value.code is expected_code
    assert "unit-test-key-not-real" not in str(error.value)
    assert error.value.__suppress_context__ is True


def test_adapter_preserves_structured_factory_error():
    structured_error = BackendError(ErrorCode.AUTH_FAILED, "safe authentication error")
    structured_error.__cause__ = RuntimeError("unit-test-key-not-real")

    def failing_factory(**_kwargs):
        raise structured_error

    with pytest.raises(BackendError) as error:
        TuyaAdapter(make_config(), device_factory=failing_factory)

    assert error.value is structured_error
    rendered = "".join(traceback.format_exception(error.value))
    assert "unit-test-key-not-real" not in rendered
