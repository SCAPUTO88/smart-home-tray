from __future__ import annotations

import math
import socket
from collections.abc import Sequence
from dataclasses import fields

import pytest

from smart_home_tray.discovery import (
    DiscoveryAnnouncement,
    DiscoveryFailure,
    DiscoveryProvider,
    DiscoveryResultStatus,
    discover_candidates,
    process_announcements,
)


class FakeDiscoveryProvider:
    def __init__(self, announcements=(), error: Exception | None = None):
        self.announcements = announcements
        self.error = error
        self.calls: list[tuple[str, float]] = []
        self.operation_calls: list[str] = []

    def discover(self, expected_device_id: str, *, timeout_seconds: float):
        self.operation_calls.append("discover")
        self.calls.append((expected_device_id, timeout_seconds))
        if self.error is not None:
            raise self.error
        return self.announcements

    def update_address(self, *_args, **_kwargs):
        self.operation_calls.append("update_address")
        raise AssertionError("candidate discovery must not update a device address")

    def set_value(self, *_args, **_kwargs):
        self.operation_calls.append("set_value")
        raise AssertionError("candidate discovery must not write a device value")

    def status(self, *_args, **_kwargs):
        self.operation_calls.append("status")
        raise AssertionError("candidate discovery must not open a device session")


def announcement(device_id="fake-device-id", address="192.0.2.10", version="3.5"):
    return DiscoveryAnnouncement(device_id, address, version)


def test_empty_announcement_list_reports_not_found():
    result = process_announcements("fake-device-id", ())

    assert result.status is DiscoveryResultStatus.NOT_FOUND
    assert result.candidates == ()
    assert result.failure is None


def test_exact_id_and_ipv4_produce_unverified_candidate():
    result = process_announcements(
        "fake-device-id",
        (announcement(address="192.0.2.10", version=3.5),),
    )

    assert result.status is DiscoveryResultStatus.CANDIDATES
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.device_id == "fake-device-id"
    assert str(candidate.address) == "192.0.2.10"
    assert candidate.announced_versions == ("3.5",)
    assert not hasattr(candidate, "verified")


def test_mismatched_device_id_is_ignored_without_parsing_its_address():
    result = process_announcements(
        "fake-device-id",
        (announcement(device_id="another-fake-id", address="not-an-ip"),),
    )

    assert result.status is DiscoveryResultStatus.NOT_FOUND
    assert result.candidates == ()


@pytest.mark.parametrize(
    "address",
    ["not-an-ip", "2001:db8::1", "0.0.0.0", "127.0.0.1", "224.0.0.1", "255.255.255.255"],
)
def test_unusable_or_non_ipv4_matching_address_fails_closed(address):
    result = process_announcements(
        "fake-device-id", (announcement(address=address),)
    )

    assert result.status is DiscoveryResultStatus.FAILED
    assert result.candidates == ()
    assert result.failure is DiscoveryFailure.INVALID_ANNOUNCEMENT


def test_malformed_matching_announcement_fails_without_partial_candidates():
    malformed = DiscoveryAnnouncement("fake-device-id", None, "3.5")  # type: ignore[arg-type]
    result = process_announcements(
        "fake-device-id",
        (announcement(address="192.0.2.11"), malformed),
    )

    assert result.status is DiscoveryResultStatus.FAILED
    assert result.candidates == ()
    assert result.failure is DiscoveryFailure.INVALID_ANNOUNCEMENT


def test_malformed_version_value_fails_closed():
    malformed = DiscoveryAnnouncement(
        "fake-device-id", "192.0.2.11", ["3.5"]  # type: ignore[arg-type]
    )

    result = process_announcements("fake-device-id", (malformed,))

    assert result.status is DiscoveryResultStatus.FAILED
    assert result.candidates == ()
    assert result.failure is DiscoveryFailure.INVALID_ANNOUNCEMENT


def test_provider_sequence_iteration_failure_is_normalized():
    class BrokenAnnouncements(Sequence):
        def __len__(self):
            return 1

        def __getitem__(self, index):
            raise RuntimeError("fake announcement payload")

    result = process_announcements("fake-device-id", BrokenAnnouncements())

    assert result.status is DiscoveryResultStatus.FAILED
    assert result.failure is DiscoveryFailure.INVALID_ANNOUNCEMENT
    assert "fake announcement payload" not in repr(result)


def test_identical_announcements_are_deduplicated():
    duplicate = announcement(address="192.0.2.10")

    result = process_announcements("fake-device-id", (duplicate, duplicate))

    assert result.status is DiscoveryResultStatus.CANDIDATES
    assert len(result.candidates) == 1


