"""Pure, internal LAN discovery contracts for untrusted candidate announcements.

This module deliberately has no TinyTuya, socket, adapter, or DeviceManager
dependency. A candidate is an address reported by an announcement, never a
verified device or an accepted address.
"""

from __future__ import annotations

import ipaddress
import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class DiscoveryResultStatus(StrEnum):
    NOT_FOUND = "not_found"
    CANDIDATES = "candidates"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


class DiscoveryFailure(StrEnum):
    INVALID_REQUEST = "invalid_request"
    INVALID_ANNOUNCEMENT = "invalid_announcement"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    STAGE_COORDINATION = "stage_coordination"
    STAGE_LISTENER = "stage_listener"
    STAGE_INTERFACES = "stage_interfaces"
    STAGE_SEND = "stage_send"
    STAGE_RECEIVE = "stage_receive"
    STAGE_LIMIT = "stage_limit"


class DiscoveryStageError(OSError):
    def __init__(self, stage: DiscoveryFailure, message: str):
        super().__init__(message)
        self.stage = stage


class DiscoveryCoordinationError(RuntimeError):
    stage = DiscoveryFailure.STAGE_COORDINATION


class DiscoveryLimitError(RuntimeError):
    stage = DiscoveryFailure.STAGE_LIMIT


@dataclass(frozen=True)
class DiscoveryAnnouncement:
    """Allowlisted fields extracted from an untrusted announcement."""

    device_id: str
    address: str
    announced_version: str | int | float | None = None


@dataclass(frozen=True)
class DiscoveryCandidate:
    """Normalized, unverified IPv4 candidate reported for one Device ID."""

    device_id: str
    address: ipaddress.IPv4Address
    announced_versions: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiscoveryResult:
    """Candidate collection outcome; it carries no identity or acceptance proof."""

    status: DiscoveryResultStatus
    candidates: tuple[DiscoveryCandidate, ...] = ()
    failure: DiscoveryFailure | None = None

    def __post_init__(self) -> None:
        if self.status is DiscoveryResultStatus.FAILED:
            if self.failure is None or self.candidates:
                raise ValueError("failed discovery results require a failure and no candidates")
            return
        if self.failure is not None:
            raise ValueError("successful discovery outcomes cannot contain a failure")
        if self.status is DiscoveryResultStatus.NOT_FOUND and self.candidates:
            raise ValueError("not-found discovery results cannot contain candidates")
        if self.status is DiscoveryResultStatus.CANDIDATES and len(self.candidates) != 1:
            raise ValueError("candidate discovery results must contain exactly one address")
        if self.status is DiscoveryResultStatus.AMBIGUOUS and len(self.candidates) < 2:
            raise ValueError("ambiguous discovery results require multiple addresses")


class DiscoveryProvider(Protocol):
    """Injected source of untrusted announcements; no real provider is defined here."""

    def discover(
        self, expected_device_id: str, *, timeout_seconds: float
    ) -> Sequence[DiscoveryAnnouncement]:
        """Return announcements observed within the caller-provided time budget."""


def _failed(failure: DiscoveryFailure) -> DiscoveryResult:
    return DiscoveryResult(DiscoveryResultStatus.FAILED, failure=failure)


def _normalize_version(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("invalid announced version")
    if isinstance(value, str):
        if not value.strip():
            raise ValueError("invalid announced version")
        return value.strip()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return str(value)
    raise ValueError("invalid announced version")


def process_announcements(
    expected_device_id: str,
    announcements: Sequence[DiscoveryAnnouncement],
) -> DiscoveryResult:
    """Normalize untrusted announcements without validating or applying an IP.

    Mismatched Device IDs are ignored before parsing their addresses. Any malformed
    record for the requested ID fails the batch so valid partial results cannot
    conceal conflicting or damaged input. Identical observations collapse, while
    differing version claims for one IP remain visible in ``announced_versions``.
    """
    if (
        not isinstance(expected_device_id, str)
        or not expected_device_id.strip()
        or not isinstance(announcements, Sequence)
        or isinstance(announcements, (str, bytes))
    ):
        return _failed(DiscoveryFailure.INVALID_REQUEST)

    try:
        records = tuple(announcements)
    except Exception:
        return _failed(DiscoveryFailure.INVALID_ANNOUNCEMENT)

    versions_by_address: dict[ipaddress.IPv4Address, set[str]] = {}
    for announcement in records:
        if not isinstance(announcement, DiscoveryAnnouncement):
            return _failed(DiscoveryFailure.INVALID_ANNOUNCEMENT)
        if not isinstance(announcement.device_id, str) or not announcement.device_id.strip():
            return _failed(DiscoveryFailure.INVALID_ANNOUNCEMENT)
        if announcement.device_id != expected_device_id:
            continue
        if not isinstance(announcement.address, str):
            return _failed(DiscoveryFailure.INVALID_ANNOUNCEMENT)

        try:
            address = ipaddress.IPv4Address(announcement.address)
            version = _normalize_version(announcement.announced_version)
        except (ipaddress.AddressValueError, ValueError):
            return _failed(DiscoveryFailure.INVALID_ANNOUNCEMENT)

        if (
            address.is_unspecified
            or address.is_loopback
            or address.is_multicast
            or address == ipaddress.IPv4Address("255.255.255.255")
        ):
            return _failed(DiscoveryFailure.INVALID_ANNOUNCEMENT)

        versions = versions_by_address.setdefault(address, set())
        if version is not None:
            versions.add(version)

    if not versions_by_address:
        return DiscoveryResult(DiscoveryResultStatus.NOT_FOUND)

    candidates = tuple(
        DiscoveryCandidate(
            device_id=expected_device_id,
            address=address,
            announced_versions=tuple(sorted(versions_by_address[address])),
        )
        for address in sorted(versions_by_address, key=int)
    )
    status = (
        DiscoveryResultStatus.AMBIGUOUS
        if len(candidates) > 1
        else DiscoveryResultStatus.CANDIDATES
    )
    return DiscoveryResult(status, candidates)


def discover_candidates(
    provider: DiscoveryProvider,
    expected_device_id: str,
    *,
    timeout_seconds: float,
) -> DiscoveryResult:
    """Call an injected provider once and normalize errors without their details."""
    if (
        not isinstance(expected_device_id, str)
        or not expected_device_id.strip()
        or isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        return _failed(DiscoveryFailure.INVALID_REQUEST)

    try:
        announcements = provider.discover(
            expected_device_id, timeout_seconds=float(timeout_seconds)
        )
    except TimeoutError:
        return _failed(DiscoveryFailure.TIMEOUT)
    except (DiscoveryStageError, DiscoveryLimitError, DiscoveryCoordinationError) as error:
        allowed = {DiscoveryFailure.STAGE_COORDINATION, DiscoveryFailure.STAGE_LISTENER, DiscoveryFailure.STAGE_INTERFACES, DiscoveryFailure.STAGE_SEND, DiscoveryFailure.STAGE_RECEIVE, DiscoveryFailure.STAGE_LIMIT}
        return _failed(error.stage if error.stage in allowed else DiscoveryFailure.PROVIDER_ERROR)
    except Exception:
        return _failed(DiscoveryFailure.PROVIDER_ERROR)

    return process_announcements(expected_device_id, announcements)
