from __future__ import annotations

import dataclasses
import threading

import pytest

from smart_home_tray.discovery import DiscoveryAnnouncement
from smart_home_tray.recovery import (
    DeviceManagerRecoveryCatalog,
    RecoveryStatus,
    RecoveryService,
)


DEVICE_ID = "synthetic-device-id"


class FakeCatalog:
    def __init__(self, protocols: dict[str, float] | None = None, error=None):
        self.protocols = protocols if protocols is not None else {DEVICE_ID: 3.5}
        self.error = error
        self.lookups: list[str] = []

    def protocol_version_for(self, device_id: str) -> float | None:
        self.lookups.append(device_id)
        if self.error is not None:
            raise self.error
        return self.protocols.get(device_id)


class FakeProvider:
    def __init__(self, announcements=(), error: Exception | None = None):
        self.announcements = announcements
        self.error = error
        self.calls: list[tuple[str, float]] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def discover(self, expected_device_id: str, *, timeout_seconds: float):
        self.calls.append((expected_device_id, timeout_seconds))
        self.entered.set()
        if not self.release.is_set():
            self.release.wait()
        if self.error is not None:
            raise self.error
        return self.announcements


def service(*, protocols=None, announcements=(), error=None, catalog_error=None):
    return RecoveryService(
        catalog=FakeCatalog(protocols, catalog_error),
        provider=FakeProvider(announcements, error),
    )


def ann(address: str, device_id: str = DEVICE_ID, version: str = "3.5"):
    return DiscoveryAnnouncement(device_id, address, version)


def test_protocol_33_is_rejected_before_discovery_provider_is_called():
    recovery = service(protocols={DEVICE_ID: 3.3}, announcements=(ann("192.0.2.10"),))

    result = recovery.discover_for_recovery(DEVICE_ID)

    assert result.status is RecoveryStatus.PROTOCOL_NOT_ELIGIBLE
    assert recovery._provider.calls == []


def test_close_reports_incomplete_until_active_validation_finishes_and_suppresses_result(monkeypatch):
    import ipaddress
    import time
    from smart_home_tray.command_scheduler import CommandScheduler
    from smart_home_tray.config import AppConfig
    from smart_home_tray.device_manager import DeviceManager
    from smart_home_tray.models import DeviceConfig, DPSMap
    from smart_home_tray.recovery import RecoveryCandidate
    from smart_home_tray.recovery_validation import CandidateValidator, ValidationResult, ValidationStatus

    entered = threading.Event()
    release = threading.Event()

    def validate(self, *_args, **_kwargs):
        entered.set()
        assert release.wait(timeout=3)
        return ValidationResult(ValidationStatus.KEY_AUTHENTICATED_READ)

    monkeypatch.setattr(CandidateValidator, "validate", validate)

    config = DeviceConfig(DEVICE_ID, "synthetic", "192.0.2.10", 3.5, "synthetic-key", DPSMap(power=20))
    manager = DeviceManager(AppConfig((config,)))
    recovery = RecoveryService(catalog=DeviceManagerRecoveryCatalog(manager), provider=FakeProvider())
    scheduler = CommandScheduler(manager)
    scheduler.start()
    candidate = RecoveryCandidate(DEVICE_ID, ipaddress.IPv4Address("192.0.2.11"), ("3.5",))
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery._validate_candidate(
        DEVICE_ID, candidate, scheduler, deadline=time.monotonic() + 3
    )))
    caller.start()
    assert entered.wait(timeout=1)
    assert recovery.close(timeout_seconds=0) is False
    release.set()
    caller.join(timeout=1)
    assert not caller.is_alive()
    assert result_box[0].status is ValidationStatus.CLOSED
    assert recovery.close(timeout_seconds=1) is True
    assert scheduler.stop(timeout_seconds=1)


