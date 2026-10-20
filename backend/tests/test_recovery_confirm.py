from __future__ import annotations

from concurrent.futures import Future
import ipaddress
import threading
import time
from dataclasses import replace

import pytest

from smart_home_tray.command_scheduler import CommandScheduler
from smart_home_tray.config import AppConfig
from smart_home_tray.device_manager import DeviceManager
from smart_home_tray.discovery import DiscoveryAnnouncement
from smart_home_tray.models import (
    BackendError,
    ConnectionStatus,
    DeviceConfig,
    FieldKnowledge,
    DeviceStateQuality,
    DPSMap,
    ErrorCode,
)
from smart_home_tray.recovery import (
    ConfirmationStatus,
    DeviceManagerRecoveryCatalog,
    PreparationStatus,
    ReadbackStatus,
    RecoveryService,
)
from smart_home_tray.recovery_proposals import ProposalBinding, ProposalStore, ProposalStoreStatus
from smart_home_tray.recovery_validation import CandidateValidator, ValidationResult, ValidationStatus


DEVICE_ID = "confirm-lamp"
OLD_ADDRESS = "192.0.2.10"
CANDIDATE_ADDRESS = ipaddress.IPv4Address("192.0.2.20")


class FakeClock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value


class Provider:
    def discover(self, expected_device_id, *, timeout_seconds):
        return (DiscoveryAnnouncement(expected_device_id, str(CANDIDATE_ADDRESS), "3.5"),)


class FakeAdapter:
    def __init__(self, *, dps=None, close_error=None, read_error=None):
        self.dps = {"20": True} if dps is None else dps
        self.close_error = close_error
        self.read_error = read_error
        self.close_calls = 0
        self.unusable = False

    def close(self):
        self.close_calls += 1
        self.unusable = True
        if self.close_error:
            raise self.close_error

    def read_status(self):
        if self.unusable:
            raise BackendError(ErrorCode.DEVICE_ERROR, "Device adapter is unavailable")
        if self.read_error:
            raise self.read_error
        return dict(self.dps)

    def write_dps(self, *_args):
        if self.unusable:
            raise BackendError(ErrorCode.DEVICE_ERROR, "Device adapter is unavailable")


def make_environment(
    monkeypatch, *, validation_statuses=None, clock=None, factory=None,
    blocking_scheduler=False,
):
    clock = clock or FakeClock()
    entropy = iter(range(1, 255))
    store = ProposalStore(
        clock=clock,
        token_bytes=lambda size: bytes([next(entropy)]) * size,
    )
    config = DeviceConfig(
        DEVICE_ID, "synthetic", OLD_ADDRESS, 3.5, "synthetic-local-key",
        DPSMap(power=20),
    )
    other = DeviceConfig(
        "lamp-b", "other synthetic", "192.0.2.30", 3.5,
        "other-synthetic-local-key", DPSMap(power=20),
    )
    adapters = []

    def default_factory(_config):
        adapter = FakeAdapter()
        adapters.append(adapter)
        return adapter

    manager = DeviceManager(
        AppConfig((config, other)),
        proposal_store=store,
        recovery_clock=clock,
        adapter_factory=factory or default_factory,
    )
    statuses = list(validation_statuses or [ValidationStatus.KEY_AUTHENTICATED_READ] * 10)
    calls = []

    def validate(_self, candidate_config, candidate, *, deadline):
        calls.append((candidate_config.address, candidate.address, deadline))
        status = statuses.pop(0) if statuses else ValidationStatus.KEY_AUTHENTICATED_READ
        return ValidationResult(status)

    monkeypatch.setattr(CandidateValidator, "validate", validate)
    recovery = RecoveryService(
        catalog=DeviceManagerRecoveryCatalog(manager), provider=Provider(), clock=clock
    )
    scheduler_manager = BlockingSchedulerProxy(manager) if blocking_scheduler else manager
    if blocking_scheduler:
        scheduler_manager.release.clear()
    scheduler = CommandScheduler(scheduler_manager, coalescing_window_seconds=0, clock=clock)
    scheduler.start()
    return clock, store, manager, recovery, scheduler, adapters, calls


