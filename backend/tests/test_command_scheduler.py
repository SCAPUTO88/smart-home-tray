from __future__ import annotations

import threading
from concurrent.futures import CancelledError
from types import SimpleNamespace
import math

import pytest

from smart_home_tray.config import AppConfig
from smart_home_tray.device_manager import DeviceManager
from smart_home_tray.models import (
    BackendError,
    DeviceConfig,
    DeviceStateQuality,
    DPSMap,
    ErrorCode,
    ValueRange,
)


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, scheduler, seconds):
        self.value += seconds
        with scheduler._condition:
            scheduler._condition.notify_all()


class FakeDeviceManager:
    def __init__(self, device_ids=("lamp-a", "lamp-b"), gates=None, failures=None):
        self._devices = tuple(SimpleNamespace(device_id=device_id) for device_id in device_ids)
        self._gates = gates or {}
        self._failures = {key: list(value) for key, value in (failures or {}).items()}
        self._condition = threading.Condition()
        self.calls = []

    def list_devices(self):
        return self._devices

    def list_device_ids(self):
        return tuple(device.device_id for device in self._devices)

    def _run(self, device_id, kind, *args):
        with self._condition:
            index = sum(call[0] == device_id for call in self.calls)
            self.calls.append((device_id, kind, args))
            self._condition.notify_all()
        gate = self._gates.get((device_id, index))
        if gate:
            entered, release = gate
            entered.set()
            assert release.wait(timeout=3)
        failure_list = self._failures.get((device_id, kind), [])
        if failure_list:
            error = failure_list.pop(0)
            if error:
                raise error
        return (device_id, kind, args)

    def set_white_brightness(self, device_id, percent):
        return self._run(device_id, "white_brightness", percent)

    def set_color_temperature(self, device_id, percent):
        return self._run(device_id, "color_temperature", percent)

    def set_hsv(self, device_id, hue, saturation, value):
        return self._run(device_id, "hsv", hue, saturation, value)

    def set_color_brightness(self, device_id, percent):
        return self._run(device_id, "color_brightness", percent)

    def set_power(self, device_id, enabled):
        return self._run(device_id, "power", enabled)

    def wait_for_calls(self, count):
        with self._condition:
            assert self._condition.wait_for(lambda: len(self.calls) >= count, timeout=3)


class QueueLanAdapter:
    def __init__(self, statuses, *, first_read_entered=None, release_first_read=None):
        self.statuses = list(statuses)
        self.writes = []
        self.read_count = 0
        self.first_read_entered = first_read_entered
        self.release_first_read = release_first_read

    def read_status(self):
        self.read_count += 1
        if self.read_count == 1 and self.first_read_entered:
            self.first_read_entered.set()
            assert self.release_first_read.wait(timeout=3)
        if not self.statuses:
            raise BackendError(ErrorCode.DEVICE_OFFLINE, "fake device unavailable")
        result = self.statuses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def write_dps(self, index, value):
        self.writes.append((index, value))


def real_manager(adapter, *, color=True, white=True):
    device = DeviceConfig(
        device_id="lamp-a",
        name="Test lamp",
        address="192.0.2.10",
        protocol_version=3.5,
        local_key="scheduler-test-key-not-real",
        dps=DPSMap(
            power=20,
            work_mode=21,
            white_brightness=22 if white else None,
            white_temperature=23 if white else None,
            hsv=24 if color else None,
        ),
        white_brightness_range=ValueRange(10, 1000) if white else None,
        white_temperature_range=ValueRange(0, 1000) if white else None,
    )
    return DeviceManager(AppConfig((device,)), adapter_factory=lambda _: adapter)


def advance(clock, scheduler, seconds=0.15):
    clock.advance(scheduler, seconds)