def test_discovery_rechecks_closed_after_global_slot_admission(monkeypatch):
    from smart_home_tray import recovery as recovery_module

    acquisition_entered = threading.Event()
    allow_acquisition = threading.Event()

    class PausingLock:
        def __init__(self):
            self._lock = threading.Lock()
            self._paused = False

        def acquire(self, *args, **kwargs):
            if threading.current_thread().name == "discovery-race" and not self._paused:
                self._paused = True
                acquisition_entered.set()
                assert allow_acquisition.wait(timeout=3)
            return self._lock.acquire(*args, **kwargs)

        def release(self):
            self._lock.release()

    provider = FakeProvider(announcements=(ann("192.0.2.10"),))
    recovery = RecoveryService(catalog=FakeCatalog(), provider=provider)
    monkeypatch.setattr(recovery_module, "_PROCESS_RECOVERY_LOCK", PausingLock())
    result_box = []
    discoverer = threading.Thread(
        name="discovery-race",
        target=lambda: result_box.append(recovery.discover_for_recovery(DEVICE_ID)),
    )
    discoverer.start()
    assert acquisition_entered.wait(timeout=1)

    assert recovery.close(timeout_seconds=0) is True
    allow_acquisition.set()
    discoverer.join(timeout=1)

    assert not discoverer.is_alive()
    assert result_box[0].status is RecoveryStatus.INVALID_REQUEST
    assert provider.calls == []


class ManualClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, amount):
        self.value += amount


class CoordinatedManager:
    def __init__(self):
        self.device_ids = ("lamp-a", "lamp-b")
        self.validation_entered = threading.Event()
        self.release_validation = threading.Event()
        self.control_entered = threading.Event()
        self.release_control = threading.Event()
        self.other_control_done = threading.Event()
        self.validation_calls = 0

    def list_device_ids(self):
        return self.device_ids

    def _recovery_snapshot(self, device_id, *, deadline):
        from types import SimpleNamespace
        return SimpleNamespace(revision=4)

    def set_power(self, device_id, enabled):
        if device_id == "lamp-a":
            self.control_entered.set()
            assert self.release_control.wait(timeout=3)
        else:
            self.other_control_done.set()
        return (device_id, enabled)

    def _validate_recovery_candidate(self, device_id, revision, candidate, *, deadline):
        from smart_home_tray.recovery_validation import ValidationResult, ValidationStatus
        self.validation_calls += 1
        self.validation_entered.set()
        assert self.release_validation.wait(timeout=3)
        return ValidationResult(ValidationStatus.KEY_AUTHENTICATED_READ)


def _coordinator(manager, clock):
    class Catalog:
        _device_manager = manager

        def protocol_version_for(self, device_id):
            return 3.5

    return RecoveryService(catalog=Catalog(), provider=FakeProvider(), clock=clock)


def _candidate_for_lamp_a():
    import ipaddress
    from smart_home_tray.recovery import RecoveryCandidate
    return RecoveryCandidate("lamp-a", ipaddress.IPv4Address("192.0.2.20"), ("3.5",))


def _wait_for_recovery_queue(scheduler):
    with scheduler._condition:
        assert scheduler._condition.wait_for(
            lambda: bool(scheduler._queues["lamp-a"]), timeout=1
        )


def test_validation_expiring_in_fifo_is_cancelled_without_late_execution():
    import time
    from smart_home_tray.command_scheduler import CommandScheduler
    from smart_home_tray.recovery_validation import ValidationStatus

    manager = CoordinatedManager()
    clock = ManualClock(time.monotonic())
    recovery = _coordinator(manager, clock)
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0)
    scheduler.start()
    caller_done = threading.Event()
    result_box = []
    try:
        active_control = scheduler.submit_power("lamp-a", True)
        assert manager.control_entered.wait(timeout=1)
        deadline = clock() + 5
        caller = threading.Thread(target=lambda: (
            result_box.append(recovery._validate_candidate(
                "lamp-a", _candidate_for_lamp_a(), scheduler, deadline=deadline
            )), caller_done.set()
        ))
        caller.start()
        _wait_for_recovery_queue(scheduler)
        clock.advance(6)
        assert caller_done.wait(timeout=1)
        assert result_box[0].status is ValidationStatus.TIMEOUT
        assert manager.validation_calls == 0
        manager.release_control.set()
        assert active_control.result(timeout=1) == ("lamp-a", True)
        caller.join(timeout=1)
        assert not caller.is_alive()
        assert manager.validation_calls == 0
    finally:
        manager.release_control.set()
        manager.release_validation.set()
        scheduler.stop(timeout_seconds=1)