def test_multiple_distinct_ips_are_preserved_and_ambiguous():
    first = announcement(address="192.0.2.10")
    second = announcement(address="192.0.2.20")

    result = process_announcements("fake-device-id", (second, first))

    assert result.status is DiscoveryResultStatus.AMBIGUOUS
    assert tuple(str(candidate.address) for candidate in result.candidates) == (
        "192.0.2.10",
        "192.0.2.20",
    )


def test_order_of_announcements_does_not_change_normalized_result():
    records = (
        announcement(address="192.0.2.20", version="3.5"),
        announcement(address="192.0.2.10", version="3.3"),
    )

    forward = process_announcements("fake-device-id", records)
    reverse = process_announcements("fake-device-id", tuple(reversed(records)))

    assert forward == reverse


def test_conflicting_announced_versions_are_preserved_without_selecting_one():
    records = (
        announcement(address="192.0.2.10", version="3.3"),
        announcement(address="192.0.2.10", version="3.5"),
        announcement(address="192.0.2.10", version="3.3"),
    )

    result = process_announcements("fake-device-id", records)

    assert result.status is DiscoveryResultStatus.CANDIDATES
    assert len(result.candidates) == 1
    assert result.candidates[0].announced_versions == ("3.3", "3.5")


def test_announced_version_is_informational_and_not_matched_to_configuration():
    configured_version = 3.3
    result = process_announcements(
        "fake-device-id", (announcement(version="3.5"),)
    )

    assert result.status is DiscoveryResultStatus.CANDIDATES
    assert result.candidates[0].announced_versions == ("3.5",)
    assert float(result.candidates[0].announced_versions[0]) != configured_version


def test_candidate_allowlist_excludes_mac_raw_payload_and_credentials():
    result = process_announcements(
        "fake-device-id", (announcement(address="192.0.2.10"),)
    )
    candidate = result.candidates[0]

    assert {field.name for field in fields(candidate)} == {
        "device_id",
        "address",
        "announced_versions",
    }
    public_repr = repr(result)
    assert "unit-test-key-not-real" not in public_repr
    assert "00:11:22:33:44:55" not in public_repr
    assert "raw_udp_payload" not in public_repr


def test_provider_is_injected_called_once_and_never_runs_device_operations():
    provider = FakeDiscoveryProvider((announcement(),))

    result = discover_candidates(provider, "fake-device-id", timeout_seconds=1.25)

    assert result.status is DiscoveryResultStatus.CANDIDATES
    assert provider.calls == [("fake-device-id", 1.25)]
    assert provider.operation_calls == ["discover"]


def test_provider_timeout_is_normalized_without_exception_text_or_cause():
    provider = FakeDiscoveryProvider(error=TimeoutError("fake secret timeout detail"))

    result = discover_candidates(provider, "fake-device-id", timeout_seconds=1.0)

    assert result.status is DiscoveryResultStatus.FAILED
    assert result.failure is DiscoveryFailure.TIMEOUT
    assert "fake secret timeout detail" not in repr(result)
    assert not hasattr(result, "exception")


def test_provider_exception_is_normalized_without_partial_candidates_or_text(caplog):
    provider = FakeDiscoveryProvider(
        announcements=(announcement(),),
        error=RuntimeError("fake local key and UDP payload"),
    )

    result = discover_candidates(provider, "fake-device-id", timeout_seconds=1.0)

    assert result.status is DiscoveryResultStatus.FAILED
    assert result.failure is DiscoveryFailure.PROVIDER_ERROR
    assert result.candidates == ()
    assert "fake local key" not in repr(result)
    assert "UDP payload" not in repr(result)
    assert "fake local key" not in caplog.text
    assert "UDP payload" not in caplog.text
    assert provider.operation_calls == ["discover"]


@pytest.mark.parametrize("timeout_seconds", [0, -1, math.nan, math.inf, True])
def test_invalid_timeout_fails_before_calling_provider(timeout_seconds):
    provider = FakeDiscoveryProvider((announcement(),))

    result = discover_candidates(
        provider, "fake-device-id", timeout_seconds=timeout_seconds
    )

    assert result.status is DiscoveryResultStatus.FAILED
    assert result.failure is DiscoveryFailure.INVALID_REQUEST
    assert provider.calls == []


def test_fake_provider_path_does_not_open_sockets(monkeypatch):
    def forbidden_socket(*_args, **_kwargs):
        pytest.fail("candidate discovery must not create a socket")

    monkeypatch.setattr(socket, "socket", forbidden_socket)
    provider = FakeDiscoveryProvider((announcement(),))

    result = discover_candidates(provider, "fake-device-id", timeout_seconds=1.0)

    assert result.status is DiscoveryResultStatus.CANDIDATES