class BlockingSchedulerProxy:
    def __init__(self, manager):
        self.manager = manager
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def list_device_ids(self):
        return self.manager.list_device_ids()

    def set_power(self, device_id, enabled):
        if device_id == DEVICE_ID and not self.release.is_set():
            self.entered.set()
            assert self.release.wait(timeout=3)
        return self.manager.get_device(device_id)

    def __getattr__(self, name):
        return getattr(self.manager, name)


def wait_for_confirmation_queued(scheduler):
    with scheduler._condition:
        assert scheduler._condition.wait_for(
            lambda: any(
                item.kind.value == "confirm_recovery"
                for item in scheduler._queues[DEVICE_ID]
            ),
            timeout=1,
        )


def issue_proposal(store, recovery, *, revision=0):
    created = store.create_validated(
        ProposalBinding(
            DEVICE_ID, CANDIDATE_ADDRESS, 3.5, revision, OLD_ADDRESS
        ),
        owner=recovery._proposal_owner,
    )
    assert created.status is ProposalStoreStatus.CREATED
    assert created.descriptor is not None
    return created.descriptor


def test_prepare_token_confirms_with_second_validation_and_address_only_adoption(monkeypatch):
    clock, store, manager, recovery, scheduler, adapters, validation_calls = make_environment(monkeypatch)
    old_adapter = FakeAdapter(dps={"20": False})
    manager._adapters[DEVICE_ID] = old_adapter
    manager._pending_power[DEVICE_ID] = False
    manager._pending_fields[DEVICE_ID] = {"work_mode": "colour"}
    previous_status = manager._states[DEVICE_ID]
    manager._states[DEVICE_ID] = replace(
        previous_status,
        state=replace(previous_status.state, quality=DeviceStateQuality.PENDING),
    )
    try:
        prepared = recovery.prepare_internal(DEVICE_ID, scheduler)
        assert prepared.status is PreparationStatus.PROPOSAL_READY_INTERNAL
        assert prepared.proposal is not None
        old_config = manager._configs[DEVICE_ID]

        result = recovery.confirm_internal(prepared.proposal.token, scheduler)

        assert result.status is ConfirmationStatus.ADOPTED
        assert result.readback_status is ReadbackStatus.SUCCEEDED
        assert result.readback is not None
        assert len(validation_calls) == 2
        adopted = manager._configs[DEVICE_ID]
        assert adopted.address == str(CANDIDATE_ADDRESS)
        assert adopted.device_id == old_config.device_id
        assert adopted.local_key == old_config.local_key
        assert adopted.protocol_version == old_config.protocol_version
        assert adopted.dps == old_config.dps
        assert adopted.capabilities == old_config.capabilities
        assert manager._config_revisions[DEVICE_ID] == 1
        assert old_adapter.close_calls == 1
        assert manager._pending_power == {DEVICE_ID: False}
        assert manager._pending_fields == {DEVICE_ID: {"work_mode": "colour"}}
        assert result.readback.connection is ConnectionStatus.ONLINE
        assert result.readback.state.quality is DeviceStateQuality.PENDING
        assert store.lookup(prepared.proposal.token).status is ProposalStoreStatus.NOT_FOUND
        with pytest.raises(TypeError):
            recovery.confirm_internal(prepared.proposal.token, scheduler, address="198.51.100.7")
    finally:
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_failed_second_authentication_consumes_token_without_adoption(monkeypatch):
    _, store, manager, recovery, scheduler, _, calls = make_environment(
        monkeypatch,
        validation_statuses=[ValidationStatus.KEY_AUTHENTICATED_READ, ValidationStatus.AUTH_FAILED],
    )
    try:
        prepared = recovery.prepare_internal(DEVICE_ID, scheduler)
        assert prepared.proposal is not None
        result = recovery.confirm_internal(prepared.proposal.token, scheduler)

        assert result.status is ConfirmationStatus.AUTH_FAILED
        assert result.readback_status is None
        assert manager._configs[DEVICE_ID].address == OLD_ADDRESS
        assert manager._config_revisions[DEVICE_ID] == 0
        assert store.lookup(prepared.proposal.token).status is ProposalStoreStatus.NOT_FOUND
        assert len(calls) == 2
    finally:
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_adapter_cleanup_failure_aborts_commit_and_never_reuses_poisoned_adapter(monkeypatch):
    _, _, manager, recovery, scheduler, _, _ = make_environment(monkeypatch)
    broken = FakeAdapter(close_error=OSError("secret cleanup failure"))
    manager._adapters[DEVICE_ID] = broken
    token = issue_proposal(manager._proposal_store, recovery)
    try:
        result = recovery.confirm_internal(token.token, scheduler)

        assert result.status is ConfirmationStatus.CLEANUP_FAILED
        assert manager._configs[DEVICE_ID].address == OLD_ADDRESS
        assert manager._config_revisions[DEVICE_ID] == 0
        assert manager._adapters[DEVICE_ID] is broken
        with pytest.raises(BackendError):
            broken.read_status()
        assert manager._proposal_store.lookup(token.token).status is ProposalStoreStatus.NOT_FOUND
    finally:
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_readback_failure_does_not_change_committed_adoption(monkeypatch):
    def factory(_config):
        return FakeAdapter(read_error=BackendError(ErrorCode.DEVICE_OFFLINE, "offline"))

    _, _, manager, recovery, scheduler, _, _ = make_environment(monkeypatch, factory=factory)
    token = issue_proposal(manager._proposal_store, recovery)
    try:
        result = recovery.confirm_internal(token.token, scheduler)

        assert result.status is ConfirmationStatus.ADOPTED
        assert result.readback_status is ReadbackStatus.FAILED
        assert result.readback_error is ErrorCode.DEVICE_OFFLINE
        assert manager._configs[DEVICE_ID].address == str(CANDIDATE_ADDRESS)
        assert manager._config_revisions[DEVICE_ID] == 1
    finally:
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_commit_invalidates_old_knowledge_before_separate_readback(monkeypatch):
    _, store, manager, recovery, scheduler, _, _ = make_environment(monkeypatch)
    manager.read_state(DEVICE_ID)
    old_state = manager.get_device(DEVICE_ID).state
    assert old_state.knowledge.power is FieldKnowledge.OBSERVED
    token = issue_proposal(store, recovery)
    entered, release = threading.Event(), threading.Event()
    original_readback = manager._read_state_for_recovery_revision

    def blocked_readback(device_id, expected_revision):
        entered.set()
        assert release.wait(timeout=3)
        return original_readback(device_id, expected_revision)

    monkeypatch.setattr(manager, "_read_state_for_recovery_revision", blocked_readback)
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.confirm_internal(token.token, scheduler)))
    caller.start()
    try:
        assert entered.wait(timeout=1)
        adopted_status = manager.get_device(DEVICE_ID)
        assert adopted_status.connection is ConnectionStatus.UNKNOWN
        assert adopted_status.state.power == old_state.power
        assert adopted_status.state.knowledge.power is FieldKnowledge.UNKNOWN
        release.set()
        caller.join(timeout=2)
        assert not caller.is_alive()
        assert result_box[0].status is ConfirmationStatus.ADOPTED
    finally:
        release.set()
        caller.join(timeout=1)
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_token_claim_is_owner_scoped_across_recovery_instances(monkeypatch):
    _, store, manager, first, scheduler, _, _ = make_environment(monkeypatch)
    second = RecoveryService(
        catalog=DeviceManagerRecoveryCatalog(manager), provider=Provider()
    )
    token = issue_proposal(store, first)
    try:
        rejected = second.confirm_internal(token.token, scheduler)

        assert rejected.status is ConfirmationStatus.PROPOSAL_UNAVAILABLE
        assert store.lookup(token.token).status is ProposalStoreStatus.AVAILABLE
        accepted = first.confirm_internal(token.token, scheduler)
        assert accepted.status is ConfirmationStatus.ADOPTED
    finally:
        first.close(timeout_seconds=1)
        second.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_confirmation_rechecks_lifecycle_after_acquiring_global_slot(monkeypatch):
    import smart_home_tray.recovery as recovery_module

    _, store, _, recovery, scheduler, _, _ = make_environment(monkeypatch)
    token = issue_proposal(store, recovery)

    class ClosingSlot:
        def acquire(self, *, blocking):
            assert blocking is False
            with recovery._lifecycle_lock:
                recovery._closed = True
                recovery._closing_event.set()
            return True

        def release(self):
            return None

    monkeypatch.setattr(recovery_module, "_PROCESS_RECOVERY_LOCK", ClosingSlot())
    try:
        result = recovery.confirm_internal(token.token, scheduler)

        assert result.status is ConfirmationStatus.CLOSED
        assert store.lookup(token.token).status is ProposalStoreStatus.AVAILABLE
    finally:
        scheduler.stop(timeout_seconds=1)