def test_expired_started_validation_keeps_slot_until_real_completion_and_other_device_progresses():
    import time
    from smart_home_tray.command_scheduler import CommandScheduler
    from smart_home_tray.recovery_validation import ValidationStatus

    manager = CoordinatedManager()
    clock = ManualClock(time.monotonic())
    recovery = _coordinator(manager, clock)
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0)
    scheduler.start()
    caller_done = threading.Event()
    result_box = []
    try:
        deadline = clock() + 5
        caller = threading.Thread(target=lambda: (
            result_box.append(recovery._validate_candidate(
                "lamp-a", _candidate_for_lamp_a(), scheduler, deadline=deadline
            )), caller_done.set()
        ))
        caller.start()
        assert manager.validation_entered.wait(timeout=1)
        other_device = scheduler.submit_power("lamp-b", True)
        assert manager.other_control_done.wait(timeout=1)
        assert other_device.result(timeout=1) == ("lamp-b", True)

        clock.advance(6)
        assert caller_done.wait(timeout=0.1) is False
        busy = recovery._validate_candidate(
            "lamp-a", _candidate_for_lamp_a(), scheduler, deadline=clock() + 5
        )
        assert busy.status is ValidationStatus.BUSY

        manager.release_validation.set()
        assert caller_done.wait(timeout=1)
        caller.join(timeout=1)
        assert result_box[0].status is ValidationStatus.TIMEOUT
        assert not caller.is_alive()
    finally:
        manager.release_validation.set()
        scheduler.stop(timeout_seconds=1)


def test_scheduler_shutdown_cancellation_returns_closed_for_queued_validation():
    import time
    from smart_home_tray.command_scheduler import CommandScheduler
    from smart_home_tray.recovery_validation import ValidationStatus

    manager = CoordinatedManager()
    clock = ManualClock(time.monotonic())
    recovery = _coordinator(manager, clock)
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0)
    scheduler.start()
    result_box = []
    caller_done = threading.Event()
    try:
        active_control = scheduler.submit_power("lamp-a", True)
        assert manager.control_entered.wait(timeout=1)
        caller = threading.Thread(target=lambda: (
            result_box.append(recovery._validate_candidate(
                "lamp-a", _candidate_for_lamp_a(), scheduler, deadline=clock() + 5
            )), caller_done.set()
        ))
        caller.start()
        _wait_for_recovery_queue(scheduler)
        assert scheduler.stop(timeout_seconds=0) is False
        assert caller_done.wait(timeout=1)
        caller.join(timeout=1)
        assert result_box[0].status is ValidationStatus.CLOSED
        assert manager.validation_calls == 0
        manager.release_control.set()
        assert active_control.result(timeout=1) == ("lamp-a", True)
        assert scheduler.stop(timeout_seconds=1) is True
    finally:
        manager.release_control.set()
        manager.release_validation.set()
        scheduler.stop(timeout_seconds=1)


def test_unknown_device_does_not_start_discovery():
    recovery = service(protocols={})

    result = recovery.discover_for_recovery(DEVICE_ID)

    assert result.status is RecoveryStatus.DEVICE_NOT_FOUND
    assert recovery._provider.calls == []


def test_single_candidate_is_explicitly_unverified_and_contains_only_allowlisted_fields():
    recovery = service(announcements=(ann("192.0.2.10"),))

    result = recovery.discover_for_recovery(DEVICE_ID)

    assert result.status is RecoveryStatus.CANDIDATE_UNVERIFIED
    assert len(result.candidates) == 1
    assert str(result.candidates[0].address) == "192.0.2.10"
    assert result.candidates[0].announced_versions == ("3.5",)
    assert {field.name for field in dataclasses.fields(result)} == {
        "status", "candidates", "failure", "wait_diagnostic"
    }
    assert {field.name for field in dataclasses.fields(result.candidates[0])} == {
        "device_id", "address", "announced_versions"
    }
    assert not hasattr(result, "proposal_id")


def test_single_candidate_announcing_only_protocol_35_remains_unverified():
    recovery = service(announcements=(ann("192.0.2.10", version="3.5"),))

    result = recovery.discover_for_recovery(DEVICE_ID)

    assert result.status is RecoveryStatus.CANDIDATE_UNVERIFIED
    assert result.candidates[0].announced_versions == ("3.5",)


def test_single_candidate_announcing_only_protocol_33_is_not_recovery_eligible():
    recovery = service(announcements=(ann("192.0.2.10", version="3.3"),))

    result = recovery.discover_for_recovery(DEVICE_ID)

    assert result.status is RecoveryStatus.PROTOCOL_NOT_ELIGIBLE
    assert result.candidates == ()


