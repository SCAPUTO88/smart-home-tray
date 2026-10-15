from __future__ import annotations

import math
import threading

import pytest

from smart_home_tray.config import AppConfig
from smart_home_tray.device_manager import DeviceManager
from smart_home_tray.models import (
    BackendError,
    ConnectionStatus,
    DeviceConfig,
    DeviceStateQuality,
    DPSMap,
    ErrorCode,
    FieldKnowledge,
    HSVColor,
    ValueRange,
)


def make_device(device_id: str, address: str, *, power_dps: int | None = 20) -> DeviceConfig:
    return DeviceConfig(
        device_id=device_id,
        name=f"Light {device_id}",
        address=address,
        protocol_version=3.5,
        local_key="unit-test-key-not-real",
        dps=DPSMap(power=power_dps, work_mode=21),
    )


def make_color_device(
    device_id: str,
    address: str,
    *,
    white: bool = True,
    color: bool = True,
) -> DeviceConfig:
    return DeviceConfig(
        device_id=device_id,
        name=f"Light {device_id}",
        address=address,
        protocol_version=3.5,
        local_key="unit-test-key-not-real",
        dps=DPSMap(
            power=20,
            work_mode=21,
            white_brightness=22 if white else None,
            white_temperature=23 if white else None,
            hsv=24 if color else None,
            scene=25,
        ),
        white_brightness_range=ValueRange(10, 1000) if white else None,
        white_temperature_range=ValueRange(0, 1000) if white else None,
    )


class FakeAdapter:
    def __init__(self, statuses=None, write_error=None, write_errors=None, on_status=None, on_write=None):
        self.statuses = list(statuses or [])
        self.write_error = write_error
        self.write_errors = list(write_errors or [])
        self.on_status = on_status
        self.on_write = on_write
        self.writes = []

    def read_status(self):
        if self.on_status:
            self.on_status()
        if not self.statuses:
            raise BackendError(ErrorCode.DEVICE_OFFLINE, "Device is unreachable")
        result = self.statuses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def write_dps(self, index, value):
        if self.on_write:
            self.on_write()
        self.writes.append((index, value))
        if self.write_errors:
            error = self.write_errors.pop(0)
            if error is not None:
                raise error
        if self.write_error:
            raise self.write_error
        return None


def make_manager(devices, adapters, *, polling_interval_seconds=15):
    created = {}

    def factory(config):
        created[config.device_id] = config
        adapter = adapters[config.device_id]
        if isinstance(adapter, BaseException):
            raise adapter
        return adapter

    return DeviceManager(
        AppConfig(tuple(devices)),
        adapter_factory=factory,
        polling_interval_seconds=polling_interval_seconds,
    ), created


def test_catalog_is_public_and_uses_device_id_identity():
    devices = [make_device("device-a", "192.0.2.10"), make_device("device-b", "192.0.2.11")]
    manager, _ = make_manager(devices, {})

    listed = manager.list_devices()
    selected = manager.get_device("device-b")

    assert len(listed) == 2
    assert all(status.device_id in {"device-a", "device-b"} for status in listed)
    assert selected.device_id == "device-b"
    assert selected.address == "192.0.2.11"
    assert selected.state.quality is DeviceStateQuality.UNKNOWN
    assert "unit-test-key-not-real" not in repr(listed)
    assert all(not isinstance(status, DeviceConfig) for status in listed)


def test_unknown_device_id_is_a_safe_structured_error():
    manager, _ = make_manager([make_device("device-a", "192.0.2.10")], {})

    with pytest.raises(BackendError) as error:
        manager.get_device("missing")

    assert error.value.code is ErrorCode.INVALID_INPUT
    assert "missing" not in str(error.value)


def test_read_state_normalizes_power_and_work_mode_using_device_map():
    device = make_device("device-a", "192.0.2.10")
    adapter = FakeAdapter(statuses=[{"20": True, "21": "white", "24": "ignored"}])
    manager, created = make_manager([device], {"device-a": adapter})

    status = manager.read_state("device-a")

    assert created["device-a"].device_id == "device-a"
    assert status.connection is ConnectionStatus.ONLINE
    assert status.state.power is True
    assert status.state.work_mode == "white"
    assert status.state.quality is DeviceStateQuality.CONFIRMED
    assert status.state.hsv is None


def test_missing_dps_do_not_invent_or_discard_last_known_values():
    device = make_device("device-a", "192.0.2.10")
    adapter = FakeAdapter(statuses=[{"20": True, "21": "white"}, {}])
    manager, _ = make_manager([device], {"device-a": adapter})

    initial = manager.get_device("device-a")
    assert initial.state.power is None
    assert initial.state.work_mode is None
    first = manager.read_state("device-a")
    second = manager.read_state("device-a")

    assert first.state.power is True
    assert second.state.power is True
    assert second.state.work_mode == "white"
    assert second.state.hsv is None


