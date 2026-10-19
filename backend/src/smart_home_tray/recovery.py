"""Manual IP recovery discovery orchestration (D.1 only).

Every returned address is an unverified UDP announcement. This module does not
validate identity, create a confirmation proposal, or mutate device state.
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

from .device_manager import DeviceManager
from .discovery import (
    DiscoveryFailure,
    DiscoveryProvider,
    DiscoveryResultStatus,
    discover_candidates,
)

MAX_RECOVERY_DISCOVERY_SECONDS = 3.0
MAX_RECOVERY_VALIDATION_SECONDS = 2.5
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
    INVALID_ANNOUNCEMENT = "invalid_announcement"
    INVALID_RESULT = "invalid_result"
    COORDINATION_ERROR = "coordination_error"


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
                RecoveryFailure.INVALID_ANNOUNCEMENT
                if discovery.failure is DiscoveryFailure.INVALID_ANNOUNCEMENT
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
