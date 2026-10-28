"""Manual recovery discovery, proposal preparation, and internal confirmation.

Discovery results remain unverified until the internal prepare/confirm stages
complete their dedicated authenticated read-only validation.
"""

from __future__ import annotations

import ipaddress
import math
import threading
import time
from concurrent.futures import CancelledError, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Protocol

from .models import DeviceStatus, ErrorCode

from .device_manager import DeviceManager
from .discovery import (
    DiscoveryFailure,
    DiscoveryProvider,
    DiscoveryResultStatus,
    discover_candidates,
)
from .recovery_proposals import (
    ProposalDescriptor,
    ProposalStoreStatus,
    process_proposal_store,
)

MAX_RECOVERY_DISCOVERY_SECONDS = 3.0
MAX_RECOVERY_VALIDATION_SECONDS = 2.5
MAX_RECOVERY_PREPARE_SECONDS = 5.5
MAX_RECOVERY_CONFIRM_SECONDS = MAX_RECOVERY_VALIDATION_SECONDS
RECOVERY_FUTURE_POLL_SECONDS = 0.05
_PROCESS_RECOVERY_LOCK = threading.Lock()


class RecoveryCatalog(Protocol):
    """Narrow catalog view used to decide whether recovery may be requested."""

    def protocol_version_for(self, device_id: str) -> float | None: ...


class DeviceManagerRecoveryCatalog:
    """Read protocol eligibility through DeviceManager's public, brief reads."""

    def __init__(self, device_manager: DeviceManager) -> None:
        self._device_manager = device_manager

    def protocol_version_for(self, device_id: str) -> float | None:
        if device_id not in self._device_manager.list_device_ids():
            return None
        return self._device_manager.get_device(device_id).protocol_version


class RecoveryStatus(StrEnum):
    CANDIDATE_UNVERIFIED = "candidate_unverified"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    TIMEOUT = "timeout"
    DISCOVERY_FAILED = "discovery_failed"
    CATALOG_FAILED = "catalog_failed"
    DEVICE_NOT_FOUND = "device_not_found"
    PROTOCOL_NOT_ELIGIBLE = "protocol_not_eligible"
    BUSY = "busy"
    INVALID_REQUEST = "invalid_request"


class RecoveryFailure(StrEnum):
    CATALOG_ERROR = "catalog_error"
    PROVIDER_ERROR = "provider_error"
    STAGE_LISTENER = "stage_listener"
    STAGE_INTERFACES = "stage_interfaces"
    STAGE_SEND = "stage_send"
    STAGE_RECEIVE = "stage_receive"
    STAGE_LIMIT = "stage_limit"
    INVALID_ANNOUNCEMENT = "invalid_announcement"
    INVALID_RESULT = "invalid_result"
    COORDINATION_ERROR = "coordination_error"


class PreparationStatus(StrEnum):
    PROPOSAL_READY_INTERNAL = "proposal_ready_internal"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    TIMEOUT = "timeout"
    DISCOVERY_FAILED = "discovery_failed"
    CATALOG_FAILED = "catalog_failed"
    DEVICE_NOT_FOUND = "device_not_found"
    PROTOCOL_NOT_ELIGIBLE = "protocol_not_eligible"
    BUSY = "busy"
    INVALID_REQUEST = "invalid_request"
    CONFIG_CHANGED = "config_changed"
    CLOSED = "closed"
    VALIDATION_FAILED = "validation_failed"
    PROPOSAL_CAPACITY = "proposal_capacity"
    PROPOSAL_PENDING = "proposal_pending"
    TOKEN_COLLISION = "token_collision"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class PreparationResult:
    """Internal prepare outcome; only success contains an opaque descriptor."""

    status: PreparationStatus
    proposal: ProposalDescriptor | None = None
    failure: RecoveryFailure | None = None
    validation_status: str | None = None

    def __post_init__(self) -> None:
        if (self.status is PreparationStatus.PROPOSAL_READY_INTERNAL) != (self.proposal is not None):
            raise ValueError("only an internally ready proposal carries a descriptor")