def test_empty_dps_read_does_not_mark_unknown_fields_confirmed():
    device = make_device("device-a", "192.0.2.10")
    manager, _ = make_manager([device], {"device-a": FakeAdapter(statuses=[{}])})

    status = manager.read_state("device-a")

    assert status.connection is ConnectionStatus.ONLINE
    assert status.state.power is None
    assert status.state.work_mode is None
    assert status.state.quality is DeviceStateQuality.UNKNOWN


def test_read_timeout_marks_device_offline_and_preserves_confirmed_state():
    device = make_device("device-a", "192.0.2.10")
    adapter = FakeAdapter(statuses=[{"20": True}, BackendError(ErrorCode.TIMEOUT, "safe timeout")])
    manager, _ = make_manager([device], {"device-a": adapter})
    manager.read_state("device-a")

    with pytest.raises(BackendError) as error:
        manager.read_state("device-a")

    status = manager.get_device("device-a")
    assert error.value.code is ErrorCode.TIMEOUT
    assert status.connection is ConnectionStatus.OFFLINE
    assert status.state.power is True
    assert status.state.quality is DeviceStateQuality.OFFLINE


def test_read_device_error_degrades_quality_but_keeps_connection_and_last_value():
    device = make_device("device-a", "192.0.2.10")
    adapter = FakeAdapter(statuses=[{"20": True}, BackendError(ErrorCode.DEVICE_ERROR, "Tuya device returned an unexpected payload (904)")])
    manager, _ = make_manager([device], {"device-a": adapter})
    manager.read_state("device-a")

    with pytest.raises(BackendError) as error:
        manager.read_state("device-a")

    status = manager.get_device("device-a")
    assert error.value.code is ErrorCode.DEVICE_ERROR
    assert status.connection is ConnectionStatus.ONLINE
    assert status.state.power is True
    assert status.state.quality is DeviceStateQuality.UNKNOWN


def test_valid_read_recovers_after_invalid_status_response():
    device = make_device("device-a", "192.0.2.10")
    adapter = FakeAdapter(statuses=[{"20": True}, object(), {"20": False}])
    manager, _ = make_manager([device], {"device-a": adapter})
    manager.read_state("device-a")
    with pytest.raises(BackendError):
        manager.read_state("device-a")

    recovered = manager.read_state("device-a")

    assert recovered.connection is ConnectionStatus.ONLINE
    assert recovered.state.power is False
    assert recovered.state.quality is DeviceStateQuality.CONFIRMED


def test_invalid_read_failure_is_isolated_from_other_devices():
    devices = [make_device("device-a", "192.0.2.10"), make_device("device-b", "192.0.2.11")]
    adapters = {
        "device-a": FakeAdapter(
            statuses=[{"20": True}, BackendError(ErrorCode.DEVICE_ERROR, "safe payload error")]
        ),
        "device-b": FakeAdapter(statuses=[{"20": False}, {"20": False}]),
    }
    manager, _ = make_manager(devices, adapters)
    manager.read_state("device-a")
    manager.read_state("device-b")

    with pytest.raises(BackendError):
        manager.read_state("device-a")

    unaffected = manager.get_device("device-b")
    assert unaffected.connection is ConnectionStatus.ONLINE
    assert unaffected.state.power is False
    assert unaffected.state.quality is DeviceStateQuality.CONFIRMED


@pytest.mark.parametrize(("requested", "first_observation", "later_observation"), [(True, False, True), (False, True, False)])
def test_divergent_read_keeps_intent_pending_until_matching_observation(
    requested, first_observation, later_observation
):
    device = make_device("device-a", "192.0.2.10")
    adapter = FakeAdapter(statuses=[{"20": first_observation}, {"20": later_observation}])
    manager, _ = make_manager([device], {"device-a": adapter})

    with pytest.raises(BackendError, match="differs"):
        manager.set_power("device-a", requested)

    divergent = manager.get_device("device-a")
    assert divergent.state.power is first_observation
    assert divergent.state.quality is DeviceStateQuality.PENDING

    confirmed = manager.read_state("device-a")

    assert confirmed.state.power is later_observation
    assert confirmed.state.quality is DeviceStateQuality.CONFIRMED


def test_new_power_command_replaces_old_pending_intent():
    device = make_device("device-a", "192.0.2.10")
    adapter = FakeAdapter(statuses=[{"20": False}, {"20": True}, {"20": False}])
    manager, _ = make_manager([device], {"device-a": adapter})

    with pytest.raises(BackendError):
        manager.set_power("device-a", True)
    with pytest.raises(BackendError, match="differs"):
        manager.set_power("device-a", False)

    status_after_stale_observation = manager.get_device("device-a")
    assert status_after_stale_observation.state.power is True
    assert status_after_stale_observation.state.quality is DeviceStateQuality.PENDING

    confirmed = manager.read_state("device-a")
    assert confirmed.state.power is False
    assert confirmed.state.quality is DeviceStateQuality.CONFIRMED


