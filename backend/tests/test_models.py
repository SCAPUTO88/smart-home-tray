import pytest

from smart_home_tray.models import (
    BackendError,
    DeviceConfig,
    DeviceStateQuality,
    DPSMap,
    ErrorCode,
    HSVColor,
    ValueRange,
)


def test_device_capabilities_are_derived_from_its_dps_map():
    device = DeviceConfig(
        device_id="unit-test-device",
        name="Test light",
        address="192.0.2.10",
        protocol_version=3.5,
        local_key="unit-test-key-not-real",
        dps=DPSMap(power=20, white_brightness=22, hsv=24),
        white_brightness_range=ValueRange(10, 1000),
    )

    assert device.capabilities.power is True
    assert device.capabilities.white_brightness is True
    assert device.capabilities.color_value is True
    assert device.capabilities.color_temperature is False
    assert device.capabilities.scenes is False


def test_value_range_converts_raw_and_percent_values():
    value_range = ValueRange(10, 1000)

    assert value_range.to_percent(10) == 0
    assert value_range.to_percent(505) == 50
    assert value_range.to_percent(1000) == 100
    assert value_range.from_percent(0) == 10
    assert value_range.from_percent(50) == 505
    assert value_range.from_percent(100) == 1000


def test_value_range_rejects_percent_outside_interface_range():
    with pytest.raises(ValueError):
        ValueRange(0, 1000).from_percent(101)


def test_device_config_requires_ranges_for_mapped_normalized_controls():
    with pytest.raises(ValueError, match="white_brightness_range"):
        DeviceConfig(
            device_id="unit-test-device",
            name="Test light",
            address="192.0.2.10",
            protocol_version=3.5,
            local_key="unit-test-key-not-real",
            dps=DPSMap(white_brightness=22),
        )


@pytest.mark.parametrize("timeout", [float("nan"), float("inf")])
def test_device_config_rejects_non_finite_connection_timeout(timeout):
    with pytest.raises(ValueError, match="finite"):
        DeviceConfig(
            device_id="unit-test-device",
            name="Test light",
            address="192.0.2.10",
            protocol_version=3.5,
            local_key="unit-test-key-not-real",
            connection_timeout_seconds=timeout,
        )


def test_device_config_repr_does_not_include_local_key():
    device = DeviceConfig(
        device_id="unit-test-device",
        name="Test light",
        address="192.0.2.10",
        protocol_version=3.5,
        local_key="unit-test-key-not-real",
        dps=DPSMap(power=20),
    )

    assert "unit-test-key-not-real" not in repr(device)


def test_hsv_color_checks_component_bounds():
    assert HSVColor(hue=180, saturation=50, value=75).value == 75
    with pytest.raises(ValueError):
        HSVColor(hue=361, saturation=50, value=75)


def test_backend_error_keeps_code_and_safe_message():
    error = BackendError(ErrorCode.TIMEOUT, "Device did not respond")

    assert error.code is ErrorCode.TIMEOUT
    assert str(error) == "Device did not respond"
    assert DeviceStateQuality.CONFIRMED.value == "confirmed"
