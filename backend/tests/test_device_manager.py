from __future__ import annotations

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


class FakeAdapter:
    def __init__(self, statuses=None, write_error=None, on_status=None, on_write=None):
        self.statuses = list(statuses or [])
        self.write_error = write_error
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


def _capture(errors, operation, device_id):
    try:
        operation(device_id)
    except BaseException as error:
        errors.append(error)