def test_inconclusive_null_ack_retains_observed_power_and_pending_intent():
    device = make_device("device-a", "192.0.2.10")
    adapter = FakeAdapter(statuses=[{"20": False}, {}])
    manager, _ = make_manager([device], {"device-a": adapter})
    manager.read_state("device-a")

    with pytest.raises(BackendError, match="did not report"):
        manager.set_power("device-a", True)

    status = manager.get_device("device-a")
    assert status.state.power is False
    assert status.state.quality is DeviceStateQuality.PENDING
    assert status.state.knowledge.power is FieldKnowledge.STALE


def test_power_intent_recovers_after_confirmation_timeout():
    device = make_device("device-a", "192.0.2.10")
    adapter = FakeAdapter(statuses=[BackendError(ErrorCode.TIMEOUT, "safe"), {"20": True}])
    manager, _ = make_manager([device], {"device-a": adapter})

    with pytest.raises(BackendError) as error:
        manager.set_power("device-a", True)
    assert error.value.code is ErrorCode.TIMEOUT
    assert manager.get_device("device-a").state.quality is DeviceStateQuality.PENDING

    recovered = manager.read_state("device-a")

    assert recovered.state.power is True
    assert recovered.state.quality is DeviceStateQuality.CONFIRMED


def test_explicit_write_rejection_does_not_leave_new_intent_pending():
    device = make_device("device-a", "192.0.2.10")
    adapter = FakeAdapter(
        statuses=[{"20": False}],
        write_error=BackendError(ErrorCode.UNSUPPORTED_CAPABILITY, "safe rejection"),
    )
    manager, _ = make_manager([device], {"device-a": adapter})
    manager.read_state("device-a")

    with pytest.raises(BackendError):
        manager.set_power("device-a", True)

    status = manager.get_device("device-a")
    assert status.state.power is False
    assert status.state.quality is DeviceStateQuality.CONFIRMED


def test_update_address_invalidates_confirmed_quality_and_preserves_pending_intent():
    device = make_device("device-a", "192.0.2.10")
    adapters = [FakeAdapter(statuses=[{"20": False}, {"20": False}]), FakeAdapter(statuses=[{"20": True}])]
    created = []

    def factory(config):
        created.append(config)
        return adapters[len(created) - 1]

    manager = DeviceManager(AppConfig((device,)), adapter_factory=factory)
    manager.read_state("device-a")
    with pytest.raises(BackendError, match="differs"):
        manager.set_power("device-a", True)
    pending = manager.get_device("device-a")
    assert pending.state.quality is DeviceStateQuality.PENDING

    updated = manager.update_address("device-a", "192.0.2.12")

    assert updated.device_id == "device-a"
    assert updated.state.power is False
    assert updated.state.quality is DeviceStateQuality.PENDING
    assert updated.connection is ConnectionStatus.UNKNOWN
    confirmed = manager.read_state("device-a")
    assert len(created) == 2
    assert created[1].address == "192.0.2.12"
    assert confirmed.state.power is True
    assert confirmed.state.quality is DeviceStateQuality.CONFIRMED


def test_adapter_initialization_failure_is_isolated_per_device():
    devices = [make_device("device-a", "192.0.2.10"), make_device("device-b", "192.0.2.11")]
    adapters = {
        "device-a": BackendError(ErrorCode.DEVICE_ERROR, "safe construction failure"),
        "device-b": FakeAdapter(statuses=[{"20": False}]),
    }
    manager, _ = make_manager(devices, adapters)

    with pytest.raises(BackendError):
        manager.read_state("device-a")
    healthy = manager.read_state("device-b")

    assert manager.get_device("device-a").connection is ConnectionStatus.OFFLINE
    assert healthy.state.power is False
    assert healthy.connection is ConnectionStatus.ONLINE


def test_set_power_writes_configured_dps_then_confirms_by_readback():
    device = make_device("device-a", "192.0.2.10", power_dps=7)
    adapter = FakeAdapter(statuses=[{"7": True}])
    manager, _ = make_manager([device], {"device-a": adapter})

    status = manager.set_power("device-a", True)

    assert adapter.writes == [(7, True)]
    assert status.state.power is True
    assert status.state.quality is DeviceStateQuality.CONFIRMED
    assert status.connection is ConnectionStatus.ONLINE