def test_replay_cannot_claim_or_adopt_the_same_proposal_twice(monkeypatch):
    _, store, manager, recovery, scheduler, _, _ = make_environment(monkeypatch)
    token = issue_proposal(store, recovery)
    entered, release = threading.Event(), threading.Event()

    def validate(_self, *_args, **_kwargs):
        entered.set()
        assert release.wait(timeout=3)
        return ValidationResult(ValidationStatus.KEY_AUTHENTICATED_READ)

    monkeypatch.setattr(CandidateValidator, "validate", validate)
    first_result = []
    first = threading.Thread(
        target=lambda: first_result.append(recovery.confirm_internal(token.token, scheduler))
    )
    first.start()
    try:
        assert entered.wait(timeout=1)
        assert recovery.confirm_internal(token.token, scheduler).status is ConfirmationStatus.BUSY
        release.set()
        first.join(timeout=2)
        assert not first.is_alive()
        replay = recovery.confirm_internal(token.token, scheduler)

        assert first_result[0].status is ConfirmationStatus.ADOPTED
        assert replay.status is ConfirmationStatus.PROPOSAL_UNAVAILABLE
        assert manager._config_revisions[DEVICE_ID] == 1
    finally:
        release.set()
        first.join(timeout=1)
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_proposal_expiring_while_queued_is_consumed_without_late_validation(monkeypatch):
    clock = FakeClock()
    _, store, manager, recovery, scheduler, _, calls = make_environment(
        monkeypatch, clock=clock, blocking_scheduler=True
    )
    proxy = scheduler._device_manager
    token = issue_proposal(store, recovery)
    clock.value = token.expires_at - 2
    active = scheduler.submit_power(DEVICE_ID, True)
    assert proxy.entered.wait(timeout=1)
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.confirm_internal(token.token, scheduler)))
    caller.start()
    try:
        wait_for_confirmation_queued(scheduler)
        assert store.lookup(token.token).status is ProposalStoreStatus.NOT_FOUND
        clock.value = token.expires_at
        proxy.release.set()
        active.result(timeout=1)
        caller.join(timeout=2)

        assert not caller.is_alive()
        assert result_box[0].status is ConfirmationStatus.PROPOSAL_EXPIRED
        assert calls == []
        assert manager._configs[DEVICE_ID].address == OLD_ADDRESS
    finally:
        proxy.release.set()
        caller.join(timeout=1)
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_deadline_cancels_confirmation_still_waiting_in_fifo(monkeypatch):
    clock = FakeClock()
    _, store, manager, recovery, scheduler, _, calls = make_environment(
        monkeypatch, clock=clock, blocking_scheduler=True
    )
    proxy = scheduler._device_manager
    token = issue_proposal(store, recovery)
    active = scheduler.submit_power(DEVICE_ID, True)
    assert proxy.entered.wait(timeout=1)
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.confirm_internal(token.token, scheduler)))
    caller.start()
    try:
        wait_for_confirmation_queued(scheduler)
        clock.value += 3
        caller.join(timeout=2)

        assert not caller.is_alive()
        assert result_box[0].status is ConfirmationStatus.TIMEOUT
        proxy.release.set()
        active.result(timeout=1)
        assert calls == []
        assert manager._configs[DEVICE_ID].address == OLD_ADDRESS
    finally:
        proxy.release.set()
        caller.join(timeout=1)
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_update_address_before_confirmation_lease_blocks_stale_proposal(monkeypatch):
    _, store, manager, recovery, scheduler, _, calls = make_environment(
        monkeypatch, blocking_scheduler=True
    )
    proxy = scheduler._device_manager
    token = issue_proposal(store, recovery)
    active = scheduler.submit_power(DEVICE_ID, True)
    assert proxy.entered.wait(timeout=1)
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.confirm_internal(token.token, scheduler)))
    caller.start()
    try:
        wait_for_confirmation_queued(scheduler)
        manager.update_address(DEVICE_ID, "192.0.2.11")
        manager.update_address(DEVICE_ID, OLD_ADDRESS)
        proxy.release.set()
        active.result(timeout=1)
        caller.join(timeout=2)

        assert not caller.is_alive()
        assert result_box[0].status is ConfirmationStatus.CONFIG_CHANGED
        assert manager._config_revisions[DEVICE_ID] == 2
        assert manager._configs[DEVICE_ID].address == OLD_ADDRESS
        assert calls == []
    finally:
        proxy.release.set()
        caller.join(timeout=1)
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_ttl_expiring_during_started_validation_prevents_commit(monkeypatch):
    clock = FakeClock()
    _, store, manager, recovery, scheduler, _, _ = make_environment(monkeypatch, clock=clock)
    token = issue_proposal(store, recovery)
    clock.value = token.expires_at - 2
    entered, release = threading.Event(), threading.Event()

    def validate(_self, *_args, **_kwargs):
        entered.set()
        assert release.wait(timeout=3)
        return ValidationResult(ValidationStatus.KEY_AUTHENTICATED_READ)

    monkeypatch.setattr(CandidateValidator, "validate", validate)
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.confirm_internal(token.token, scheduler)))
    caller.start()
    try:
        assert entered.wait(timeout=1)
        clock.value = token.expires_at
        release.set()
        caller.join(timeout=2)

        assert not caller.is_alive()
        assert result_box[0].status is ConfirmationStatus.PROPOSAL_EXPIRED
        assert manager._configs[DEVICE_ID].address == OLD_ADDRESS
        assert manager._config_revisions[DEVICE_ID] == 0
    finally:
        release.set()
        caller.join(timeout=1)
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_deadline_during_started_validation_drains_without_releasing_slot(monkeypatch):
    clock = FakeClock()
    _, store, manager, recovery, scheduler, _, _ = make_environment(monkeypatch, clock=clock)
    token = issue_proposal(store, recovery)
    entered, release = threading.Event(), threading.Event()

    def validate(_self, *_args, **_kwargs):
        entered.set()
        assert release.wait(timeout=3)
        return ValidationResult(ValidationStatus.KEY_AUTHENTICATED_READ)

    monkeypatch.setattr(CandidateValidator, "validate", validate)
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.confirm_internal(token.token, scheduler)))
    caller.start()
    try:
        assert entered.wait(timeout=1)
        clock.value += 3
        assert caller.is_alive()
        second_token = store.create_validated(
            ProposalBinding("lamp-b", CANDIDATE_ADDRESS, 3.5, 0, "192.0.2.30"),
            owner=recovery._proposal_owner,
        ).descriptor
        assert second_token is not None
        assert recovery.confirm_internal(second_token.token, scheduler).status is ConfirmationStatus.BUSY
        release.set()
        caller.join(timeout=2)

        assert not caller.is_alive()
        assert result_box[0].status is ConfirmationStatus.TIMEOUT
        assert manager._configs[DEVICE_ID].address == OLD_ADDRESS
        assert store.lookup(token.token).status is ProposalStoreStatus.NOT_FOUND
    finally:
        release.set()
        caller.join(timeout=1)
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_shutdown_during_validation_blocks_adoption_and_consumes_token(monkeypatch):
    _, store, manager, recovery, scheduler, _, _ = make_environment(monkeypatch)
    token = issue_proposal(store, recovery)
    entered, release = threading.Event(), threading.Event()

    def validate(_self, *_args, **_kwargs):
        entered.set()
        assert release.wait(timeout=3)
        return ValidationResult(ValidationStatus.KEY_AUTHENTICATED_READ)

    monkeypatch.setattr(CandidateValidator, "validate", validate)
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.confirm_internal(token.token, scheduler)))
    caller.start()
    try:
        assert entered.wait(timeout=1)
        assert recovery.close(timeout_seconds=0) is False
        release.set()
        caller.join(timeout=2)

        assert not caller.is_alive()
        assert result_box[0].status is ConfirmationStatus.CLOSED
        assert manager._configs[DEVICE_ID].address == OLD_ADDRESS
        assert store.lookup(token.token).status is ProposalStoreStatus.NOT_FOUND
    finally:
        release.set()
        caller.join(timeout=1)
        scheduler.stop(timeout_seconds=1)