def test_burst_coalesces_hundreds_of_brightness_values_to_the_last_intent():
    from smart_home_tray.command_scheduler import CommandScheduler

    clock = FakeClock()
    manager = FakeDeviceManager()
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0.15, clock=clock)
    scheduler.start()
    try:
        futures = [scheduler.submit_white_brightness("lamp-a", value) for value in range(100)]
        assert all(future.cancelled() for future in futures[:-1])

        advance(clock, scheduler)
        manager.wait_for_calls(1)

        assert manager.calls == [("lamp-a", "white_brightness", (99,))]
        assert futures[-1].result(timeout=1) == ("lamp-a", "white_brightness", (99,))
    finally:
        scheduler.stop()


def test_continuous_drag_sends_periodic_latest_values_without_waiting_for_release():
    from smart_home_tray.command_scheduler import CommandScheduler

    clock = FakeClock()
    manager = FakeDeviceManager()
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0.15, clock=clock)
    scheduler.start()
    try:
        for value, expected_count in ((10, 1), (20, 2), (30, 3)):
            future = scheduler.submit_white_brightness("lamp-a", value)
            advance(clock, scheduler)
            manager.wait_for_calls(expected_count)
            assert future.result(timeout=1) == ("lamp-a", "white_brightness", (value,))

        assert [call[2][0] for call in manager.calls] == [10, 20, 30]
    finally:
        scheduler.stop()


def test_replaced_command_future_is_cancelled_and_terminal():
    from smart_home_tray.command_scheduler import CommandScheduler

    clock = FakeClock()
    manager = FakeDeviceManager()
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0.15, clock=clock)
    scheduler.start()
    try:
        replaced = scheduler.submit_color_temperature("lamp-a", 20)
        latest = scheduler.submit_color_temperature("lamp-a", 65)

        assert replaced.cancelled()
        with pytest.raises(CancelledError):
            replaced.result()
        advance(clock, scheduler)
        manager.wait_for_calls(1)
        assert manager.calls == [("lamp-a", "color_temperature", (65,))]
        assert latest.result(timeout=1) == ("lamp-a", "color_temperature", (65,))
    finally:
        scheduler.stop()


def test_started_command_is_not_replaced_but_later_pending_burst_is_coalesced():
    from smart_home_tray.command_scheduler import CommandScheduler

    clock = FakeClock()
    entered, release = threading.Event(), threading.Event()
    manager = FakeDeviceManager(gates={("lamp-a", 0): (entered, release)})
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0.15, clock=clock)
    scheduler.start()
    try:
        started = scheduler.submit_white_brightness("lamp-a", 10)
        advance(clock, scheduler)
        assert entered.wait(timeout=2)
        assert started.running()

        replaced = scheduler.submit_white_brightness("lamp-a", 20)
        latest = scheduler.submit_white_brightness("lamp-a", 30)
        assert replaced.cancelled()
        release.set()
        assert started.result(timeout=2) == ("lamp-a", "white_brightness", (10,))

        advance(clock, scheduler)
        manager.wait_for_calls(2)
        assert manager.calls == [
            ("lamp-a", "white_brightness", (10,)),
            ("lamp-a", "white_brightness", (30,)),
        ]
        assert latest.result(timeout=1) == ("lamp-a", "white_brightness", (30,))
    finally:
        release.set()
        scheduler.stop()


def test_power_on_and_off_are_discrete_and_never_coalesced():
    from smart_home_tray.command_scheduler import CommandScheduler

    manager = FakeDeviceManager()
    scheduler = CommandScheduler(manager)
    scheduler.start()
    try:
        on = scheduler.submit_power("lamp-a", True)
        off = scheduler.submit_power("lamp-a", False)
        manager.wait_for_calls(2)

        assert manager.calls == [("lamp-a", "power", (True,)), ("lamp-a", "power", (False,))]
        assert on.result(timeout=1) == ("lamp-a", "power", (True,))
        assert off.result(timeout=1) == ("lamp-a", "power", (False,))
    finally:
        scheduler.stop()