def test_set_power_validates_boolean_and_power_capability():
    capable = make_device("device-a", "192.0.2.10")
    incapable = make_device("device-b", "192.0.2.11", power_dps=None)
    adapters = {"device-a": FakeAdapter(), "device-b": FakeAdapter()}
    manager, _ = make_manager([capable, incapable], adapters)

    with pytest.raises(BackendError) as invalid:
        manager.set_power("device-a", 1)
    with pytest.raises(BackendError) as unsupported:
        manager.set_power("device-b", True)

    assert invalid.value.code is ErrorCode.INVALID_INPUT
    assert unsupported.value.code is ErrorCode.UNSUPPORTED_CAPABILITY
    assert adapters["device-a"].writes == []
    assert adapters["device-b"].writes == []


def test_null_ack_does_not_confirm_power_without_matching_readback():
    device = make_device("device-a", "192.0.2.10")
    adapter = FakeAdapter(statuses=[{"20": False}])
    manager, _ = make_manager([device], {"device-a": adapter})

    with pytest.raises(BackendError) as error:
        manager.set_power("device-a", True)

    status = manager.get_device("device-a")
    assert error.value.code is ErrorCode.DEVICE_ERROR
    assert adapter.writes == [(20, True)]
    assert status.state.power is False
    assert status.state.quality is DeviceStateQuality.PENDING


def test_readback_failure_leaves_power_pending_and_device_offline():
    device = make_device("device-a", "192.0.2.10")
    adapter = FakeAdapter(statuses=[BackendError(ErrorCode.TIMEOUT, "safe timeout")])
    manager, _ = make_manager([device], {"device-a": adapter})

    with pytest.raises(BackendError) as error:
        manager.set_power("device-a", True)

    status = manager.get_device("device-a")
    assert error.value.code is ErrorCode.TIMEOUT
    assert status.connection is ConnectionStatus.OFFLINE
    assert status.state.quality is DeviceStateQuality.PENDING


def test_explicitly_rejected_power_write_restores_the_previous_state_quality():
    device = make_device("device-a", "192.0.2.10")
    adapter = FakeAdapter(
        statuses=[{"20": False}],
        write_error=BackendError(ErrorCode.UNSUPPORTED_CAPABILITY, "safe rejection"),
    )
    manager, _ = make_manager([device], {"device-a": adapter})
    manager.read_state("device-a")

    with pytest.raises(BackendError) as error:
        manager.set_power("device-a", True)

    status = manager.get_device("device-a")
    assert error.value.code is ErrorCode.UNSUPPORTED_CAPABILITY
    assert status.state.power is False
    assert status.state.quality is DeviceStateQuality.CONFIRMED


def test_per_device_locks_serialize_operations_without_global_lock():
    first_read_entered = threading.Event()
    release_first_read = threading.Event()
    write_entered = threading.Event()
    second_read_entered = threading.Event()

    def blocking_read():
        first_read_entered.set()
        assert release_first_read.wait(timeout=2)

    def independent_read():
        second_read_entered.set()

    devices = [make_device("device-a", "192.0.2.10"), make_device("device-b", "192.0.2.11")]
    first = FakeAdapter(
        statuses=[{"20": False}, {"20": True}],
        on_status=blocking_read,
        on_write=write_entered.set,
    )
    second = FakeAdapter(statuses=[{"20": True}], on_status=independent_read)

    def first_factory(config):
        return first if config.device_id == "device-a" else second

    manager = DeviceManager(AppConfig(tuple(devices)), adapter_factory=first_factory)
    errors = []

    reader = threading.Thread(target=lambda: _capture(errors, manager.read_state, "device-a"))
    reader.start()
    assert first_read_entered.wait(timeout=2)

    writer_ready = threading.Event()

    def write_same_device():
        writer_ready.set()
        try:
            manager.set_power("device-a", True)
        except BackendError as error:
            errors.append(error)

    writer = threading.Thread(target=write_same_device)
    writer.start()
    assert writer_ready.wait(timeout=2)
    assert not write_entered.is_set()

    independent = threading.Thread(target=lambda: _capture(errors, manager.read_state, "device-b"))
    independent.start()
    independent.join(timeout=2)
    assert not independent.is_alive()
    assert second_read_entered.is_set()

    release_first_read.set()
    reader.join(timeout=2)
    writer.join(timeout=2)
    assert not reader.is_alive()
    assert not writer.is_alive()
    assert not errors
    assert first.writes == [(20, True)]


def test_polling_has_explicit_lifecycle_and_poll_once_isolated_failures():
    devices = [make_device("device-a", "192.0.2.10"), make_device("device-b", "192.0.2.11")]
    failing = FakeAdapter(statuses=[BackendError(ErrorCode.TIMEOUT, "safe timeout")])
    healthy = FakeAdapter(statuses=[{"20": True}])
    manager, _ = make_manager(devices, {"device-a": failing, "device-b": healthy})

    assert manager.polling_running is False
    manager.poll_once()
    assert manager.get_device("device-a").connection is ConnectionStatus.OFFLINE
    assert manager.get_device("device-b").state.power is True

    manager.start_polling()
    assert manager.polling_running is True
    manager.stop_polling()
    assert manager.polling_running is False