def test_shutdown_after_commit_preserves_adopted_result(monkeypatch):
    _, store, manager, recovery, scheduler, _, _ = make_environment(monkeypatch)
    token = issue_proposal(store, recovery)
    entered, release = threading.Event(), threading.Event()
    original_readback = manager._read_state_for_recovery_revision

    def blocked_readback(device_id, expected_revision):
        entered.set()
        assert release.wait(timeout=3)
        return original_readback(device_id, expected_revision)

    monkeypatch.setattr(manager, "_read_state_for_recovery_revision", blocked_readback)
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.confirm_internal(token.token, scheduler)))
    caller.start()
    try:
        assert entered.wait(timeout=1)
        assert manager._configs[DEVICE_ID].address == str(CANDIDATE_ADDRESS)
        assert recovery.close(timeout_seconds=0) is False
        release.set()
        caller.join(timeout=2)

        assert not caller.is_alive()
        assert result_box[0].status is ConfirmationStatus.ADOPTED
        assert result_box[0].readback_status is ReadbackStatus.SUCCEEDED
    finally:
        release.set()
        caller.join(timeout=1)
        scheduler.stop(timeout_seconds=1)


def test_deadline_after_commit_does_not_change_adopted_result(monkeypatch):
    clock, store, manager, recovery, scheduler, _, _ = make_environment(monkeypatch)
    token = issue_proposal(store, recovery)
    entered, release = threading.Event(), threading.Event()
    original_readback = manager._read_state_for_recovery_revision

    def blocked_readback(device_id, expected_revision):
        entered.set()
        assert release.wait(timeout=3)
        return original_readback(device_id, expected_revision)

    monkeypatch.setattr(manager, "_read_state_for_recovery_revision", blocked_readback)
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.confirm_internal(token.token, scheduler)))
    caller.start()
    try:
        assert entered.wait(timeout=1)
        clock.value += 3
        assert caller.is_alive()
        release.set()
        caller.join(timeout=2)

        assert not caller.is_alive()
        assert result_box[0].status is ConfirmationStatus.ADOPTED
        assert result_box[0].readback_status is ReadbackStatus.SUCCEEDED
    finally:
        release.set()
        caller.join(timeout=1)
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_address_change_after_commit_supersedes_readback_without_reversing_adoption(monkeypatch):
    _, store, manager, recovery, scheduler, _, _ = make_environment(monkeypatch)
    token = issue_proposal(store, recovery)
    entered, release = threading.Event(), threading.Event()
    original_readback = manager._read_state_for_recovery_revision

    def blocked_readback(device_id, expected_revision):
        entered.set()
        assert release.wait(timeout=3)
        return original_readback(device_id, expected_revision)

    monkeypatch.setattr(manager, "_read_state_for_recovery_revision", blocked_readback)
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.confirm_internal(token.token, scheduler)))
    caller.start()
    try:
        assert entered.wait(timeout=1)
        manager.update_address(DEVICE_ID, "192.0.2.30")
        release.set()
        caller.join(timeout=2)

        assert not caller.is_alive()
        assert result_box[0].status is ConfirmationStatus.ADOPTED
        assert result_box[0].readback_status is ReadbackStatus.SUPERSEDED
        assert manager._configs[DEVICE_ID].address == "192.0.2.30"
        assert manager._config_revisions[DEVICE_ID] == 2
    finally:
        release.set()
        caller.join(timeout=1)
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)


def test_other_device_control_progresses_during_confirmation_validation(monkeypatch):
    _, store, manager, recovery, scheduler, _, _ = make_environment(monkeypatch)
    token = issue_proposal(store, recovery)
    entered, release = threading.Event(), threading.Event()

    def validate(_self, *_args, **_kwargs):
        entered.set()
        assert release.wait(timeout=3)
        return ValidationResult(ValidationStatus.KEY_AUTHENTICATED_READ)

    monkeypatch.setattr(CandidateValidator, "validate", validate)
    result_box = []
    caller = threading.Thread(target=lambda: result_box.append(recovery.confirm_internal(token.token, scheduler)))
    caller.start()
    try:
        assert entered.wait(timeout=1)
        other = scheduler.submit_power("lamp-b", True)
        try:
            other.result(timeout=1)
        except BackendError:
            pass
        assert other.done()
        release.set()
        caller.join(timeout=2)

        assert not caller.is_alive()
        assert result_box[0].status is ConfirmationStatus.ADOPTED
    finally:
        release.set()
        caller.join(timeout=1)
        recovery.close(timeout_seconds=1)
        scheduler.stop(timeout_seconds=1)
