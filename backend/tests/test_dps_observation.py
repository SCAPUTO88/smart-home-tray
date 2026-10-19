from __future__ import annotations

from smart_home_tray.dps_observation import observe_dps
from smart_home_tray.models import DeviceConfig, DPSMap, ValueRange


def _config() -> DeviceConfig:
    return DeviceConfig(
        device_id="synthetic-device",
        name="synthetic lamp",
        address="10.60.2.10",
        protocol_version=3.5,
        local_key="synthetic-key-123",
        dps=DPSMap(power=20, work_mode=21, white_brightness=22, hsv=23, scene=24),
        white_brightness_range=ValueRange(10, 1000),
    )


def test_observe_dps_uses_device_manager_semantics_without_mutating_input():
    dps = {"20": True, "21": "white", "22": 505, "23": "00b4006403e8", "24": "scene"}

    observed = observe_dps(_config(), dps)

    assert observed.power is True
    assert observed.work_mode == "white"
    assert observed.white_brightness_percent == 50.0
    assert observed.hsv is not None
    assert observed.scene == "scene"
    assert observed.observed == {
        "power", "work_mode", "white_brightness", "hsv", "scene"
    }
    assert dps["20"] is True


def test_observe_dps_ignores_invalid_configured_values_and_unknown_fields():
    observed = observe_dps(_config(), {"20": 1, "21": [], "22": float("inf"), "999": True})

    assert observed.observed == frozenset()