def test_update_address_rebuilds_adapter_without_changing_device_identity():
    device = make_device("stable-id", "192.0.2.10")
    adapters = [FakeAdapter(statuses=[{"20": True}]), FakeAdapter(statuses=[{"20": False}])]
    created = []

    def factory(config):
        created.append(config)
        return adapters[len(created) - 1]

    manager = DeviceManager(AppConfig((device,)), adapter_factory=factory)
    manager.read_state("stable-id")
    updated = manager.update_address("stable-id", "192.0.2.12")
    assert updated.state.quality is DeviceStateQuality.UNKNOWN
    status = manager.read_state("stable-id")

    assert updated.device_id == "stable-id"
    assert updated.address == "192.0.2.12"
    assert len(created) == 2
    assert created[1].device_id == "stable-id"
    assert created[1].address == "192.0.2.12"
    assert status.state.power is False


def test_read_state_normalizes_white_temperature_hsv_and_scene_separately():
    device = make_color_device("mesa", "192.0.2.10")
    adapter = FakeAdapter(
        statuses=[
            {
                "20": True,
                "21": "white",
                "22": 505,
                "23": 250,
                "24": "007803e800fa",
                "25": "scene_data",
            }
        ]
    )
    manager, _ = make_manager([device], {"mesa": adapter})

    status = manager.read_state("mesa")

    assert status.state.white_brightness_percent == 50.0
    assert status.state.color_temperature_percent == 25.0
    assert status.state.hsv == HSVColor(120, 100, 25)
    assert status.state.color_value_percent == 25.0
    assert status.state.scene == "scene_data"
    assert status.state.quality is DeviceStateQuality.CONFIRMED


def test_color_value_and_white_brightness_remain_independent():
    device = make_color_device("mesa", "192.0.2.10")
    adapter = FakeAdapter(statuses=[{"22": 505, "24": "00b403e800fa"}])
    manager, _ = make_manager([device], {"mesa": adapter})

    status = manager.read_state("mesa")

    assert status.state.white_brightness_percent == 50.0
    assert status.state.color_value_percent == 25.0
    assert status.state.hsv == HSVColor(180, 100, 25)


def test_invalid_lighting_dps_preserve_last_valid_observations():
    device = make_color_device("mesa", "192.0.2.10")
    adapter = FakeAdapter(
        statuses=[
            {"22": 505, "23": 250, "24": "007803e800fa", "25": "scene_data"},
            {"22": True, "23": 1001, "24": "not-a-color", "25": {"unsafe": "shape"}},
        ]
    )
    manager, _ = make_manager([device], {"mesa": adapter})
    manager.read_state("mesa")

    status = manager.read_state("mesa")

    assert status.state.white_brightness_percent == 50.0
    assert status.state.color_temperature_percent == 25.0
    assert status.state.hsv == HSVColor(120, 100, 25)
    assert status.state.scene == "scene_data"


def test_set_white_brightness_uses_its_range_and_confirms_readback():
    device = make_color_device("mesa", "192.0.2.10")
    adapter = FakeAdapter(statuses=[{"21": "white", "22": 505}, {"21": "white", "22": 802}])
    manager, _ = make_manager([device], {"mesa": adapter})

    status = manager.set_white_brightness("mesa", 80)

    assert adapter.writes == [(22, 802)]
    assert status.state.white_brightness_percent == 80.0
    assert status.state.quality is DeviceStateQuality.CONFIRMED


def test_set_color_temperature_switches_mode_before_using_configured_dps():
    device = make_color_device("mesa", "192.0.2.10")
    adapter = FakeAdapter(
        statuses=[{"21": "colour", "23": 500}, {"21": "white", "23": 700}]
    )
    manager, _ = make_manager([device], {"mesa": adapter})

    status = manager.set_color_temperature("mesa", 70)

    assert adapter.writes == [(21, "white"), (23, 700)]
    assert status.state.work_mode == "white"
    assert status.state.color_temperature_percent == 70.0


def test_set_hsv_switches_to_color_mode_before_writing_hsv():
    device = make_color_device("mesa", "192.0.2.10")
    adapter = FakeAdapter(
        statuses=[
            {"21": "white", "24": "000003e803e8"},
            {"21": "colour", "24": "007803e801f4"},
        ]
    )
    manager, _ = make_manager([device], {"mesa": adapter})

    status = manager.set_hsv("mesa", 120, 100, 50)

    assert adapter.writes == [(21, "colour"), (24, "007803e801f4")]
    assert status.state.hsv == HSVColor(120, 100, 50)
    assert status.state.color_value_percent == 50.0


