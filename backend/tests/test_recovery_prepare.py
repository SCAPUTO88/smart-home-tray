from __future__ import annotations

from concurrent.futures import Future
import ipaddress
import threading
import time

import pytest

from smart_home_tray.command_scheduler import CommandScheduler
from smart_home_tray.config import AppConfig
from smart_home_tray.device_manager import DeviceManager
from smart_home_tray.discovery import DiscoveryAnnouncement
from smart_home_tray.models import DeviceConfig, DPSMap
from smart_home_tray.recovery import (
    DeviceManagerRecoveryCatalog,
    PreparationStatus,
    RecoveryService,
)
from smart_home_tray.recovery_proposals import ProposalBinding, ProposalStore, ProposalStoreStatus
from smart_home_tray.recovery_validation import CandidateValidator, ValidationResult, ValidationStatus
from smart_home_tray.recovery_validation import ValidationPublicationResult


DEVICE_ID = "synthetic-lamp"


class Provider:
    def __init__(self, *, hold=False):
        self.entered = threading.Event()
        self.release = threading.Event()
        if not hold:
            self.release.set()

    def discover(self, expected_device_id, *, timeout_seconds):
        self.entered.set()
        assert self.release.wait(timeout=3)
        return (DiscoveryAnnouncement(expected_device_id, "192.0.2.20", "3.5"),)


class StoreClock:
    def __init__(self):
        self.value = time.monotonic()

    def __call__(self):
        return self.value


def make_store(clock=None):
    entropy = iter(range(1, 256))
    return ProposalStore(
        clock=clock or StoreClock(),
        token_bytes=lambda size: bytes([next(entropy)]) * size,
    )


def make_manager(store, clock=time.monotonic):
    config = DeviceConfig(
        DEVICE_ID, "synthetic", "192.0.2.10", 3.5,
        "synthetic-key-123", DPSMap(power=20),
    )
    other = DeviceConfig(
        "lamp-b", "other synthetic", "192.0.2.30", 3.5,
        "synthetic-key-456", DPSMap(power=20),
    )
    third = DeviceConfig(
        "lamp-c", "third synthetic", "192.0.2.40", 3.5,
        "synthetic-key-789", DPSMap(power=20),
    )
    return DeviceManager(
        AppConfig((config, other, third)), adapter_factory=lambda _config: object(),
        proposal_store=store, recovery_clock=clock,
    )


def make_service(manager, provider, clock=time.monotonic):
    return RecoveryService(
        catalog=DeviceManagerRecoveryCatalog(manager), provider=provider, clock=clock
    )


def accepted_validator(monkeypatch, *, entered=None, release=None, status=ValidationStatus.KEY_AUTHENTICATED_READ):
    def validate(_self, *_args, **_kwargs):
        if entered is not None:
            entered.set()
        if release is not None:
            assert release.wait(timeout=3)
        return ValidationResult(status)
    monkeypatch.setattr(CandidateValidator, "validate", validate)


def test_prepare_internal_discovers_validates_and_publishes_only_internal_descriptor(monkeypatch):
    accepted_validator(monkeypatch)
    store = make_store()
    manager = make_manager(store)
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0)
    scheduler.start()
    recovery = make_service(manager, Provider())
    before_status = manager.get_device(DEVICE_ID)
    before_pending = dict(manager._pending_power)
    before_pending_fields = {key: dict(value) for key, value in manager._pending_fields.items()}
    before_last_fields = {key: dict(value) for key, value in manager._last_read_fields.items()}
    before_last_power = dict(manager._last_read_power)
    before_knowledge = before_status.state.knowledge
    before_adapter = manager._adapters[DEVICE_ID]
    try:
        result = recovery.prepare_internal(DEVICE_ID, scheduler)
        assert result.status is PreparationStatus.PROPOSAL_READY_INTERNAL
        assert result.proposal is not None
        assert result.proposal.device_id == DEVICE_ID
        assert result.proposal.candidate_address == ipaddress.IPv4Address("192.0.2.20")
        assert "synthetic-key" not in repr(result)
        assert store.lookup(result.proposal.token).status is ProposalStoreStatus.AVAILABLE
        assert manager.get_device(DEVICE_ID) == before_status
        assert manager.get_device(DEVICE_ID).state.knowledge == before_knowledge
        assert manager._pending_power == before_pending
        assert manager._pending_fields == before_pending_fields
        assert manager._last_read_fields == before_last_fields
        assert manager._last_read_power == before_last_power
        assert manager._adapters[DEVICE_ID] is before_adapter
        manager.update_address(DEVICE_ID, "192.0.2.11")
        manager.update_address(DEVICE_ID, "192.0.2.10")
        assert store.lookup(result.proposal.token).status is ProposalStoreStatus.NOT_FOUND
    finally:
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_pending_proposal_is_rejected_before_second_discovery(monkeypatch):
    accepted_validator(monkeypatch)
    store = make_store()
    manager = make_manager(store)
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0)
    scheduler.start()
    first_provider = Provider()
    first = make_service(manager, first_provider)
    second_provider = Provider()
    second = make_service(manager, second_provider)
    try:
        assert first.prepare_internal(DEVICE_ID, scheduler).status is PreparationStatus.PROPOSAL_READY_INTERNAL
        second_result = second.prepare_internal(DEVICE_ID, scheduler)
        assert second_result.status is PreparationStatus.PROPOSAL_PENDING
        assert not second_provider.entered.is_set()
    finally:
        first.close(timeout_seconds=1)
        second.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_service_shutdown_invalidates_existing_shared_token():
    store = make_store()
    manager = make_manager(store)
    recovery = make_service(manager, Provider())
    created = store.create_validated(ProposalBinding(
        DEVICE_ID, ipaddress.IPv4Address("192.0.2.20"), 3.5, 0, "192.0.2.10"
    ), owner=recovery._proposal_owner)
    assert created.descriptor is not None

    assert recovery.close(timeout_seconds=1) is True
    assert store.lookup(created.descriptor.token).status is ProposalStoreStatus.NOT_FOUND


