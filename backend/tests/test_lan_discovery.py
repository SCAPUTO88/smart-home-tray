from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace
import pytest

import tinytuya
from smart_home_tray.discovery import DiscoveryAnnouncement, DiscoveryResultStatus, discover_candidates
from smart_home_tray.lan_discovery import TinyTuyaLanDiscoveryProvider, decode_announcement


DEVICE_ID = "synthetic-device-012345"


def packet_33(device_id: str = DEVICE_ID, ip: str = "192.0.2.44") -> bytes:
    payload = json.dumps({"gwId": device_id, "ip": ip, "version": "3.3"}).encode()
    return tinytuya.encrypt(payload, tinytuya.udpkey)


def packet_33_frame(device_id: str = DEVICE_ID) -> bytes:
    payload = b"\x00\x00\x00\x00" + json.dumps(
        {"gwId": device_id, "version": "3.3"}
    ).encode()
    message = tinytuya.TuyaMessage(
        0,
        tinytuya.REQ_DEVINFO,
        None,
        payload,
        0,
        True,
        tinytuya.PREFIX_55AA_VALUE,
        True,
    )
    return tinytuya.pack_message(message)


def packet_35(device_id: str = DEVICE_ID) -> bytes:
    payload = json.dumps({"gwId": device_id, "version": "3.5"}).encode()
    message = tinytuya.TuyaMessage(
        0,
        tinytuya.REQ_DEVINFO,
        None,
        payload,
        0,
        True,
        tinytuya.PREFIX_6699_VALUE,
        True,
    )
    return tinytuya.pack_message(message, hmac_key=tinytuya.udpkey)


@pytest.mark.parametrize("version", ["3.3", "3.5"])
def test_decode_announcement_allowlists_only_id_source_ip_and_version(version):
    packet = packet_33() if version == "3.3" else packet_35()
    result = decode_announcement(packet, ("192.0.2.50", 6667))

    assert result == DiscoveryAnnouncement(DEVICE_ID, "192.0.2.50", version)


def test_decode_announcement_accepts_33_inside_55aa_frame():
    assert decode_announcement(packet_33_frame(), ("192.0.2.50", 6667)) == DiscoveryAnnouncement(
        DEVICE_ID, "192.0.2.50", "3.3"
    )


@pytest.mark.parametrize("packet", [b"", b"broken", b"{}", b'{"gwId":'])
def test_decode_rejects_invalid_truncated_and_missing_id_packets(packet):
    assert decode_announcement(packet, ("192.0.2.50", 6667)) is None


def test_decode_rejects_invalid_source_and_unsupported_records():
    assert decode_announcement(packet_33(), ("not-an-ip", 6667)) is None
    unsupported = tinytuya.encrypt(b'{"gwId":"fake","version":"9.9"}', tinytuya.udpkey)
    assert decode_announcement(unsupported, ("192.0.2.50", 6667)) is None


class FakeSocket:
    def __init__(self, factory, _family, _kind, _protocol=0):
        self.factory = factory
        self.closed = False
        self.bound = None
        self.sent = []
        self.options = []
        self.timeout = None
        factory.sockets.append(self)

    def setsockopt(self, *args):
        self.options.append(args)

    def bind(self, address):
        self.bound = address
        if self.factory.bind_clock is not None:
            self.factory.bind_clock.advance(self.factory.bind_delay)
        if address[1] in self.factory.bind_fail_ports:
            raise OSError("synthetic bind error")

    def settimeout(self, value):
        self.timeout = value

    def sendto(self, packet, address):
        if self.factory.send_error:
            raise OSError("synthetic send failure")
        self.sent.append((packet, address))

    def recvfrom(self, _size):
        if self.factory.receive_error or self.bound[1] in self.factory.receive_error_ports:
            self.factory.receive_calls += 1
            raise OSError("synthetic receive failure")
        self.factory.receive_calls += 1
        return self.factory.datagrams.pop(0)

    def close(self):
        self.closed = True