def test_power_flushes_prior_continuous_intent_before_running_without_debounce():
    from smart_home_tray.command_scheduler import CommandScheduler

    clock = FakeClock()
    manager = FakeDeviceManager()
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0.15, clock=clock)
    scheduler.start()
    try:
        brightness = scheduler.submit_white_brightness("lamp-a", 42)
        power = scheduler.submit_power("lamp-a", True)
        manager.wait_for_calls(2)

        assert manager.calls == [
            ("lamp-a", "white_brightness", (42,)),
            ("lamp-a", "power", (True,)),
        ]
        assert brightness.result(timeout=1) == ("lamp-a", "white_brightness", (42,))
        assert power.result(timeout=1) == ("lamp-a", "power", (True,))
    finally:
        scheduler.stop()


def test_power_arrival_flushes_continuous_slot_queued_behind_an_inflight_operation():
    from smart_home_tray.command_scheduler import CommandScheduler

    clock = FakeClock()
    entered, release = threading.Event(), threading.Event()
    manager = FakeDeviceManager(gates={("lamp-a", 0): (entered, release)})
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0.15, clock=clock)
    scheduler.start()
    try:
        first = scheduler.submit_white_brightness("lamp-a", 10)
        advance(clock, scheduler)
        assert entered.wait(timeout=2)
        queued = scheduler.submit_white_brightness("lamp-a", 20)
        power = scheduler.submit_power("lamp-a", False)
        release.set()

        assert first.result(timeout=2) == ("lamp-a", "white_brightness", (10,))
        manager.wait_for_calls(3)
        assert manager.calls == [
            ("lamp-a", "white_brightness", (10,)),
            ("lamp-a", "white_brightness", (20,)),
            ("lamp-a", "power", (False,)),
        ]
        assert queued.result(timeout=1) == ("lamp-a", "white_brightness", (20,))
        assert power.result(timeout=1) == ("lamp-a", "power", (False,))
    finally:
        release.set()
        scheduler.stop()


def test_hsv_and_color_brightness_share_dps_but_are_not_coalesced():
    from smart_home_tray.command_scheduler import CommandScheduler

    clock = FakeClock()
    manager = FakeDeviceManager()
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0.15, clock=clock)
    scheduler.start()
    try:
        hsv = scheduler.submit_hsv("lamp-a", 180, 80, 50)
        brightness = scheduler.submit_color_brightness("lamp-a", 20)
        advance(clock, scheduler)
        manager.wait_for_calls(1)
        assert hsv.result(timeout=1) == ("lamp-a", "hsv", (180, 80, 50))
        advance(clock, scheduler)
        manager.wait_for_calls(2)

        assert manager.calls == [
            ("lamp-a", "hsv", (180, 80, 50)),
            ("lamp-a", "color_brightness", (20,)),
        ]
        assert brightness.result(timeout=1) == ("lamp-a", "color_brightness", (20,))
    finally:
        scheduler.stop()


def test_white_and_color_controls_preserve_order_as_separate_segments():
    from smart_home_tray.command_scheduler import CommandScheduler

    clock = FakeClock()
    manager = FakeDeviceManager()
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0.15, clock=clock)
    scheduler.start()
    try:
        white = scheduler.submit_white_brightness("lamp-a", 60)
        hsv = scheduler.submit_hsv("lamp-a", 240, 100, 40)
        temperature = scheduler.submit_color_temperature("lamp-a", 75)

        advance(clock, scheduler)
        manager.wait_for_calls(1)
        assert white.result(timeout=1) == ("lamp-a", "white_brightness", (60,))
        advance(clock, scheduler)
        manager.wait_for_calls(2)
        assert hsv.result(timeout=1) == ("lamp-a", "hsv", (240, 100, 40))
        advance(clock, scheduler)
        manager.wait_for_calls(3)

        assert manager.calls == [
            ("lamp-a", "white_brightness", (60,)),
            ("lamp-a", "hsv", (240, 100, 40)),
            ("lamp-a", "color_temperature", (75,)),
        ]
        assert temperature.result(timeout=1) == ("lamp-a", "color_temperature", (75,))
    finally:
        scheduler.stop()