def test_set_color_brightness_preserves_hue_and_saturation():
    device = make_color_device("strip", "192.0.2.11", white=False)
    adapter = FakeAdapter(
        statuses=[{"21": "colour", "24": "00b4032002bc"}, {"21": "colour", "24": "00b4032000fa"}]
    )
    manager, _ = make_manager([device], {"strip": adapter})

    status = manager.set_color_brightness("strip", 25)

    assert adapter.writes == [(24, "00b4032000fa")]
    assert status.state.hsv == HSVColor(180, 80, 25)
    assert status.state.color_value_percent == 25.0
    assert status.state.white_brightness_percent is None


def test_set_color_brightness_requires_a_previously_observed_valid_hsv():
    device = make_color_device("strip", "192.0.2.11", white=False)
    adapter = FakeAdapter(statuses=[{"21": "colour", "24": "invalid!"}])
    manager, _ = make_manager([device], {"strip": adapter})

    with pytest.raises(BackendError) as error:
        manager.set_color_brightness("strip", 25)

    assert error.value.code is ErrorCode.DEVICE_ERROR
    assert adapter.writes == []


def test_color_brightness_rejects_invalid_current_hsv_instead_of_reusing_stale_color():
    device = make_color_device("strip", "192.0.2.11", white=False)
    previous_hsv = "00b4032002bc"
    adapter = FakeAdapter(
        statuses=[
            {"24": previous_hsv},
            {"21": "colour", "24": "invalid!"},
            {"21": "colour", "24": "00b4032000fa"},
        ]
    )
    manager, _ = make_manager([device], {"strip": adapter})
    manager.read_state("strip")

    with pytest.raises(BackendError) as error:
        manager.set_color_brightness("strip", 25)

    status = manager.get_device("strip")
    assert error.value.code is ErrorCode.DEVICE_ERROR
    assert status.state.hsv == HSVColor(180, 80, 70)
    assert adapter.writes == []


def test_color_brightness_rejects_missing_current_hsv_instead_of_reusing_stale_color():
    device = make_color_device("strip", "192.0.2.11", white=False)
    adapter = FakeAdapter(
        statuses=[
            {"21": "colour", "24": "00b4032002bc"},
            {"21": "colour"},
            {"21": "colour", "24": "00b4032000fa"},
        ]
    )
    manager, _ = make_manager([device], {"strip": adapter})
    manager.read_state("strip")

    with pytest.raises(BackendError) as error:
        manager.set_color_brightness("strip", 25)

    status = manager.get_device("strip")
    assert error.value.code is ErrorCode.DEVICE_ERROR
    assert status.state.hsv == HSVColor(180, 80, 70)
    assert adapter.writes == []


def test_color_brightness_uses_current_valid_hsv_and_changes_only_value():
    device = make_color_device("strip", "192.0.2.11", white=False)
    adapter = FakeAdapter(
        statuses=[
            {"21": "colour", "24": "005a03e801f4"},
            {"21": "colour", "24": "00b4032002bc"},
            {"21": "colour", "24": "00b4032000fa"},
        ]
    )
    manager, _ = make_manager([device], {"strip": adapter})
    manager.read_state("strip")

    status = manager.set_color_brightness("strip", 25)

    assert adapter.writes == [(24, "00b4032000fa")]
    assert status.state.hsv == HSVColor(180, 80, 25)
    assert status.state.quality is DeviceStateQuality.CONFIRMED


def test_led_strip_rejects_white_brightness_and_color_temperature():
    device = make_color_device("strip", "192.0.2.11", white=False)
    adapter = FakeAdapter()
    manager, _ = make_manager([device], {"strip": adapter})

    with pytest.raises(BackendError) as brightness_error:
        manager.set_white_brightness("strip", 50)
    with pytest.raises(BackendError) as temperature_error:
        manager.set_color_temperature("strip", 50)

    assert brightness_error.value.code is ErrorCode.UNSUPPORTED_CAPABILITY
    assert temperature_error.value.code is ErrorCode.UNSUPPORTED_CAPABILITY
    assert adapter.writes == []


def test_lighting_command_divergence_keeps_field_intent_pending_until_readback():
    device = make_color_device("mesa", "192.0.2.10")
    adapter = FakeAdapter(
        statuses=[
            {"21": "colour", "24": "000003e803e8"},
            {"21": "colour", "24": "00f003e801f4"},
            {"21": "colour", "24": "007803e801f4"},
        ]
    )
    manager, _ = make_manager([device], {"mesa": adapter})

    with pytest.raises(BackendError, match="differs"):
        manager.set_hsv("mesa", 120, 100, 50)

    divergent = manager.get_device("mesa")
    assert divergent.state.hsv == HSVColor(240, 100, 50)
    assert divergent.state.quality is DeviceStateQuality.PENDING

    confirmed = manager.read_state("mesa")
    assert confirmed.state.hsv == HSVColor(120, 100, 50)
    assert confirmed.state.quality is DeviceStateQuality.CONFIRMED