class ConfirmationStatus(StrEnum):
    ADOPTED = "adopted"
    PROPOSAL_UNAVAILABLE = "proposal_unavailable"
    PROPOSAL_EXPIRED = "proposal_expired"
    BUSY = "busy"
    INVALID_REQUEST = "invalid_request"
    TIMEOUT = "timeout"
    CLOSED = "closed"
    CONFIG_CHANGED = "config_changed"
    PROTOCOL_NOT_ELIGIBLE = "protocol_not_eligible"
    AUTH_FAILED = "auth_failed"
    VALIDATION_FAILED = "validation_failed"
    CLEANUP_FAILED = "cleanup_failed"
    INTERNAL_ERROR = "internal_error"


class ReadbackStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class ConfirmationResult:
    """Internal adoption outcome with an independent post-commit readback."""

    status: ConfirmationStatus
    readback_status: ReadbackStatus | None = None
    readback: DeviceStatus | None = None
    readback_error: ErrorCode | None = None
    validation_status: str | None = None

    def __post_init__(self) -> None:
        if (self.status is ConfirmationStatus.ADOPTED) != (self.readback_status is not None):
            raise ValueError("adopted results must carry a separate readback result")
        if self.readback is not None and self.readback_status is not ReadbackStatus.SUCCEEDED:
            raise ValueError("only a successful readback carries device status")
        if self.readback_error is not None and self.readback_status is not ReadbackStatus.FAILED:
            raise ValueError("readback errors require a failed readback")


@dataclass(frozen=True)
class RecoveryCandidate:
    """Allowlisted discovery fields. The announcement is not identity proof."""

    device_id: str
    address: ipaddress.IPv4Address
    announced_versions: tuple[str, ...]


@dataclass(frozen=True)
class RecoveryResult:
    """Internal D.1 outcome, intentionally without proposal or trust state."""

    status: RecoveryStatus
    candidates: tuple[RecoveryCandidate, ...] = ()
    failure: RecoveryFailure | None = None

    def __post_init__(self) -> None:
        if self.status is RecoveryStatus.CANDIDATE_UNVERIFIED and len(self.candidates) != 1:
            raise ValueError("a unique unverified outcome requires exactly one candidate")
        if self.status is RecoveryStatus.AMBIGUOUS and len(self.candidates) < 2:
            raise ValueError("an ambiguous outcome requires multiple candidates")
        if self.status not in {
            RecoveryStatus.CANDIDATE_UNVERIFIED,
            RecoveryStatus.AMBIGUOUS,
        } and self.candidates:
            raise ValueError("this recovery outcome cannot contain candidates")
        if self.status in {
            RecoveryStatus.DISCOVERY_FAILED,
            RecoveryStatus.CATALOG_FAILED,
        }:
            if self.failure is None:
                raise ValueError("failed outcomes require a normalized failure")
        elif self.failure is not None:
            raise ValueError("non-failure outcomes cannot contain a failure")


