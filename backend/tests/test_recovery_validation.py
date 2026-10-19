from __future__ import annotations

import ipaddress

from smart_home_tray.models import DeviceConfig, DPSMap
from smart_home_tray.recovery import RecoveryCandidate
from smart_home_tray.recovery_validation import (
    CandidateValidator,
    ValidationStatus,
)
from smart_home_tray.tuya35_readonly import ReadOnlyError, ReadOnlyFailure


def _config() -> DeviceConfig:
    return DeviceConfig(
        device_id="synthetic-device",
        name="synthetic lamp",
        address="10.60.2.10",
        protocol_version=3.5,
        local_key="synthetic-key-12",
        dps=DPSMap(power=20),
    )


def _candidate(*, device_id="synthetic-device", versions=("3.5",)):
    return RecoveryCandidate(
        device_id=device_id,
        address=ipaddress.IPv4Address("10.60.2.20"),
        announced_versions=versions,
    )


class FakeReadonlyClient:
    def __init__(self, dps=None, failure=None) -> None:
        self.dps = dps
        self.failure = failure
        self.calls = 0

    def read_authenticated_dps(self, *, deadline):
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return self.dps


def test_candidate_validator_returns_only_reduced_authenticated_read_result():
    client = FakeReadonlyClient({"20": True, "991": "unmapped"})
    made = []

    def factory(config, candidate):
        made.append((config, candidate))
        return client

    result = CandidateValidator(client_factory=factory).validate(
        _config(), _candidate(), deadline=10.0
    )

    assert result.status is ValidationStatus.KEY_AUTHENTICATED_READ
    assert result.phase is None
    assert "local_key" not in repr(result)
    assert "dps" not in repr(result)
    assert client.calls == 1
    assert made == [(_config(), _candidate())]


def test_candidate_validator_rejects_incompatible_claim_before_factory():
    made = []
    validator = CandidateValidator(client_factory=lambda *_: made.append(True))

    result = validator.validate(_config(), _candidate(versions=("3.3",)), deadline=10.0)

    assert result.status is ValidationStatus.PROTOCOL_NOT_ELIGIBLE
    assert made == []


def test_candidate_validator_rejects_candidate_for_different_device_id():
    made = []
    result = CandidateValidator(client_factory=lambda *_: made.append(True)).validate(
        _config(), _candidate(device_id="other-id"), deadline=10.0
    )

    assert result.status is ValidationStatus.PROTOCOL_NOT_ELIGIBLE
    assert made == []


def test_candidate_validator_requires_at_least_one_recognized_dps():
    client = FakeReadonlyClient({"991": "plausible but unmapped"})
    result = CandidateValidator(client_factory=lambda *_: client).validate(
        _config(), _candidate(), deadline=10.0
    )

    assert result.status is ValidationStatus.INVALID_RESPONSE


def test_candidate_validator_normalizes_failure_without_exposing_exception():
    client = FakeReadonlyClient(failure=ReadOnlyError(ReadOnlyFailure.TIMEOUT, "status"))

    result = CandidateValidator(client_factory=lambda *_: client).validate(
        _config(), _candidate(), deadline=10.0
    )

    assert result.status is ValidationStatus.TIMEOUT
    assert result.phase == "status"
    assert "Timeout" not in repr(result)