@pytest.mark.parametrize("terminal", ["timeout", "closed"])
def test_late_future_collection_retracts_its_already_published_proposal(terminal):
    clock = StoreClock()
    store = make_store(clock)
    manager = make_manager(store, clock)
    recovery = make_service(manager, Provider(), clock)
    created = store.create_validated(ProposalBinding(
        DEVICE_ID, ipaddress.IPv4Address("192.0.2.20"), 3.5, 0, "192.0.2.10"
    ))
    assert created.descriptor is not None
    future = Future()
    future.set_result(ValidationPublicationResult(
        ValidationResult(ValidationStatus.KEY_AUTHENTICATED_READ),
        proposal=created.descriptor,
    ))
    deadline = clock() + 1
    if terminal == "timeout":
        clock.value += 1
    else:
        recovery._closing_event.set()

    result = recovery._await_prepare_future(future, deadline)

    assert result.status is (
        PreparationStatus.TIMEOUT if terminal == "timeout" else PreparationStatus.CLOSED
    )
    assert store.lookup(created.descriptor.token).status is ProposalStoreStatus.NOT_FOUND


def test_closing_one_service_preserves_other_instance_proposals_while_it_is_active(monkeypatch):
    validation_entered = threading.Event()
    release_validation = threading.Event()

    def validate(_self, _config, candidate, *, deadline):
        if candidate.device_id == "lamp-c":
            validation_entered.set()
            assert release_validation.wait(timeout=3)
        return ValidationResult(ValidationStatus.KEY_AUTHENTICATED_READ)

    monkeypatch.setattr(CandidateValidator, "validate", validate)
    store = make_store()
    manager = make_manager(store)
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0)
    scheduler.start()
    first = make_service(manager, Provider())
    second = make_service(manager, Provider())
    first_result = first.prepare_internal(DEVICE_ID, scheduler)
    second_result = second.prepare_internal("lamp-b", scheduler)
    assert first_result.proposal is not None and second_result.proposal is not None
    active_result = []
    active = threading.Thread(
        target=lambda: active_result.append(second.prepare_internal("lamp-c", scheduler))
    )
    active.start()
    try:
        assert validation_entered.wait(timeout=1)
        assert first.close(timeout_seconds=0) is False
        assert store.lookup(first_result.proposal.token).status is ProposalStoreStatus.NOT_FOUND
        assert store.lookup(second_result.proposal.token).status is ProposalStoreStatus.AVAILABLE
        release_validation.set()
        active.join(timeout=2)
        assert not active.is_alive()
        assert active_result[0].status is PreparationStatus.PROPOSAL_READY_INTERNAL
        assert store.lookup(second_result.proposal.token).status is ProposalStoreStatus.AVAILABLE
        assert store.lookup(active_result[0].proposal.token).status is ProposalStoreStatus.AVAILABLE
    finally:
        release_validation.set()
        first.close(timeout_seconds=1)
        second.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_configuration_change_during_udp_invalidates_snapshot_before_validation(monkeypatch):
    validation_calls = []
    monkeypatch.setattr(
        CandidateValidator, "validate",
        lambda *_args, **_kwargs: validation_calls.append(True),
    )
    store = make_store()
    manager = make_manager(store)
    provider = Provider(hold=True)
    recovery = make_service(manager, provider)
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0)
    scheduler.start()
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.prepare_internal(DEVICE_ID, scheduler)))
    caller.start()
    try:
        assert provider.entered.wait(timeout=1)
        manager.update_address(DEVICE_ID, "192.0.2.11")
        provider.release.set()
        caller.join(timeout=2)
        assert not caller.is_alive()
        assert result_box[0].status is PreparationStatus.CONFIG_CHANGED
        assert validation_calls == []
        assert store.pending_count == 0
    finally:
        provider.release.set()
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_configuration_change_while_validation_is_active_invalidates_published_result(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    accepted_validator(monkeypatch, entered=entered, release=release)
    store = make_store()
    manager = make_manager(store)
    recovery = make_service(manager, Provider())
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0)
    scheduler.start()
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.prepare_internal(DEVICE_ID, scheduler)))
    caller.start()
    update_started = threading.Event()
    update_done = threading.Event()
    updater = threading.Thread(target=lambda: (
        update_started.set(), manager.update_address(DEVICE_ID, "192.0.2.10"), update_done.set()
    ))
    try:
        assert entered.wait(timeout=1)
        updater.start()
        assert update_started.wait(timeout=1)
        release.set()
        caller.join(timeout=2)
        updater.join(timeout=2)
        assert not caller.is_alive() and not updater.is_alive()
        assert update_done.is_set()
        if result_box[0].proposal is not None:
            assert store.lookup(result_box[0].proposal.token).status is ProposalStoreStatus.NOT_FOUND
        assert store.pending_count == 0
    finally:
        release.set()
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