class RecoveryService:
    """Classify F2E.B announcements for a registered Tuya 3.5 device.

    The default lock is shared across every instance in this process. It is
    acquired without waiting and held only around one bounded UDP discovery.
    It is not caller-configurable, so a second instance cannot bypass the cap.
    """

    def __init__(
        self,
        *,
        catalog: RecoveryCatalog,
        provider: DiscoveryProvider,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._catalog = catalog
        self._provider = provider
        self._device_manager = getattr(catalog, "_device_manager", None)
        self._lifecycle_lock = threading.Lock()
        self._closed = False
        self._closing_event = threading.Event()
        self._clock = clock
        self._proposal_owner = object()
        self._proposal_store = getattr(
            self._device_manager, "_proposal_store", process_proposal_store()
        )

    def close(self, *, timeout_seconds: float = 0.0) -> bool:
        """Close this coordinator and wait boundedly for the process recovery slot.

        False means an active discovery/validation still owns the slot. Its
        owner is not abandoned; call close again after the operation drains.
        """
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds < 0
        ):
            return False
        with self._lifecycle_lock:
            self._closed = True
            self._closing_event.set()
        # Instance shutdown retracts only its own proposals; other active
        # service instances share the store and retain their pending tokens.
        self._proposal_store.invalidate_owner(self._proposal_owner)
        acquired = _PROCESS_RECOVERY_LOCK.acquire(timeout=float(timeout_seconds))
        if acquired:
            _PROCESS_RECOVERY_LOCK.release()
        return acquired

    def _validate_candidate(self, device_id: str, candidate: RecoveryCandidate, scheduler: object, *, deadline: float):
        """Run one private validation turn under the process-wide recovery slot.

        This is backend-internal composition. Callers must be outside scheduler
        workers because the coordinator waits for the FIFO turn to finish.
        """
        from .recovery_validation import ValidationResult, ValidationStatus

        if (
            self._device_manager is None
            or not isinstance(device_id, str)
            or not isinstance(candidate, RecoveryCandidate)
            or candidate.device_id != device_id
            or isinstance(deadline, bool)
            or not isinstance(deadline, (int, float))
            or not math.isfinite(deadline)
        ):
            return ValidationResult(ValidationStatus.INVALID_REQUEST)
        deadline = min(float(deadline), self._clock() + MAX_RECOVERY_VALIDATION_SECONDS)
        if scheduler._is_worker_thread():
            return ValidationResult(ValidationStatus.INVALID_REQUEST)
        with self._lifecycle_lock:
            if self._closed:
                return ValidationResult(ValidationStatus.CLOSED)
        if not _PROCESS_RECOVERY_LOCK.acquire(blocking=False):
            return ValidationResult(ValidationStatus.BUSY)
        try:
            with self._lifecycle_lock:
                if self._closed:
                    return ValidationResult(ValidationStatus.CLOSED)
            snapshot = self._device_manager._recovery_snapshot(device_id, deadline=deadline)
            if snapshot is None:
                return ValidationResult(ValidationStatus.TIMEOUT)
            future = scheduler.submit_recovery_validation(
                device_id, candidate, snapshot.revision, deadline=deadline
            )
            # This caller is the recovery coordinator, never its scheduler worker.
            # Poll in short waits so an injected monotonic clock can advance.
            # Once running, cancellation fails and we must drain actual I/O.
            while True:
                if self._closing_event.is_set():
                    if future.cancel():
                        return ValidationResult(ValidationStatus.CLOSED)
                    result = future.result()
                    break
                remaining = deadline - self._clock()
                try:
                    result = future.result(
                        timeout=min(max(remaining, 0.0), RECOVERY_FUTURE_POLL_SECONDS)
                    )
                    break
                except FutureTimeoutError:
                    if self._clock() < deadline:
                        continue
                    if future.cancel():
                        return ValidationResult(ValidationStatus.TIMEOUT)
                    # Running work owns its lease and the global slot until done.
                    result = future.result()
                    break
            with self._lifecycle_lock:
                if self._closed:
                    return ValidationResult(ValidationStatus.CLOSED)
            if self._clock() >= deadline:
                return ValidationResult(ValidationStatus.TIMEOUT)
            return result
        except CancelledError:
            return ValidationResult(ValidationStatus.CLOSED)
        except Exception:
            with self._lifecycle_lock:
                if self._closed:
                    return ValidationResult(ValidationStatus.CLOSED)
            return ValidationResult(ValidationStatus.INTERNAL_ERROR)
        finally:
            _PROCESS_RECOVERY_LOCK.release()

    def prepare_internal(
        self, device_id: str, scheduler: object, *,
        timeout_seconds: float = MAX_RECOVERY_PREPARE_SECONDS,
    ) -> PreparationResult:
        """Discover, validate and publish internally under one process slot."""
        if (
            self._device_manager is None
            or not isinstance(device_id, str)
            or not device_id.strip()
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            return PreparationResult(PreparationStatus.INVALID_REQUEST)
        if scheduler._is_worker_thread():
            return PreparationResult(PreparationStatus.INVALID_REQUEST)
        with self._lifecycle_lock:
            if self._closed:
                return PreparationResult(PreparationStatus.CLOSED)
        deadline = self._clock() + min(float(timeout_seconds), MAX_RECOVERY_PREPARE_SECONDS)
        if not _PROCESS_RECOVERY_LOCK.acquire(blocking=False):
            return PreparationResult(PreparationStatus.BUSY)
        try:
            with self._lifecycle_lock:
                if self._closed:
                    return PreparationResult(PreparationStatus.CLOSED)
            snapshot = self._device_manager._recovery_snapshot(device_id, deadline=deadline)
            if snapshot is None:
                return PreparationResult(PreparationStatus.TIMEOUT)
            admission = self._proposal_store.admission(device_id)
            if admission is ProposalStoreStatus.CAPACITY:
                return PreparationResult(PreparationStatus.PROPOSAL_CAPACITY)
            if admission is ProposalStoreStatus.DEVICE_PENDING:
                return PreparationResult(PreparationStatus.PROPOSAL_PENDING)
            if self._closing_event.is_set():
                return PreparationResult(PreparationStatus.CLOSED)

            discovery = self._discover_with_held_slot(
                device_id, deadline=deadline
            )
            mapped = self._preparation_from_discovery(discovery)
            if mapped is not None:
                return mapped
            candidate = discovery.candidates[0]
            if self._clock() >= deadline:
                return PreparationResult(PreparationStatus.TIMEOUT)
            with self._lifecycle_lock:
                if self._closed:
                    return PreparationResult(PreparationStatus.CLOSED)
            validation_deadline = min(
                deadline, self._clock() + MAX_RECOVERY_VALIDATION_SECONDS
            )
            try:
                future = scheduler.submit_recovery_validation(
                    device_id, candidate, snapshot.revision,
                    deadline=validation_deadline,
                    cancellation=self._closing_event,
                    publish_proposal=True,
                    proposal_owner=self._proposal_owner,
                )
            except RuntimeError:
                return PreparationResult(PreparationStatus.CLOSED)
            outcome = self._await_prepare_future(future, validation_deadline)
            if outcome.status is PreparationStatus.TIMEOUT or outcome.status is PreparationStatus.CLOSED:
                return outcome
            if not isinstance(outcome, PreparationResult):
                return outcome
            if self._closing_event.is_set():
                return PreparationResult(PreparationStatus.CLOSED)
            return outcome
        except CancelledError:
            return PreparationResult(PreparationStatus.CLOSED)
        except Exception:
            with self._lifecycle_lock:
                if self._closed:
                    return PreparationResult(PreparationStatus.CLOSED)
            return PreparationResult(PreparationStatus.INTERNAL_ERROR)
        finally:
            _PROCESS_RECOVERY_LOCK.release()

    def confirm_internal(
        self, token: str, scheduler: object, *,
        timeout_seconds: float = MAX_RECOVERY_CONFIRM_SECONDS,
    ) -> ConfirmationResult:
        """Consume and confirm one internally issued proposal by token only."""
        if (
            self._device_manager is None
            or not isinstance(token, str)
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            return ConfirmationResult(ConfirmationStatus.INVALID_REQUEST)
        if scheduler._is_worker_thread():
            return ConfirmationResult(ConfirmationStatus.INVALID_REQUEST)
        with self._lifecycle_lock:
            if self._closed:
                return ConfirmationResult(ConfirmationStatus.CLOSED)
        deadline = self._clock() + min(
            float(timeout_seconds), MAX_RECOVERY_CONFIRM_SECONDS
        )
        if not _PROCESS_RECOVERY_LOCK.acquire(blocking=False):
            return ConfirmationResult(ConfirmationStatus.BUSY)
        try:
            # Admission linearizes against close after the global slot is owned.
            with self._lifecycle_lock:
                if self._closed:
                    return ConfirmationResult(ConfirmationStatus.CLOSED)
            if self._clock() >= deadline:
                return ConfirmationResult(ConfirmationStatus.TIMEOUT)
            claimed = self._proposal_store.claim(token, owner=self._proposal_owner)
            if claimed.status is ProposalStoreStatus.EXPIRED:
                return ConfirmationResult(ConfirmationStatus.PROPOSAL_EXPIRED)
            if claimed.status is not ProposalStoreStatus.CLAIMED:
                return ConfirmationResult(ConfirmationStatus.PROPOSAL_UNAVAILABLE)
            if (
                claimed.binding is None
                or claimed.expires_at is None
                or claimed.owner is not self._proposal_owner
            ):
                return ConfirmationResult(ConfirmationStatus.INTERNAL_ERROR)
            if self._closing_event.is_set():
                return ConfirmationResult(ConfirmationStatus.CLOSED)
            if self._clock() >= deadline:
                return ConfirmationResult(ConfirmationStatus.TIMEOUT)
            try:
                future = scheduler.submit_recovery_confirmation(
                    claimed.binding.device_id,
                    claimed.binding,
                    claimed.expires_at,
                    claimed.owner,
                    deadline=deadline,
                    cancellation=self._closing_event,
                    lifecycle_lock=self._lifecycle_lock,
                )
            except RuntimeError:
                return ConfirmationResult(ConfirmationStatus.CLOSED)
            return self._await_confirmation_future(future, deadline)
        except CancelledError:
            return ConfirmationResult(ConfirmationStatus.CLOSED)
        except Exception:
            with self._lifecycle_lock:
                if self._closed:
                    return ConfirmationResult(ConfirmationStatus.CLOSED)
            return ConfirmationResult(ConfirmationStatus.INTERNAL_ERROR)
        finally:
            _PROCESS_RECOVERY_LOCK.release()

    def _await_confirmation_future(self, future, deadline: float) -> ConfirmationResult:
        while True:
            if self._closing_event.is_set():
                if future.cancel():
                    return ConfirmationResult(ConfirmationStatus.CLOSED)
                raw = future.result()
                if isinstance(raw, ConfirmationResult) and raw.status is ConfirmationStatus.ADOPTED:
                    return raw
                return ConfirmationResult(ConfirmationStatus.CLOSED)
            remaining = deadline - self._clock()
            try:
                raw = future.result(
                    timeout=min(max(remaining, 0.0), RECOVERY_FUTURE_POLL_SECONDS)
                )
            except FutureTimeoutError:
                if self._clock() < deadline:
                    continue
                if future.cancel():
                    return ConfirmationResult(ConfirmationStatus.TIMEOUT)
                raw = future.result()  # An active validation/readback still owns the slot.
                if isinstance(raw, ConfirmationResult) and raw.status is ConfirmationStatus.ADOPTED:
                    return raw
                if self._closing_event.is_set():
                    return ConfirmationResult(ConfirmationStatus.CLOSED)
                return ConfirmationResult(ConfirmationStatus.TIMEOUT)
            except CancelledError:
                return ConfirmationResult(ConfirmationStatus.CLOSED)

            if not isinstance(raw, ConfirmationResult):
                if self._closing_event.is_set():
                    return ConfirmationResult(ConfirmationStatus.CLOSED)
                if self._clock() >= deadline:
                    return ConfirmationResult(ConfirmationStatus.TIMEOUT)
                return ConfirmationResult(ConfirmationStatus.INTERNAL_ERROR)
            if raw.status is ConfirmationStatus.ADOPTED:
                return raw
            if self._closing_event.is_set():
                return ConfirmationResult(ConfirmationStatus.CLOSED)
            if self._clock() >= deadline:
                return ConfirmationResult(ConfirmationStatus.TIMEOUT)
            return raw

    def _discover_with_held_slot(self, device_id: str, *, deadline: float) -> RecoveryResult:
        """D.1 classification for a caller that already owns the process slot."""
        from .discovery import DiscoveryFailure, DiscoveryResultStatus

        try:
            protocol_version = self._catalog.protocol_version_for(device_id)
        except Exception:
            return RecoveryResult(
                RecoveryStatus.CATALOG_FAILED,
                failure=RecoveryFailure.CATALOG_ERROR,
            )
        if protocol_version is None:
            return RecoveryResult(RecoveryStatus.DEVICE_NOT_FOUND)
        if (
            isinstance(protocol_version, bool)
            or not isinstance(protocol_version, (int, float))
            or protocol_version != 3.5
        ):
            return RecoveryResult(RecoveryStatus.PROTOCOL_NOT_ELIGIBLE)
        remaining = min(MAX_RECOVERY_DISCOVERY_SECONDS, deadline - self._clock())
        if remaining <= 0:
            return RecoveryResult(RecoveryStatus.TIMEOUT)
        discovery = discover_candidates(
            self._provider, device_id, timeout_seconds=remaining
        )
        if discovery.status is DiscoveryResultStatus.FAILED:
            if discovery.failure is DiscoveryFailure.TIMEOUT:
                return RecoveryResult(RecoveryStatus.TIMEOUT)
            failure = (
                RecoveryFailure(discovery.failure.value)
                if discovery.failure in {DiscoveryFailure.INVALID_ANNOUNCEMENT, DiscoveryFailure.STAGE_LISTENER, DiscoveryFailure.STAGE_INTERFACES, DiscoveryFailure.STAGE_SEND, DiscoveryFailure.STAGE_RECEIVE, DiscoveryFailure.STAGE_LIMIT}
                else RecoveryFailure.PROVIDER_ERROR
            )
            return RecoveryResult(RecoveryStatus.DISCOVERY_FAILED, failure=failure)
        if discovery.status is DiscoveryResultStatus.NOT_FOUND:
            return RecoveryResult(RecoveryStatus.NOT_FOUND)
        candidates = tuple(
            RecoveryCandidate(item.device_id, item.address, item.announced_versions)
            for item in discovery.candidates
        )
        if discovery.status is DiscoveryResultStatus.AMBIGUOUS:
            return RecoveryResult(RecoveryStatus.AMBIGUOUS, candidates)
        if discovery.status is DiscoveryResultStatus.CANDIDATES and len(candidates) == 1:
            if candidates[0].announced_versions != ("3.5",):
                return RecoveryResult(RecoveryStatus.PROTOCOL_NOT_ELIGIBLE)
            return RecoveryResult(RecoveryStatus.CANDIDATE_UNVERIFIED, candidates)
        return RecoveryResult(
            RecoveryStatus.DISCOVERY_FAILED,
            failure=RecoveryFailure.INVALID_RESULT,
        )

    @staticmethod
    def _preparation_from_discovery(result: RecoveryResult) -> PreparationResult | None:
        mapping = {
            RecoveryStatus.NOT_FOUND: PreparationStatus.NOT_FOUND,
            RecoveryStatus.AMBIGUOUS: PreparationStatus.AMBIGUOUS,
            RecoveryStatus.TIMEOUT: PreparationStatus.TIMEOUT,
            RecoveryStatus.DISCOVERY_FAILED: PreparationStatus.DISCOVERY_FAILED,
            RecoveryStatus.CATALOG_FAILED: PreparationStatus.CATALOG_FAILED,
            RecoveryStatus.DEVICE_NOT_FOUND: PreparationStatus.DEVICE_NOT_FOUND,
            RecoveryStatus.PROTOCOL_NOT_ELIGIBLE: PreparationStatus.PROTOCOL_NOT_ELIGIBLE,
        }
        if result.status is RecoveryStatus.CANDIDATE_UNVERIFIED:
            return None
        return PreparationResult(
            mapping.get(result.status, PreparationStatus.INTERNAL_ERROR),
            failure=result.failure,
        )

    def _await_prepare_future(self, future, deadline: float) -> PreparationResult:
        from .recovery_validation import ValidationPublicationResult, ValidationStatus

        while True:
            if self._closing_event.is_set():
                if future.cancel():
                    return PreparationResult(PreparationStatus.CLOSED)
                raw = future.result()  # Running validation owns its lease and slot until actual completion.
                self._retract_completed_proposal(raw)
                return PreparationResult(PreparationStatus.CLOSED)
            remaining = deadline - self._clock()
            try:
                raw = future.result(
                    timeout=min(max(remaining, 0.0), RECOVERY_FUTURE_POLL_SECONDS)
                )
            except FutureTimeoutError:
                if self._clock() < deadline:
                    continue
                if future.cancel():
                    return PreparationResult(PreparationStatus.TIMEOUT)
                raw = future.result()  # Do not release the process slot while I/O is active.
                self._retract_completed_proposal(raw)
                return PreparationResult(PreparationStatus.TIMEOUT)
            if self._clock() >= deadline:
                self._retract_completed_proposal(raw)
                return PreparationResult(PreparationStatus.TIMEOUT)
            if self._closing_event.is_set():
                self._retract_completed_proposal(raw)
                return PreparationResult(PreparationStatus.CLOSED)
            if not isinstance(raw, ValidationPublicationResult):
                return PreparationResult(PreparationStatus.INTERNAL_ERROR)
            if raw.proposal is not None:
                return PreparationResult(
                    PreparationStatus.PROPOSAL_READY_INTERNAL, proposal=raw.proposal
                )
            status = raw.validation.status
            if status is ValidationStatus.CLOSED:
                mapped = PreparationStatus.CLOSED
            elif status is ValidationStatus.TIMEOUT:
                mapped = PreparationStatus.TIMEOUT
            elif status is ValidationStatus.CONFIG_CHANGED:
                mapped = PreparationStatus.CONFIG_CHANGED
            elif raw.publication_status is ProposalStoreStatus.CAPACITY:
                mapped = PreparationStatus.PROPOSAL_CAPACITY
            elif raw.publication_status is ProposalStoreStatus.DEVICE_PENDING:
                mapped = PreparationStatus.PROPOSAL_PENDING
            elif raw.publication_status is ProposalStoreStatus.TOKEN_COLLISION:
                mapped = PreparationStatus.TOKEN_COLLISION
            elif raw.publication_status is ProposalStoreStatus.DEADLINE_EXPIRED:
                mapped = PreparationStatus.TIMEOUT
            elif raw.publication_status is ProposalStoreStatus.CANCELLED:
                mapped = PreparationStatus.CLOSED
            else:
                mapped = PreparationStatus.VALIDATION_FAILED
            return PreparationResult(mapped, validation_status=status.value)

    def _retract_completed_proposal(self, outcome: object) -> None:
        from .recovery_validation import ValidationPublicationResult

        if isinstance(outcome, ValidationPublicationResult) and outcome.proposal is not None:
            self._proposal_store.retract(outcome.proposal.token)

    def discover_for_recovery(
        self,
        device_id: str,
        *,
        timeout_seconds: float = MAX_RECOVERY_DISCOVERY_SECONDS,
    ) -> RecoveryResult:
        """Return normalized, unverified candidates for an eligible catalog ID."""
        if (
            not isinstance(device_id, str)
            or not device_id.strip()
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            return RecoveryResult(RecoveryStatus.INVALID_REQUEST)
        with self._lifecycle_lock:
            if self._closed:
                return RecoveryResult(RecoveryStatus.INVALID_REQUEST)

        try:
            protocol_version = self._catalog.protocol_version_for(device_id)
        except Exception:
            return RecoveryResult(
                RecoveryStatus.CATALOG_FAILED,
                failure=RecoveryFailure.CATALOG_ERROR,
            )

        if protocol_version is None:
            return RecoveryResult(RecoveryStatus.DEVICE_NOT_FOUND)
        if (
            isinstance(protocol_version, bool)
            or not isinstance(protocol_version, (int, float))
            or protocol_version != 3.5
        ):
            return RecoveryResult(RecoveryStatus.PROTOCOL_NOT_ELIGIBLE)

        try:
            acquired = _PROCESS_RECOVERY_LOCK.acquire(blocking=False)
        except Exception:
            return RecoveryResult(
                RecoveryStatus.DISCOVERY_FAILED,
                failure=RecoveryFailure.COORDINATION_ERROR,
            )
        if not acquired:
            return RecoveryResult(RecoveryStatus.BUSY)

        try:
            # Admission linearizes here against close(): release the lifecycle
            # mutex before provider I/O, while retaining the process slot.
            with self._lifecycle_lock:
                if self._closed:
                    return RecoveryResult(RecoveryStatus.INVALID_REQUEST)
            discovery = discover_candidates(
                self._provider,
                device_id,
                timeout_seconds=min(
                    float(timeout_seconds), MAX_RECOVERY_DISCOVERY_SECONDS
                ),
            )
        finally:
            _PROCESS_RECOVERY_LOCK.release()

        with self._lifecycle_lock:
            if self._closed:
                return RecoveryResult(RecoveryStatus.INVALID_REQUEST)

        if discovery.status is DiscoveryResultStatus.FAILED:
            if discovery.failure is DiscoveryFailure.TIMEOUT:
                return RecoveryResult(RecoveryStatus.TIMEOUT)
            failure = (
                RecoveryFailure(discovery.failure.value)
                if discovery.failure in {DiscoveryFailure.INVALID_ANNOUNCEMENT, DiscoveryFailure.STAGE_LISTENER, DiscoveryFailure.STAGE_INTERFACES, DiscoveryFailure.STAGE_SEND, DiscoveryFailure.STAGE_RECEIVE, DiscoveryFailure.STAGE_LIMIT}
                else RecoveryFailure.PROVIDER_ERROR
            )
            return RecoveryResult(
                RecoveryStatus.DISCOVERY_FAILED,
                failure=failure,
            )
        if discovery.status is DiscoveryResultStatus.NOT_FOUND:
            return RecoveryResult(RecoveryStatus.NOT_FOUND)

        candidates = tuple(
            RecoveryCandidate(
                device_id=candidate.device_id,
                address=candidate.address,
                announced_versions=candidate.announced_versions,
            )
            for candidate in discovery.candidates
        )
        if discovery.status is DiscoveryResultStatus.AMBIGUOUS:
            return RecoveryResult(RecoveryStatus.AMBIGUOUS, candidates)
        if discovery.status is DiscoveryResultStatus.CANDIDATES and len(candidates) == 1:
            # UDP version claims are untrusted. Require one unambiguous, exact
            # 3.5 claim before exposing this endpoint to later recovery steps.
            if candidates[0].announced_versions != ("3.5",):
                return RecoveryResult(RecoveryStatus.PROTOCOL_NOT_ELIGIBLE)
            return RecoveryResult(RecoveryStatus.CANDIDATE_UNVERIFIED, candidates)
        return RecoveryResult(
            RecoveryStatus.DISCOVERY_FAILED,
            failure=RecoveryFailure.INVALID_RESULT,
        )