class FakeSocketFactory:
    def __init__(
        self,
        datagrams=(),
        bind_fail_ports=(),
        receive_error=False,
        receive_error_ports=(),
        bind_clock=None,
        bind_delay=0.0,
        send_error=False,
    ):
        self.datagrams = list(datagrams)
        self.bind_fail_ports = set(bind_fail_ports)
        self.receive_error = receive_error
        self.receive_error_ports = set(receive_error_ports)
        self.bind_clock = bind_clock
        self.bind_delay = bind_delay
        self.send_error = send_error
        self.receive_calls = 0
        self.sockets = []

    def __call__(self, *args):
        return FakeSocket(self, *args)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_provider(factory, clock, *, interfaces=None, packet_limit=256, candidate_limit=64):
    def wait_readable(sockets, timeout):
        clock.advance(timeout)
        ready = [sock for sock in sockets if factory.receive_error or sock.bound[1] in factory.receive_error_ports]
        if factory.datagrams:
            healthy = next((sock for sock in sockets if sock not in ready), None)
            if healthy is not None:
                ready.append(healthy)
        return ready, [], []

    return TinyTuyaLanDiscoveryProvider(
        socket_factory=factory,
        interface_provider=(
            interfaces
            if interfaces is not None
            else lambda: (("192.0.2.255", "192.0.2.2", "255.255.255.0"),)
        ),
        wait_readable=wait_readable,
        monotonic=clock,
        max_packets=packet_limit,
        max_candidates=candidate_limit,
        max_duration_seconds=3.0,
    )


def test_provider_collects_matching_only_and_normalizer_preserves_conflicting_ips():
    factory = FakeSocketFactory(
        [
            (packet_33(), ("192.0.2.44", 6667)),
            (packet_33("other-id"), ("192.0.2.45", 6667)),
            (packet_35(), ("192.0.2.46", 7000)),
        ]
    )
    clock = FakeClock()
    provider = make_provider(factory, clock)

    result = discover_candidates(provider, DEVICE_ID, timeout_seconds=1.0)

    assert result.status is DiscoveryResultStatus.AMBIGUOUS
    assert [str(candidate.address) for candidate in result.candidates] == ["192.0.2.44", "192.0.2.46"]
    assert all(sock.closed for sock in factory.sockets)


def test_packet_budget_saturation_fails_closed():
    factory = FakeSocketFactory([(packet_33(), (f"192.0.2.{i}", 6667)) for i in (10, 11, 12)])
    clock = FakeClock()
    provider = make_provider(factory, clock, packet_limit=2, candidate_limit=10)

    with pytest.raises(RuntimeError, match="collection limit"):
        provider.discover(DEVICE_ID, timeout_seconds=1.0)
    assert all(sock.closed for sock in factory.sockets)


def test_provider_enforces_candidate_limit_even_with_packet_budget_remaining():
    factory = FakeSocketFactory([(packet_33(), (f"192.0.2.{i}", 6667)) for i in (10, 11, 12)])
    provider = make_provider(factory, FakeClock(), packet_limit=20, candidate_limit=1)

    with pytest.raises(RuntimeError, match="collection limit"):
        provider.discover(DEVICE_ID, timeout_seconds=1.0)
    assert len(factory.datagrams) == 2


def test_provider_timeout_and_bind_failure_release_every_socket():
    factory = FakeSocketFactory(bind_fail_ports={6666, 6667, 7000})
    provider = make_provider(factory, FakeClock())

    with pytest.raises(OSError):
        provider.discover(DEVICE_ID, timeout_seconds=1.0)

    assert all(sock.closed for sock in factory.sockets)


def test_provider_reports_interface_enumeration_failure():
    factory = FakeSocketFactory()
    provider = make_provider(factory, FakeClock(), interfaces=lambda: (_ for _ in ()).throw(OSError()))

    with pytest.raises(OSError, match="interface enumeration failed"):
        provider.discover(DEVICE_ID, timeout_seconds=0.2)

    assert len(factory.sockets) == 3
    assert all(sock.closed for sock in factory.sockets)


def test_no_broadcast_capable_interfaces_still_completes_passive_window():
    factory = FakeSocketFactory()
    provider = make_provider(factory, FakeClock(), interfaces=lambda: ())

    assert provider.discover(DEVICE_ID, timeout_seconds=0.2) == []
    assert len(factory.sockets) == 3
    assert all(sock.closed for sock in factory.sockets)


def test_failed_broadcast_is_not_reported_as_not_found():
    factory = FakeSocketFactory(send_error=True)
    provider = make_provider(factory, FakeClock())

    with pytest.raises(OSError, match="broadcast failed"):
        provider.discover(DEVICE_ID, timeout_seconds=0.2)

    assert all(sock.closed for sock in factory.sockets)