class BlockingControlProxy:
    def __init__(self, manager):
        self.manager = manager
        self.entered = threading.Event()
        self.release = threading.Event()
        self.other_control_done = threading.Event()

    def list_device_ids(self):
        return self.manager.list_device_ids()

    def set_power(self, device_id, *_args):
        if device_id == "lamp-b":
            self.other_control_done.set()
            return None
        self.entered.set()
        assert self.release.wait(timeout=3)
        return None

    def __getattr__(self, name):
        return getattr(self.manager, name)


def test_configuration_change_while_validation_waits_in_fifo_blocks_stale_turn(monkeypatch):
    validation_calls = []
    monkeypatch.setattr(
        CandidateValidator, "validate",
        lambda *_args, **_kwargs: validation_calls.append(True),
    )
    store = make_store()
    manager = make_manager(store)
    proxy = BlockingControlProxy(manager)
    scheduler = CommandScheduler(proxy, coalescing_window_seconds=0)
    scheduler.start()
    recovery = make_service(manager, Provider())
    control = scheduler.submit_power(DEVICE_ID, True)
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.prepare_internal(DEVICE_ID, scheduler)))
    caller.start()
    try:
        assert proxy.entered.wait(timeout=1)
        with scheduler._condition:
            assert scheduler._condition.wait_for(
                lambda: any(item.kind.value == "validate_recovery" for item in scheduler._queues[DEVICE_ID]),
                timeout=1,
            )
        manager.update_address(DEVICE_ID, "192.0.2.11")
        proxy.release.set()
        assert control.result(timeout=1) is None
        caller.join(timeout=2)
        assert not caller.is_alive()
        assert result_box[0].status is PreparationStatus.CONFIG_CHANGED
        assert validation_calls == []
        assert store.pending_count == 0
    finally:
        proxy.release.set()
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


@pytest.mark.parametrize("failure", [ValidationStatus.AUTH_FAILED, ValidationStatus.CLEANUP_FAILED])
def test_authentication_or_cleanup_failure_never_publishes(monkeypatch, failure):
    accepted_validator(monkeypatch, status=failure)
    store = make_store()
    manager = make_manager(store)
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0)
    scheduler.start()
    recovery = make_service(manager, Provider())
    try:
        result = recovery.prepare_internal(DEVICE_ID, scheduler)
        assert result.status is PreparationStatus.VALIDATION_FAILED
        assert result.proposal is None
        assert store.pending_count == 0
    finally:
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_shutdown_during_started_validation_suppresses_late_publication(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    accepted_validator(monkeypatch, entered=entered, release=release)
    store = make_store()
    manager = make_manager(store)
    recovery = make_service(manager, Provider())
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0)
    scheduler.start()
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.prepare_internal(DEVICE_ID, scheduler)))
    caller.start()
    try:
        assert entered.wait(timeout=1)
        assert recovery.close(timeout_seconds=0) is False
        assert store.pending_count == 0
        release.set()
        caller.join(timeout=2)
        assert not caller.is_alive()
        assert result_box[0].status is PreparationStatus.CLOSED
        assert store.pending_count == 0
    finally:
        release.set()
        scheduler.stop(timeout_seconds=1)