def test_devices_progress_independently_while_one_device_is_blocked():
    from smart_home_tray.command_scheduler import CommandScheduler

    clock = FakeClock()
    entered, release = threading.Event(), threading.Event()
    manager = FakeDeviceManager(gates={("lamp-a", 0): (entered, release)})
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0.15, clock=clock)
    scheduler.start()
    try:
        first = scheduler.submit_white_brightness("lamp-a", 11)
        second = scheduler.submit_white_brightness("lamp-b", 22)
        advance(clock, scheduler)
        assert entered.wait(timeout=2)
        manager.wait_for_calls(2)

        assert second.result(timeout=1) == ("lamp-b", "white_brightness", (22,))
        assert not first.done()
        release.set()
        assert first.result(timeout=2) == ("lamp-a", "white_brightness", (11,))
    finally:
        release.set()
        scheduler.stop()


def test_failed_device_command_does_not_kill_worker_or_other_device():
    from smart_home_tray.command_scheduler import CommandScheduler

    manager = FakeDeviceManager(
        failures={("lamp-a", "hsv"): [BackendError(ErrorCode.DEVICE_ERROR, "safe failure")]}
    )
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0)
    scheduler.start()
    try:
        failed = scheduler.submit_hsv("lamp-a", 10, 20, 30)
        healthy = scheduler.submit_white_brightness("lamp-b", 44)

        with pytest.raises(BackendError) as error:
            failed.result(timeout=2)
        assert error.value.code is ErrorCode.DEVICE_ERROR
        assert healthy.result(timeout=2) == ("lamp-b", "white_brightness", (44,))

        recovered = scheduler.submit_hsv("lamp-a", 20, 30, 40)
        assert recovered.result(timeout=2) == ("lamp-a", "hsv", (20, 30, 40))
        assert len(manager.calls) == 3
    finally:
        scheduler.stop()


def test_stop_cancels_queued_futures_but_waits_for_inflight_command():
    from smart_home_tray.command_scheduler import CommandScheduler

    clock = FakeClock()
    entered, release = threading.Event(), threading.Event()
    manager = FakeDeviceManager(gates={("lamp-a", 0): (entered, release)})
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0.15, clock=clock)
    scheduler.start()
    running = scheduler.submit_white_brightness("lamp-a", 10)
    advance(clock, scheduler)
    assert entered.wait(timeout=2)
    queued = scheduler.submit_power("lamp-a", True)

    assert scheduler.stop(timeout_seconds=0) is False
    assert queued.cancelled()
    assert running.running()

    release.set()
    assert running.result(timeout=2) == ("lamp-a", "white_brightness", (10,))
    assert scheduler.stop(timeout_seconds=2) is True
    assert scheduler.stop(timeout_seconds=2) is True


def test_callback_can_request_stop_without_joining_its_own_worker():
    from smart_home_tray.command_scheduler import CommandScheduler

    entered, release = threading.Event(), threading.Event()
    callback_finished = threading.Event()
    callback_stop_results = []
    callback_errors = []
    manager = FakeDeviceManager(gates={("lamp-a", 0): (entered, release)})
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0)
    scheduler.start()

    running = scheduler.submit_white_brightness("lamp-a", 35)
    assert entered.wait(timeout=2)
    queued = scheduler.submit_power("lamp-a", True)

    def request_shutdown(_future):
        try:
            try:
                callback_stop_results.append(scheduler.stop(timeout_seconds=0))
            except BaseException as error:
                callback_errors.append(error)
        finally:
            callback_finished.set()

    running.add_done_callback(request_shutdown)
    release.set()

    assert callback_finished.wait(timeout=2)
    assert running.result(timeout=1) == ("lamp-a", "white_brightness", (35,))
    assert queued.cancelled()
    assert callback_errors == []
    assert callback_stop_results == [False]
    assert scheduler.stop(timeout_seconds=2) is True


def test_start_is_idempotent_and_submission_after_shutdown_is_rejected():
    from smart_home_tray.command_scheduler import CommandScheduler

    manager = FakeDeviceManager()
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0)
    scheduler.start()
    scheduler.start()
    future = scheduler.submit_power("lamp-a", True)
    assert future.result(timeout=2) == ("lamp-a", "power", (True,))
    assert scheduler.stop(timeout_seconds=2) is True
    assert scheduler.stop(timeout_seconds=2) is True

    with pytest.raises(RuntimeError):
        scheduler.submit_power("lamp-a", False)
    with pytest.raises(RuntimeError):
        scheduler.start()