def test_default_interface_enumeration_uses_local_addresses_without_route_probe(monkeypatch):
    import tinytuya.scanner as scanner
    import smart_home_tray.lan_discovery as lan_discovery

    class FakePsutil:
        @staticmethod
        def net_if_addrs():
            return {
                "fake-interface": [
                    SimpleNamespace(family=lan_discovery.socket.AF_INET, address="192.0.2.2", broadcast="192.0.2.255", netmask="255.255.255.0"),
                    SimpleNamespace(family=lan_discovery.socket.AF_INET, address="192.0.2.3", broadcast="192.0.2.255", netmask="255.255.255.0"),
                ],
                "down-interface": [
                    SimpleNamespace(family=lan_discovery.socket.AF_INET, address="198.51.100.2", broadcast="198.51.100.255", netmask="255.255.255.0"),
                ],
            }

        @staticmethod
        def net_if_stats():
            return {"fake-interface": SimpleNamespace(isup=True)}

    monkeypatch.setitem(sys.modules, "psutil", FakePsutil)
    monkeypatch.setattr(scanner, "get_ip_to_broadcast", lambda: pytest.fail("unsafe route fallback used"))

    assert TinyTuyaLanDiscoveryProvider._default_interfaces() == (
        ("192.0.2.255", "192.0.2.2", "255.255.255.0"),
        ("192.0.2.255", "192.0.2.3", "255.255.255.0"),
    )


def test_clean_backend_install_declares_interface_enumerator():
    project = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert any(requirement.lower().startswith("psutil") for requirement in project["project"]["dependencies"])


def test_repeated_receive_oserror_retires_failed_listeners_without_busy_loop():
    factory = FakeSocketFactory(receive_error=True)
    wait_calls = []
    provider = TinyTuyaLanDiscoveryProvider(
        socket_factory=factory,
        interface_provider=lambda: (),
        wait_readable=lambda sockets, _timeout: (wait_calls.append(tuple(sockets)) or (list(sockets), [], [])),
        monotonic=FakeClock(),
        max_duration_seconds=3.0,
    )

    with pytest.raises(OSError, match="listeners failed"):
        provider.discover(DEVICE_ID, timeout_seconds=3.0)

    assert factory.receive_calls == 9
    assert len(wait_calls) == 3
    assert all(sock.closed for sock in factory.sockets)


def test_healthy_listener_keeps_collecting_after_another_listener_fails():
    factory = FakeSocketFactory(
        datagrams=[(packet_33(), ("192.0.2.44", 6667))],
        receive_error_ports={6666},
    )
    provider = make_provider(factory, FakeClock())

    results = provider.discover(DEVICE_ID, timeout_seconds=1.0)

    assert results == [DiscoveryAnnouncement(DEVICE_ID, "192.0.2.44", "3.3")]
    assert all(sock.closed for sock in factory.sockets)


def test_provider_does_not_log_or_return_packet_payload_fields(caplog):
    secretish = packet_33()
    factory = FakeSocketFactory([(secretish, ("192.0.2.44", 6667))])
    provider = make_provider(factory, FakeClock())

    results = provider.discover(DEVICE_ID, timeout_seconds=1.0)

    assert results == [DiscoveryAnnouncement(DEVICE_ID, "192.0.2.44", "3.3")]
    assert secretish.hex() not in repr(results)
    assert secretish.hex() not in caplog.text


def test_provider_never_uses_scanner_files_or_device_operations(monkeypatch):
    factory = FakeSocketFactory()
    provider = make_provider(factory, FakeClock())
    import tinytuya.scanner as scanner

    forbidden = lambda *_args, **_kwargs: pytest.fail("forbidden TinyTuya operation called")
    for name in ("Device", "find_device", "deviceScan", "load_devicefile"):
        if hasattr(tinytuya, name):
            monkeypatch.setattr(tinytuya, name, forbidden)
    monkeypatch.setattr(scanner, "devices", forbidden)

    assert provider.discover(DEVICE_ID, timeout_seconds=0.01) == []

    assert all(sock.closed for sock in factory.sockets)


def test_expired_caller_budget_normalizes_to_timeout_without_sensitive_details():
    factory = FakeSocketFactory()
    provider = make_provider(factory, FakeClock())

    result = discover_candidates(provider, DEVICE_ID, timeout_seconds=0.2)

    assert result.status is DiscoveryResultStatus.NOT_FOUND
    assert "synthetic" not in repr(result)
    assert all(sock.closed for sock in factory.sockets)


@pytest.mark.parametrize("timeout_seconds", [0.2, 1.0, 3.0, 5.0])
def test_empty_completed_listening_window_is_not_found(timeout_seconds):
    factory = FakeSocketFactory()
    provider = make_provider(factory, FakeClock())

    result = discover_candidates(provider, DEVICE_ID, timeout_seconds=timeout_seconds)

    assert result.status is DiscoveryResultStatus.NOT_FOUND
    assert result.candidates == ()
    assert all(sock.closed for sock in factory.sockets)


def test_budget_consumed_before_first_listen_is_operational_timeout():
    clock = FakeClock()
    factory = FakeSocketFactory(bind_clock=clock, bind_delay=0.2)
    provider = make_provider(factory, clock)

    result = discover_candidates(provider, DEVICE_ID, timeout_seconds=0.2)

    assert result.status is DiscoveryResultStatus.FAILED
    assert result.failure.value == "timeout"
    assert all(sock.closed for sock in factory.sockets)