@pytest.mark.parametrize(
    "versions",
    [("3.3", "3.5"), (None,)],
    ids=("conflicting-claims", "missing-version"),
)
def test_single_candidate_with_conflicting_or_missing_versions_is_ineligible(versions):
    recovery = service(
        announcements=tuple(ann("192.0.2.10", version=version) for version in versions)
    )

    result = recovery.discover_for_recovery(DEVICE_ID)

    assert result.status is RecoveryStatus.PROTOCOL_NOT_ELIGIBLE
    assert result.candidates == ()


def test_ambiguous_candidates_remain_ambiguous_across_protocol_claims():
    recovery = service(
        announcements=(ann("192.0.2.10", version="3.5"), ann("192.0.2.11", version="3.3"))
    )

    result = recovery.discover_for_recovery(DEVICE_ID)

    assert result.status is RecoveryStatus.AMBIGUOUS
    assert tuple(str(candidate.address) for candidate in result.candidates) == (
        "192.0.2.10", "192.0.2.11"
    )


def test_no_announcement_maps_to_not_found():
    assert service().discover_for_recovery(DEVICE_ID).status is RecoveryStatus.NOT_FOUND


def test_distinct_addresses_remain_ambiguous():
    recovery = service(announcements=(ann("192.0.2.10"), ann("192.0.2.11")))

    result = recovery.discover_for_recovery(DEVICE_ID)

    assert result.status is RecoveryStatus.AMBIGUOUS
    assert tuple(str(candidate.address) for candidate in result.candidates) == (
        "192.0.2.10", "192.0.2.11"
    )


def test_duplicate_announcements_normalize_to_one_candidate():
    recovery = service(announcements=(ann("192.0.2.10"), ann("192.0.2.10")))

    result = recovery.discover_for_recovery(DEVICE_ID)

    assert result.status is RecoveryStatus.CANDIDATE_UNVERIFIED
    assert len(result.candidates) == 1


def test_provider_ignores_other_device_ids_via_f2b_normalization():
    recovery = service(announcements=(ann("192.0.2.99", "other-synthetic-id"),))

    assert recovery.discover_for_recovery(DEVICE_ID).status is RecoveryStatus.NOT_FOUND


def test_provider_timeout_is_distinct_and_safe():
    recovery = service(error=TimeoutError("private details must not escape"))

    result = recovery.discover_for_recovery(DEVICE_ID)

    assert result.status is RecoveryStatus.TIMEOUT
    assert result.failure is None
    assert "private details" not in repr(result)


def test_provider_error_and_truncated_collection_fail_closed():
    for error in (RuntimeError("private detail"), OverflowError("collection truncated")):
        result = service(error=error).discover_for_recovery(DEVICE_ID)
        assert result.status is RecoveryStatus.DISCOVERY_FAILED
        assert result.candidates == ()
        assert result.failure is not None
        assert "private" not in repr(result)
        assert "truncated" not in repr(result)


def test_invalid_request_and_timeout_are_rejected_before_catalog_or_provider():
    recovery = service()

    invalid_id = recovery.discover_for_recovery(" ")
    invalid_timeout = recovery.discover_for_recovery(DEVICE_ID, timeout_seconds=0)

    assert invalid_id.status is RecoveryStatus.INVALID_REQUEST
    assert invalid_timeout.status is RecoveryStatus.INVALID_REQUEST
    assert recovery._catalog.lookups == []
    assert recovery._provider.calls == []


def test_catalog_failure_is_normalized_without_raw_exception():
    recovery = service(catalog_error=RuntimeError("private catalog detail"))

    result = recovery.discover_for_recovery(DEVICE_ID)

    assert result.status is RecoveryStatus.CATALOG_FAILED
    assert result.candidates == ()
    assert "private catalog" not in repr(result)
    assert recovery._provider.calls == []


def test_global_slot_returns_busy_and_is_released_after_provider_failure():
    provider = FakeProvider(error=RuntimeError("provider failure"))
    first = RecoveryService(catalog=FakeCatalog(), provider=provider)
    second = RecoveryService(
        catalog=FakeCatalog({"other-synthetic-id": 3.5}),
        provider=FakeProvider(),
    )
    provider.release.set()

    failed = first.discover_for_recovery(DEVICE_ID)
    after_error = second.discover_for_recovery("other-synthetic-id")

    assert failed.status is RecoveryStatus.DISCOVERY_FAILED
    assert after_error.status is RecoveryStatus.NOT_FOUND
    assert len(second._provider.calls) == 1