def test_deadline_expiring_during_started_validation_drains_without_late_publication(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    accepted_validator(monkeypatch, entered=entered, release=release)
    clock = StoreClock()
    store = make_store(clock)
    manager = make_manager(store, clock)
    recovery = make_service(manager, Provider(), clock)
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0, clock=clock)
    scheduler.start()
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.prepare_internal(DEVICE_ID, scheduler)))
    caller.start()
    try:
        assert entered.wait(timeout=1)
        clock.value += 6
        assert caller.is_alive()
        release.set()
        caller.join(timeout=2)
        assert not caller.is_alive()
        assert result_box[0].status is PreparationStatus.TIMEOUT
        assert store.pending_count == 0
    finally:
        release.set()
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_other_device_control_progresses_while_prepare_validation_is_active(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    accepted_validator(monkeypatch, entered=entered, release=release)
    store = make_store()
    manager = make_manager(store)
    proxy = BlockingControlProxy(manager)
    scheduler = CommandScheduler(proxy, coalescing_window_seconds=0)
    scheduler.start()
    recovery = make_service(manager, Provider())
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.prepare_internal(DEVICE_ID, scheduler)))
    caller.start()
    try:
        assert entered.wait(timeout=1)
        other = scheduler.submit_power("lamp-b", True)
        assert proxy.other_control_done.wait(timeout=1)
        assert other.result(timeout=1) is None
        release.set()
        caller.join(timeout=2)
        assert not caller.is_alive()
        assert result_box[0].status is PreparationStatus.PROPOSAL_READY_INTERNAL
    finally:
        release.set()
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_scheduler_shutdown_cancels_queued_prepare_as_closed_without_validation(monkeypatch):
    validation_calls = []
    monkeypatch.setattr(
        CandidateValidator, "validate",
        lambda *_args, **_kwargs: validation_calls.append(True),
    )
    store = make_store()
    manager = make_manager(store)
    proxy = BlockingControlProxy(manager)
    scheduler = CommandScheduler(proxy, coalescing_window_seconds=0)
    scheduler.start()
    recovery = make_service(manager, Provider())
    active = scheduler.submit_power(DEVICE_ID, True)
    assert proxy.entered.wait(timeout=1)
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.prepare_internal(DEVICE_ID, scheduler)))
    caller.start()
    try:
        with scheduler._condition:
            assert scheduler._condition.wait_for(
                lambda: any(item.kind.value == "validate_recovery" for item in scheduler._queues[DEVICE_ID]),
                timeout=1,
            )
        assert scheduler.stop(timeout_seconds=0) is False
        caller.join(timeout=1)
        assert not caller.is_alive()
        assert result_box[0].status is PreparationStatus.CLOSED
        assert validation_calls == []
        proxy.release.set()
        assert active.result(timeout=1) is None
        assert scheduler.stop(timeout_seconds=1) is True
        assert store.pending_count == 0
    finally:
        proxy.release.set()
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)



@pytest.mark.parametrize("stage", ["STAGE_LISTENER", "STAGE_INTERFACES", "STAGE_SEND", "STAGE_RECEIVE", "STAGE_LIMIT"])
def test_prepare_preserves_safe_discovery_stage_without_proposal(stage):
    from smart_home_tray.discovery import DiscoveryFailure, DiscoveryStageError
    from smart_home_tray.recovery import RecoveryFailure
    class FailedProvider:
        def discover(self, expected_device_id, *, timeout_seconds):
            raise DiscoveryStageError(DiscoveryFailure[stage], "private diagnostic")
    manager = make_manager(make_store())
    scheduler = CommandScheduler(manager, coalescing_window_seconds=0)
    scheduler.start()
    recovery = make_service(manager, FailedProvider())
    try:
        result = recovery.prepare_internal(DEVICE_ID, scheduler)
        assert result.status is PreparationStatus.DISCOVERY_FAILED
        assert result.failure is RecoveryFailure[stage]
        assert result.proposal is None
    finally:
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)