def test_first_candidate_followed_by_packet_budget_saturation_fails_closed():
    factory = FakeSocketFactory([
        (packet_33(), ("192.0.2.44", 6667)),
        (packet_33(), ("192.0.2.45", 6667)),
    ])
    provider = make_provider(factory, FakeClock(), packet_limit=1)

    result = discover_candidates(provider, DEVICE_ID, timeout_seconds=1.0)

    assert result.status is DiscoveryResultStatus.FAILED
    assert result.candidates == ()
    assert result.failure.value == "provider_error"
    assert all(sock.closed for sock in factory.sockets)


def test_candidate_budget_saturation_fails_closed():
    factory = FakeSocketFactory([
        (packet_33(), ("192.0.2.44", 6667)),
        (packet_33(), ("192.0.2.45", 6667)),
    ])
    provider = make_provider(factory, FakeClock(), candidate_limit=1)

    result = discover_candidates(provider, DEVICE_ID, timeout_seconds=1.0)

    assert result.status is DiscoveryResultStatus.FAILED
    assert result.candidates == ()
    assert result.failure.value == "provider_error"
    assert all(sock.closed for sock in factory.sockets)


def test_broadcast_interfaces_are_validated_and_send_sockets_are_capped():
    interfaces = [
        ("192.0.2.255", "192.0.2.2", "255.255.255.0"),
        ("not-an-ip", "198.51.100.2", "255.255.255.0"),
        ("198.51.100.255", "0.0.0.0", "255.255.255.0"),
        ("203.0.113.255", "203.0.113.2", "255.255.255.0"),
        ("203.0.113.254", "203.0.113.3", "255.255.255.0"),
        *((f"10.1.{n}.255", f"10.1.{n}.2", "255.255.255.0") for n in range(20)),
    ]
    factory = FakeSocketFactory()
    clock = FakeClock()
    provider = TinyTuyaLanDiscoveryProvider(
        socket_factory=factory,
        interface_provider=lambda: interfaces,
        wait_readable=lambda _sockets, timeout: (clock.advance(timeout) or ([], [], [])),
        monotonic=clock,
        max_broadcast_interfaces=2,
        max_duration_seconds=0.1,
    )

    with pytest.raises(RuntimeError, match="interface limit"):
        provider.discover(DEVICE_ID, timeout_seconds=0.1)

    transmissions = [sock.sent[0][1] for sock in factory.sockets if sock.sent]
    assert transmissions == [("192.0.2.255", 7000), ("203.0.113.255", 7000)]
    assert len(transmissions) <= 2


def test_provider_rejects_concurrent_scan_without_opening_more_sockets():
    factory = FakeSocketFactory()
    provider = None
    clock = FakeClock()

    def nested_interface_enumeration():
        with pytest.raises(RuntimeError, match="already active"):
            provider.discover(DEVICE_ID, timeout_seconds=0.1)
        return (("192.0.2.255", "192.0.2.2", "255.255.255.0"),)

    provider = TinyTuyaLanDiscoveryProvider(
        socket_factory=factory,
        interface_provider=nested_interface_enumeration,
        wait_readable=lambda _sockets, timeout: (clock.advance(timeout) or ([], [], [])),
        monotonic=clock,
        max_duration_seconds=0.1,
    )

    assert provider.discover(DEVICE_ID, timeout_seconds=0.1) == []
    assert len(factory.sockets) == 4
    assert sum(bool(sock.sent) for sock in factory.sockets) == 1
    assert all(sock.closed for sock in factory.sockets)


def test_provider_collapses_duplicates_only_in_f2eb_normalizer():
    duplicate = (packet_33(), ("192.0.2.44", 6667))
    factory = FakeSocketFactory([duplicate, duplicate])
    provider = make_provider(factory, FakeClock())

    result = discover_candidates(provider, DEVICE_ID, timeout_seconds=1.0)

    assert result.status is DiscoveryResultStatus.CANDIDATES
    assert len(result.candidates) == 1


def test_duplicate_packets_do_not_consume_distinct_candidate_limit():
    same_address = (packet_33(), ("192.0.2.44", 6667))
    other_address = (packet_35(), ("192.0.2.45", 7000))
    factory = FakeSocketFactory([same_address, same_address, other_address])
    provider = make_provider(factory, FakeClock(), packet_limit=10, candidate_limit=3)

    result = discover_candidates(provider, DEVICE_ID, timeout_seconds=1.0)

    assert result.status is DiscoveryResultStatus.AMBIGUOUS
    assert len(result.candidates) == 2