def test_global_slot_is_released_when_operation_is_interrupted():
    interrupted = RecoveryService(
        catalog=FakeCatalog(),
        provider=FakeProvider(error=KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        interrupted.discover_for_recovery(DEVICE_ID)

    assert service().discover_for_recovery(DEVICE_ID).status is RecoveryStatus.NOT_FOUND


def test_concurrent_recovery_is_busy_without_blocking_other_device_work():
    provider = FakeProvider(announcements=(ann("192.0.2.10"),))
    provider.release.clear()
    first = RecoveryService(catalog=FakeCatalog(), provider=provider)
    other_provider = FakeProvider()
    second = RecoveryService(
        catalog=FakeCatalog({"other-synthetic-id": 3.5}),
        provider=other_provider,
    )
    first_result = []
    worker = threading.Thread(target=lambda: first_result.append(first.discover_for_recovery(DEVICE_ID)))
    worker.start()
    assert provider.entered.wait(timeout=1)

    busy = second.discover_for_recovery("other-synthetic-id")
    provider.release.set()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert busy.status is RecoveryStatus.BUSY
    assert other_provider.calls == []
    assert first_result[0].status is RecoveryStatus.CANDIDATE_UNVERIFIED
    assert second.discover_for_recovery("other-synthetic-id").status is RecoveryStatus.NOT_FOUND


def test_no_status_write_or_address_adoption_method_is_required_or_called():
    class PublicManagerFake:
        def list_device_ids(self):
            return (DEVICE_ID,)

        def get_device(self, device_id):
            assert device_id == DEVICE_ID
            return type("PublicStatus", (), {"protocol_version": 3.5})()

        def read_state(self, *_args):
            raise AssertionError("D.1 must not read device status over TCP")

        def open_session(self, *_args):
            raise AssertionError("D.1 must not open a device session")

        def write_dps(self, *_args):
            raise AssertionError("D.1 must not write DPS")

        def update_address(self, *_args):
            raise AssertionError("D.1 must not adopt an address")

    provider = FakeProvider(announcements=(ann("192.0.2.10"),))
    recovery = RecoveryService(
        catalog=DeviceManagerRecoveryCatalog(PublicManagerFake()),
        provider=provider,
    )

    result = recovery.discover_for_recovery(DEVICE_ID)

    assert result.status is RecoveryStatus.CANDIDATE_UNVERIFIED
    assert provider.calls == [(DEVICE_ID, 3.0)]


def test_requested_timeout_is_bounded_by_the_lan_discovery_cap():
    recovery = service()

    recovery.discover_for_recovery(DEVICE_ID, timeout_seconds=25)

    assert recovery._provider.calls == [(DEVICE_ID, 3.0)]


def test_short_timeout_is_forwarded_without_being_extended():
    recovery = service()

    recovery.discover_for_recovery(DEVICE_ID, timeout_seconds=0.2)

    assert recovery._provider.calls == [(DEVICE_ID, 0.2)]


def test_device_manager_catalog_reads_only_protocol_from_public_status():
    class PublicManagerFake:
        def __init__(self):
            self.lookups = []

        def list_device_ids(self):
            return (DEVICE_ID,)

        def get_device(self, device_id):
            self.lookups.append(device_id)
            return type("PublicStatus", (), {"protocol_version": 3.5})()

        def read_state(self, *_args):
            raise AssertionError("catalog eligibility must not open a device session")

        def update_address(self, *_args):
            raise AssertionError("D.1 must not adopt an address")

        def set_power(self, *_args):
            raise AssertionError("D.1 must not write a device")

    manager = PublicManagerFake()
    catalog = DeviceManagerRecoveryCatalog(manager)

    assert catalog.protocol_version_for(DEVICE_ID) == 3.5
    assert catalog.protocol_version_for("missing-synthetic-id") is None
    assert manager.lookups == [DEVICE_ID]


def test_discovery_stage_survives_preparation_mapping():
    from smart_home_tray.recovery import RecoveryFailure, RecoveryResult, RecoveryService, RecoveryStatus, PreparationStatus
    result = RecoveryService._preparation_from_discovery(RecoveryResult(RecoveryStatus.DISCOVERY_FAILED, failure=RecoveryFailure.STAGE_INTERFACES))
    assert result.status is PreparationStatus.DISCOVERY_FAILED
    assert result.failure is RecoveryFailure.STAGE_INTERFACES
    assert result.proposal is None