def test_color_readback_does_not_resolve_pending_power_intent():
    device = make_color_device("mesa", "192.0.2.10")
    adapter = FakeAdapter(
        statuses=[
            {"20": False, "21": "white"},
            {"20": False, "21": "white", "24": "000003e803e8"},
            {"20": False, "21": "colour", "24": "007803e801f4"},
            {"20": True, "21": "colour", "24": "007803e801f4"},
        ]
    )
    manager, _ = make_manager([device], {"mesa": adapter})
    with pytest.raises(BackendError):
        manager.set_power("mesa", True)

    status = manager.set_hsv("mesa", 120, 100, 50)

    assert status.state.power is False
    assert status.state.hsv == HSVColor(120, 100, 50)
    assert status.state.quality is DeviceStateQuality.PENDING

    recovered = manager.read_state("mesa")
    assert recovered.state.power is True
    assert recovered.state.quality is DeviceStateQuality.CONFIRMED


def test_partial_mode_switch_is_not_rolled_back_and_remains_observable():
    device = make_color_device("mesa", "192.0.2.10")
    adapter = FakeAdapter(
        statuses=[
            {"21": "white", "24": "000003e803e8"},
            {"21": "colour", "24": "000003e803e8"},
            {"21": "colour", "24": "007803e801f4"},
        ],
        write_errors=[None, BackendError(ErrorCode.DEVICE_ERROR, "safe write failure")],
    )
    manager, _ = make_manager([device], {"mesa": adapter})

    with pytest.raises(BackendError):
        manager.set_hsv("mesa", 120, 100, 50)

    partial = manager.get_device("mesa")
    assert adapter.writes == [(21, "colour"), (24, "007803e801f4")]
    assert partial.state.work_mode == "colour"
    assert partial.state.hsv == HSVColor(0, 100, 100)
    assert partial.state.quality is DeviceStateQuality.PENDING

    confirmed = manager.read_state("mesa")
    assert confirmed.state.hsv == HSVColor(120, 100, 50)
    assert confirmed.state.quality is DeviceStateQuality.CONFIRMED


def test_lighting_arguments_are_validated_before_any_write():
    device = make_color_device("mesa", "192.0.2.10")
    adapter = FakeAdapter()
    manager, _ = make_manager([device], {"mesa": adapter})

    with pytest.raises(BackendError) as brightness_error:
        manager.set_white_brightness("mesa", math.nan)
    with pytest.raises(BackendError) as hsv_error:
        manager.set_hsv("mesa", True, 100, 50)

    assert brightness_error.value.code is ErrorCode.INVALID_INPUT
    assert hsv_error.value.code is ErrorCode.INVALID_INPUT
    assert adapter.writes == []


def test_lighting_control_does_not_leak_local_key_in_public_status():
    device = make_color_device("mesa", "192.0.2.10")
    adapter = FakeAdapter(
        statuses=[{"21": "white", "22": 500}, {"21": "white", "22": 505}]
    )
    manager, _ = make_manager([device], {"mesa": adapter})

    status = manager.set_white_brightness("mesa", 50)

    assert status.state.white_brightness_percent == 50.0
    assert "unit-test-key-not-real" not in repr(status)


def test_lighting_command_skips_redundant_write_when_fresh_state_matches():
    device = make_color_device("mesa", "192.0.2.10")
    adapter = FakeAdapter(statuses=[{"21": "white", "22": 802}])
    manager, _ = make_manager([device], {"mesa": adapter})

    status = manager.set_white_brightness("mesa", 80)

    assert status.state.white_brightness_percent == 80.0
    assert adapter.writes == []


def test_explicit_mode_rejection_restores_observed_quality_and_values():
    device = make_color_device("mesa", "192.0.2.10")
    adapter = FakeAdapter(
        statuses=[{"21": "white", "24": "00b4032002bc"}],
        write_error=BackendError(ErrorCode.UNSUPPORTED_CAPABILITY, "safe rejection"),
    )
    manager, _ = make_manager([device], {"mesa": adapter})
    with pytest.raises(BackendError) as error:
        manager.set_hsv("mesa", 120, 100, 50)

    status = manager.get_device("mesa")
    assert error.value.code is ErrorCode.UNSUPPORTED_CAPABILITY
    assert status.state.work_mode == "white"
    assert status.state.hsv == HSVColor(180, 80, 70)
    assert status.state.quality is DeviceStateQuality.CONFIRMED


def test_explicit_brightness_rejection_does_not_leave_phantom_pending_quality():
    device = make_color_device("mesa", "192.0.2.10")
    adapter = FakeAdapter(
        statuses=[{"21": "white", "22": 505}],
        write_error=BackendError(ErrorCode.INVALID_INPUT, "safe rejection"),
    )
    manager, _ = make_manager([device], {"mesa": adapter})
    with pytest.raises(BackendError) as error:
        manager.set_white_brightness("mesa", 80)

    status = manager.get_device("mesa")
    assert error.value.code is ErrorCode.INVALID_INPUT
    assert status.state.white_brightness_percent == 50.0
    assert status.state.quality is DeviceStateQuality.CONFIRMED