def test_invalid_device_is_rejected_without_exposing_manager_configuration():
    from smart_home_tray.command_scheduler import CommandScheduler

    manager = FakeDeviceManager(device_ids=("lamp-a",))
    manager.local_key = "secret-not-for-scheduler"
    scheduler = CommandScheduler(manager)
    scheduler.start()
    try:
        with pytest.raises(BackendError) as error:
            scheduler.submit_power("unknown", True)
        assert error.value.code is ErrorCode.INVALID_INPUT
        assert "secret-not-for-scheduler" not in repr(error.value)
    finally:
        scheduler.stop()


def test_real_manager_state_is_not_confirmed_on_enqueue_and_future_reports_readback():
    from smart_home_tray.command_scheduler import CommandScheduler

    clock = FakeClock()
    adapter = QueueLanAdapter(
        [
            {"20": False, "21": "colour", "24": "007803e803e8"},
            {"20": False, "21": "colour", "24": "007803e801f4"},
        ]
    )
    manager = real_manager(adapter, white=False)
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0.15, clock=clock)
    scheduler.start()
    try:
        future = scheduler.submit_color_brightness("lamp-a", 50)
        before_send = manager.get_device("lamp-a")
        assert not future.done()
        assert before_send.state.quality is DeviceStateQuality.UNKNOWN
        assert adapter.read_count == 0

        advance(clock, scheduler)
        result = future.result(timeout=2)
        assert result.state.quality is DeviceStateQuality.CONFIRMED
        assert result.state.color_value_percent == 50
        assert adapter.writes == [(24, "007803e801f4")]
        assert "scheduler-test-key-not-real" not in repr(result)
    finally:
        scheduler.stop()


def test_real_manager_reports_invalid_arguments_and_missing_capabilities_as_future_errors():
    from smart_home_tray.command_scheduler import CommandScheduler

    adapter = QueueLanAdapter([])
    manager = real_manager(adapter, color=False, white=False)
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0)
    scheduler.start()
    try:
        invalid = scheduler.submit_white_brightness("lamp-a", math.nan)
        unsupported = scheduler.submit_color_temperature("lamp-a", 50)

        with pytest.raises(BackendError) as invalid_error:
            invalid.result(timeout=2)
        with pytest.raises(BackendError) as unsupported_error:
            unsupported.result(timeout=2)

        assert invalid_error.value.code is ErrorCode.INVALID_INPUT
        assert unsupported_error.value.code is ErrorCode.UNSUPPORTED_CAPABILITY
        assert adapter.read_count == 0
        assert adapter.writes == []
    finally:
        scheduler.stop()


def test_scheduler_command_waits_for_device_manager_lock_held_by_polling_operation():
    from smart_home_tray.command_scheduler import CommandScheduler

    entered, release = threading.Event(), threading.Event()
    adapter = QueueLanAdapter(
        [
            {"20": False, "21": "white", "22": 505},
            {"20": False, "21": "white", "22": 703},
            {"20": False, "21": "white", "22": 703},
        ],
        first_read_entered=entered,
        release_first_read=release,
    )
    manager = real_manager(adapter, color=False)
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0)
    scheduler.start()
    polling_started = threading.Event()
    polling_done = threading.Event()

    try:
        command = scheduler.submit_white_brightness("lamp-a", 70)
        assert entered.wait(timeout=2)

        def poll():
            polling_started.set()
            manager.read_state("lamp-a")
            polling_done.set()

        poller = threading.Thread(target=poll)
        poller.start()
        assert polling_started.wait(timeout=2)
        assert adapter.read_count == 1

        release.set()
        assert command.result(timeout=2).state.white_brightness_percent == 70
        assert polling_done.wait(timeout=2)
        poller.join(timeout=2)
        assert not poller.is_alive()
        assert adapter.read_count == 3
    finally:
        release.set()
        scheduler.stop()
