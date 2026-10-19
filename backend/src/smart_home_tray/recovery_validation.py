"""Private D.2.A candidate validator; it creates no proposal and changes no state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from smart_home_tray.dps_observation import observe_dps
from smart_home_tray.models import DeviceConfig
from smart_home_tray.recovery import RecoveryCandidate
from smart_home_tray.tuya35_readonly import (
    ReadOnlyError,
    ReadOnlyFailure,
    TinyTuya35ReadOnlyClient,
)


class ValidationStatus(StrEnum):
    KEY_AUTHENTICATED_READ = "key_authenticated_read"
    INVALID_REQUEST = "invalid_request"
    PROTOCOL_NOT_ELIGIBLE = "protocol_not_eligible"
    DEPENDENCY_UNSUPPORTED = "dependency_unsupported"
    INTERFACE_UNAVAILABLE = "interface_unavailable"
    TIMEOUT = "timeout"
    TRANSPORT_FAILED = "transport_failed"
    AUTH_FAILED = "auth_failed"
    INVALID_RESPONSE = "invalid_response"
    CLOSED = "closed"
    CLEANUP_FAILED = "cleanup_failed"
    INTERNAL_ERROR = "internal_error"
    CONFIG_CHANGED = "config_changed"
    BUSY = "busy"


@dataclass(frozen=True)
class ValidationResult:
    """Allowlisted outcome only; no candidate, DPS, config, key or packet data."""

    status: ValidationStatus
    phase: str | None = None


class ReadOnlyClient(Protocol):
    def read_authenticated_dps(self, *, deadline: float) -> dict[str, object]: ...


ClientFactory = Callable[[DeviceConfig, RecoveryCandidate], ReadOnlyClient]

_FAILURE_TO_STATUS = {
    ReadOnlyFailure.INVALID_REQUEST: ValidationStatus.INVALID_REQUEST,
    ReadOnlyFailure.CLOSED: ValidationStatus.CLOSED,
    ReadOnlyFailure.PROTOCOL_NOT_ELIGIBLE: ValidationStatus.PROTOCOL_NOT_ELIGIBLE,
    ReadOnlyFailure.DEPENDENCY_UNSUPPORTED: ValidationStatus.DEPENDENCY_UNSUPPORTED,
    ReadOnlyFailure.INTERFACE_UNAVAILABLE: ValidationStatus.INTERFACE_UNAVAILABLE,
    ReadOnlyFailure.TIMEOUT: ValidationStatus.TIMEOUT,
    ReadOnlyFailure.TRANSPORT_FAILED: ValidationStatus.TRANSPORT_FAILED,
    ReadOnlyFailure.AUTH_FAILED: ValidationStatus.AUTH_FAILED,
    ReadOnlyFailure.INVALID_RESPONSE: ValidationStatus.INVALID_RESPONSE,
    ReadOnlyFailure.CLEANUP_FAILED: ValidationStatus.CLEANUP_FAILED,
}


class CandidateValidator:
    """Validate one D.1 candidate without touching DeviceManager or a proposal store."""

    def __init__(self, *, client_factory: ClientFactory | None = None) -> None:
        self._client_factory = client_factory or self._default_client_factory

    def validate(
        self,
        config: DeviceConfig,
        candidate: RecoveryCandidate,
        *,
        deadline: float,
    ) -> ValidationResult:
        if (
            config.protocol_version != 3.5
            or candidate.device_id != config.device_id
            or candidate.announced_versions != ("3.5",)
        ):
            return ValidationResult(ValidationStatus.PROTOCOL_NOT_ELIGIBLE)

        try:
            client = self._client_factory(config, candidate)
            dps = client.read_authenticated_dps(deadline=deadline)
            observation = observe_dps(config, dps)
            if not observation.observed:
                return ValidationResult(ValidationStatus.INVALID_RESPONSE, "status")
            return ValidationResult(ValidationStatus.KEY_AUTHENTICATED_READ)
        except ReadOnlyError as error:
            return ValidationResult(_FAILURE_TO_STATUS[error.failure], error.phase)
        except Exception:
            # Never preserve a factory/parser exception or its potentially sensitive context.
            return ValidationResult(ValidationStatus.INTERNAL_ERROR)

    @staticmethod
    def _default_client_factory(
        config: DeviceConfig, candidate: RecoveryCandidate
    ) -> TinyTuya35ReadOnlyClient:
        return TinyTuya35ReadOnlyClient(
            config,
            candidate.address,
            candidate_device_id=candidate.device_id,
            announced_versions=candidate.announced_versions,
        )