def test_explicit_write_rejection_preserves_independent_power_intent_until_readback():
    device = make_color_device("mesa", "192.0.2.10")
    adapter = FakeAdapter(
        statuses=[
            {"20": False},
            {"20": False, "21": "white", "22": 505},
            {"20": True, "21": "white", "22": 505},
        ],
        write_errors=[None, BackendError(ErrorCode.UNSUPPORTED_CAPABILITY, "safe rejection")],
    )
    manager, _ = make_manager([device], {"mesa": adapter})

    with pytest.raises(BackendError, match="differs"):
        manager.set_power("mesa", True)
    with pytest.raises(BackendError) as error:
        manager.set_white_brightness("mesa", 80)

    rejected = manager.get_device("mesa")
    assert error.value.code is ErrorCode.UNSUPPORTED_CAPABILITY
    assert rejected.state.power is False
    assert rejected.state.white_brightness_percent == 50.0
    assert rejected.state.quality is DeviceStateQuality.PENDING

    recovered = manager.read_state("mesa")
    assert recovered.state.power is True
    assert recovered.state.white_brightness_percent == 50.0
    assert recovered.state.quality is DeviceStateQuality.CONFIRMED


def test_rejection_does_not_promote_unknown_state_and_later_valid_read_recovers():
    device = make_color_device("mesa", "192.0.2.10")
    adapter = FakeAdapter(
        statuses=[{}, {"21": "white", "22": 505}],
        write_error=BackendError(ErrorCode.INVALID_INPUT, "safe rejection"),
    )
    manager, _ = make_manager([device], {"mesa": adapter})

    with pytest.raises(BackendError):
        manager.set_white_brightness("mesa", 80)

    after_rejection = manager.get_device("mesa")
    assert after_rejection.state.white_brightness_percent is None
    assert after_rejection.state.quality is DeviceStateQuality.UNKNOWN

    recovered = manager.read_state("mesa")
    assert recovered.state.white_brightness_percent == 50.0
    assert recovered.state.quality is DeviceStateQuality.CONFIRMED


def _capture(errors, operation, device_id):
    try:
        operation(device_id)
    except BaseException as error:
        errors.append(error)


def test_field_knowledge_tracks_partial_invalid_failure_and_recovery():
    device = make_color_device("knowledge", "192.0.2.30")
    adapter = FakeAdapter(statuses=[
        {"20": True, "21": "colour", "22": 505, "23": 500, "24": "007803e801f4", "25": "scene"},
        {"20": False, "22": "invalid", "24": "bad"},
        BackendError(ErrorCode.DEVICE_OFFLINE, "fixture unreachable"),
        {"20": True, "21": "white", "22": 400, "23": 700, "24": "00b4032000fa", "25": "scene"},
    ])
    manager, _ = make_manager([device], {"knowledge": adapter})
    from smart_home_tray.models import FieldKnowledge as K

    first = manager.read_state("knowledge").state.knowledge
    assert first.power is K.OBSERVED and first.hsv is K.OBSERVED
    assert first.color_value is K.OBSERVED and first.scene is K.OBSERVED
    partial = manager.read_state("knowledge").state
    assert partial.power is False and partial.knowledge.power is K.OBSERVED
    assert partial.white_brightness_percent is not None
    assert partial.knowledge.white_brightness is K.STALE
    assert partial.knowledge.hsv is K.STALE and partial.knowledge.color_value is K.STALE
    with pytest.raises(BackendError):
        manager.read_state("knowledge")
    failed = manager.get_device("knowledge")
    assert failed.connection is ConnectionStatus.OFFLINE
    assert failed.state.knowledge.power is K.STALE
    assert failed.state.knowledge.hsv is K.STALE
    recovered = manager.read_state("knowledge")
    assert recovered.connection is ConnectionStatus.ONLINE
    assert recovered.state.knowledge.power is K.OBSERVED
    assert recovered.state.knowledge.hsv is K.OBSERVED
    assert recovered.state.knowledge.color_value is K.OBSERVED


def test_unknown_fields_become_observed_only_after_valid_readback():
    device = make_device("unknown-first", "192.0.2.31")
    adapter = FakeAdapter(statuses=[{"20": "not-a-bool"}, {"20": True}])
    manager, _ = make_manager([device], {"unknown-first": adapter})
    from smart_home_tray.models import FieldKnowledge as K

    invalid = manager.read_state("unknown-first").state
    assert invalid.power is None and invalid.knowledge.power is K.UNKNOWN
    valid = manager.read_state("unknown-first").state
    assert valid.power is True and valid.knowledge.power is K.OBSERVED
