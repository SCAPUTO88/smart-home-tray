import socket

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

    adapter.write_dps(24, "00006400c800")

    assert fake.writes == [(24, "00006400c800")]


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
