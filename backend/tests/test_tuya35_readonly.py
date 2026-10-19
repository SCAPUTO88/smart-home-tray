from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import socket
from collections import deque

import pytest
import tinytuya

from smart_home_tray.models import DeviceConfig, DPSMap, ValueRange
from smart_home_tray.tuya35_readonly import (
    ReadOnlyError,
    ReadOnlyFailure,
    TinyTuya35ReadOnlyClient,
    validate_candidate_address,
)


DEVICE_ID = "synthetic-device-id"
LOCAL_KEY = "synthetic-key-12"
ADDRESS = "10.70.4.20"
SESSION_REMOTE_NONCE = b"remote-nonce-123"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeSocket:
    def __init__(self, response_factory, *, chunks=None, fail_recv=None) -> None:
        self.response_factory = response_factory
        self.chunks = deque(chunks or ())
        self.fail_recv = fail_recv
        self.sent: list[bytes] = []
        self.timeout_values: list[float] = []
        self.closed = False
        self.connected = None

    def settimeout(self, value: float) -> None:
        self.timeout_values.append(value)

    def connect(self, endpoint) -> None:
        self.connected = endpoint

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)
        if not self.chunks:
            self.chunks.extend(self.response_factory(data, len(self.sent)))

    def recv(self, size: int) -> bytes:
        if self.fail_recv is not None:
            raise self.fail_recv
        if not self.chunks:
            raise socket.timeout()
        chunk = self.chunks.popleft()
        if len(chunk) > size:
            self.chunks.appendleft(chunk[size:])
            return chunk[:size]
        return chunk

    def close(self) -> None:
        self.closed = True


def _config(*, key: str = LOCAL_KEY, address: str = "10.70.4.10") -> DeviceConfig:
    return DeviceConfig(
        device_id=DEVICE_ID,
        name="synthetic lamp",
        address=address,
        protocol_version=3.5,
        local_key=key,
        dps=DPSMap(power=20, work_mode=21, white_brightness=22),
        white_brightness_range=ValueRange(10, 1000),
    )


def _network_interfaces():
    return (("10.70.4.10", "255.255.255.0", True),)


def _derive_session_key(local_nonce: bytes, remote_nonce: bytes) -> bytes:
    mixed = bytes(a ^ b for a, b in zip(local_nonce, remote_nonce, strict=True))
    cipher = tinytuya.AESCipher(LOCAL_KEY.encode("ascii"))
    iv = local_nonce[:12]
    encrypted = cipher.encrypt(mixed, use_base64=False, pad=False, iv=iv)
    return encrypted[12:28]


def _unpack(data: bytes, key: bytes):
    header = tinytuya.parse_header(data)
    return tinytuya.unpack_message(data, hmac_key=key, header=header, no_retcode=None)


def _response_factory(
    *, bad_handshake_hmac=False, bad_status_tag=False, status_payload=None,
    status_command=None, status_retcode=0, bad_status_suffix=False
):
    local_key = LOCAL_KEY.encode("ascii")
    session: dict[str, bytes] = {}

    def build(client_frame: bytes, ordinal: int):
        request_key = session["key"] if ordinal >= 3 else local_key
        request = _unpack(client_frame, request_key)
        if ordinal == 1:
            local_nonce = request.payload
            remote_nonce = SESSION_REMOTE_NONCE
            digest = hmac.new(local_key, local_nonce, hashlib.sha256).digest()
            if bad_handshake_hmac:
                digest = b"x" * len(digest)
            payload = remote_nonce + digest
            response = tinytuya.TuyaMessage(
                80, tinytuya.SESS_KEY_NEG_RESP, 0, payload, 0, True,
                tinytuya.PREFIX_6699_VALUE, b"R" * 12,
            )
            session["key"] = _derive_session_key(local_nonce, remote_nonce)
            return [tinytuya.pack_message(response, hmac_key=local_key)]
        if ordinal == 2:
            return []
        response_payload = status_payload
        if response_payload is None:
            response_payload = json.dumps({"dps": {"20": True, "21": "white"}}).encode()
        response = tinytuya.TuyaMessage(
            93, status_command or tinytuya.DP_QUERY_NEW, status_retcode, response_payload, 0, True,
            tinytuya.PREFIX_6699_VALUE, b"S" * 12,
        )
        frame = tinytuya.pack_message(response, hmac_key=session["key"])
        if bad_status_tag:
            frame = frame[:-8] + bytes([frame[-8] ^ 1]) + frame[-7:]
        if bad_status_suffix:
            frame = frame[:-1] + bytes([frame[-1] ^ 1])
        return [frame]

    return build


def _client(fake_socket, *, clock=None, entropy=None, interface_reader=None):
    if entropy is None:
        counter = 0

        def entropy(length):
            nonlocal counter
            counter += 1
            return bytes([counter]) * length

    return TinyTuya35ReadOnlyClient(
        _config(),
        ADDRESS,
        candidate_device_id=DEVICE_ID,
        announced_versions=("3.5",),
        socket_factory=lambda *_args: fake_socket,
        clock=clock or FakeClock(),
        entropy=entropy or (lambda length: bytes(range(16))[:length]),
        interface_reader=interface_reader or _network_interfaces,
    )


def test_read_only_exchange_authenticates_handshake_and_status_then_closes():
    fake_socket = FakeSocket(_response_factory())
    client = _client(fake_socket)

    dps = client.read_authenticated_dps(deadline=100.0)

    assert dps == {"20": True, "21": "white"}
    assert fake_socket.connected == ((ADDRESS, 6668))
    assert len(fake_socket.sent) == 3  # start, finish, one query; finish is sent without a reply
    commands = [
        _unpack(frame, LOCAL_KEY.encode() if index < 2 else _derive_session_key(
            bytes([1]) * 16, SESSION_REMOTE_NONCE
        )).cmd
        for index, frame in enumerate(fake_socket.sent)
    ]
    assert commands == [
        tinytuya.SESS_KEY_NEG_START,
        tinytuya.SESS_KEY_NEG_FINISH,
        tinytuya.DP_QUERY_NEW,
    ]
    query = _unpack(fake_socket.sent[2], _derive_session_key(bytes([1]) * 16, SESSION_REMOTE_NONCE))
    assert query.payload == b"{}"
    assert not hasattr(client, "status")
    assert not hasattr(client, "set_value")
    assert fake_socket.closed


def test_outgoing_frames_use_distinct_explicit_ivs_even_in_debug(caplog, monkeypatch):
    fake_socket = FakeSocket(_response_factory())
    client = _client(fake_socket)
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(logging.getLogger("tinytuya"), "level", logging.DEBUG)

    client.read_authenticated_dps(deadline=2.5)

    local_key = LOCAL_KEY.encode()
    session_key = _derive_session_key(bytes([1]) * 16, SESSION_REMOTE_NONCE)
    messages = [
        _unpack(fake_socket.sent[0], local_key),
        _unpack(fake_socket.sent[1], local_key),
        _unpack(fake_socket.sent[2], session_key),
    ]
    ivs = [message.iv for message in messages]
    assert len(set(ivs)) == 3
    assert all(len(iv) == 12 and iv != b"0123456789ab" for iv in ivs)


@pytest.mark.parametrize(
    ("factory_kwargs", "expected"),
    [
        ({"bad_handshake_hmac": True}, ReadOnlyFailure.AUTH_FAILED),
        ({"bad_status_tag": True}, ReadOnlyFailure.AUTH_FAILED),
    ],
)
def test_rejects_invalid_handshake_hmac_or_gcm_tag(factory_kwargs, expected):
    fake_socket = FakeSocket(_response_factory(**factory_kwargs))
    client = _client(fake_socket)

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)
    assert error.value.failure is expected
    assert fake_socket.closed


def test_wrong_16_byte_local_key_fails_gcm_authentication():
    fake_socket = FakeSocket(_response_factory())
    client = TinyTuya35ReadOnlyClient(
        _config(key="wrong-key-123456"),
        ADDRESS,
        candidate_device_id=DEVICE_ID,
        announced_versions=("3.5",),
        socket_factory=lambda *_args: fake_socket,
        clock=FakeClock(),
        entropy=lambda length: b"N" * length,
        interface_reader=_network_interfaces,
    )

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)

    assert error.value.failure is ReadOnlyFailure.AUTH_FAILED
    assert fake_socket.closed


def test_rejects_55aa_even_when_it_contains_plausible_status():
    fake_socket = FakeSocket(_response_factory())
    # A legacy response is injected before any valid 6699 frame.
    fake_socket.chunks.extend([b"\x00\x00\x55\xaa" + b"\x00" * 64])
    client = _client(fake_socket)

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)
    assert error.value.failure is ReadOnlyFailure.INVALID_RESPONSE


def test_fragmented_frames_share_one_deadline_and_are_closed():
    response_factory = _response_factory()

    def fragmented(frame, ordinal):
        frames = response_factory(frame, ordinal)
        return [part for packet in frames for part in (packet[:3], packet[3:11], packet[11:])]

    fake_socket = FakeSocket(fragmented)
    client = _client(fake_socket)
    assert client.read_authenticated_dps(deadline=100.0)["20"] is True
    assert max(fake_socket.timeout_values) <= 2.5
    assert fake_socket.closed


def test_deadline_expiry_during_receive_is_typed_and_closes_socket():
    clock = FakeClock()

    class ExpiringSocket(FakeSocket):
        def recv(self, size: int) -> bytes:
            clock.now = 3.0
            raise socket.timeout()

    fake_socket = ExpiringSocket(_response_factory())
    client = _client(fake_socket, clock=clock)

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)
    assert error.value.failure is ReadOnlyFailure.TIMEOUT
    assert fake_socket.closed


def test_nonstandard_interruption_still_closes_socket():
    class InterruptedSocket(FakeSocket):
        def recv(self, size: int) -> bytes:
            raise KeyboardInterrupt()

    fake_socket = InterruptedSocket(_response_factory())
    client = _client(fake_socket)

    with pytest.raises(KeyboardInterrupt):
        client.read_authenticated_dps(deadline=2.5)

    assert fake_socket.closed


def test_rejects_replayed_handshake_from_different_client_nonce():
    prior_nonce = bytes(range(16))
    prior_digest = hmac.new(LOCAL_KEY.encode(), prior_nonce, hashlib.sha256).digest()
    replayed = tinytuya.pack_message(
        tinytuya.TuyaMessage(
            80, tinytuya.SESS_KEY_NEG_RESP, 0,
            SESSION_REMOTE_NONCE + prior_digest, 0, True,
            tinytuya.PREFIX_6699_VALUE, b"R" * 12,
        ),
        hmac_key=LOCAL_KEY.encode(),
    )
    fake_socket = FakeSocket(lambda _frame, _ordinal: [replayed])
    client = _client(fake_socket, entropy=lambda length: b"N" * length)

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)
    assert error.value.failure is ReadOnlyFailure.AUTH_FAILED


def test_debug_logging_does_not_emit_key_or_frames(caplog, monkeypatch):
    fake_socket = FakeSocket(_response_factory(bad_status_tag=True))
    client = _client(fake_socket)
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(logging.getLogger("tinytuya"), "level", logging.DEBUG)

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)
    assert error.value.failure is ReadOnlyFailure.AUTH_FAILED

    rendered = caplog.text
    assert LOCAL_KEY not in rendered
    assert DEVICE_ID not in rendered
    assert "remote-nonce" not in rendered
    assert "b'\\x00" not in rendered


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b'{"dps":{}}',
        b'{"dps":{"20":true,"20":false}}',
        b'{"dps":{"20":NaN}}',
        b'{"dps":{"20":{"nested":true}}}',
    ],
)
def test_rejects_malformed_or_ambiguous_status_json(payload):
    fake_socket = FakeSocket(_response_factory(status_payload=payload))
    client = _client(fake_socket)

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)

    assert error.value.failure is ReadOnlyFailure.INVALID_RESPONSE
    assert fake_socket.closed


def test_cleanup_failure_discards_otherwise_valid_read():
    class CleanupFailureSocket(FakeSocket):
        def close(self):
            raise OSError("synthetic close failure")

    fake_socket = CleanupFailureSocket(_response_factory())
    client = _client(fake_socket)

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)

    assert error.value.failure is ReadOnlyFailure.CLEANUP_FAILED


def test_limits_frame_payload_and_rejects_saturation():
    oversized = json.dumps({"dps": {"20": "x" * 1500}}).encode()
    fake_socket = FakeSocket(_response_factory(status_payload=oversized))
    client = _client(fake_socket)

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)

    assert error.value.failure is ReadOnlyFailure.INVALID_RESPONSE
    assert fake_socket.closed


def test_rejects_response_command_outside_status_allowlist():
    fake_socket = FakeSocket(
        _response_factory(status_command=tinytuya.CONTROL_NEW)
    )
    client = _client(fake_socket)

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)

    assert error.value.failure is ReadOnlyFailure.INVALID_RESPONSE
    assert fake_socket.closed


def test_rejects_wrong_6699_suffix_even_when_gcm_tag_is_valid():
    fake_socket = FakeSocket(_response_factory(bad_status_suffix=True))
    client = _client(fake_socket)

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)

    assert error.value.failure is ReadOnlyFailure.INVALID_RESPONSE
    assert fake_socket.closed


def test_accepts_status_with_explicit_35_payload_header():
    response = b"3.5" + tinytuya.PROTOCOL_3x_HEADER + b'{"dps":{"20":true}}'
    fake_socket = FakeSocket(_response_factory(status_payload=response))
    client = _client(fake_socket)

    assert client.read_authenticated_dps(deadline=2.5) == {"20": True}
    assert fake_socket.closed


def test_rejects_status_without_explicit_success_retcode():
    fake_socket = FakeSocket(
        _response_factory(status_retcode=None)
    )
    client = _client(fake_socket)

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)

    assert error.value.failure is ReadOnlyFailure.INVALID_RESPONSE
    assert fake_socket.closed


def test_frame_count_budget_is_fail_closed(monkeypatch):
    import smart_home_tray.tuya35_readonly as transport

    monkeypatch.setattr(transport, "MAX_FRAMES", 3)
    fake_socket = FakeSocket(_response_factory())
    client = _client(fake_socket)

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)

    assert error.value.failure is ReadOnlyFailure.INVALID_RESPONSE
    assert len(fake_socket.sent) == 2
    assert fake_socket.closed


def test_total_byte_budget_is_fail_closed(monkeypatch):
    import smart_home_tray.tuya35_readonly as transport

    monkeypatch.setattr(transport, "MAX_BYTES", 300)
    fake_socket = FakeSocket(_response_factory())
    client = _client(fake_socket)

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)

    assert error.value.failure is ReadOnlyFailure.INVALID_RESPONSE
    assert fake_socket.closed


def test_unsupported_tinytuya_version_fails_before_socket(monkeypatch):
    import smart_home_tray.tuya35_readonly as transport

    opened = []
    monkeypatch.setattr(transport.importlib.metadata, "version", lambda _name: "1.21.0")
    client = TinyTuya35ReadOnlyClient(
        _config(),
        ADDRESS,
        candidate_device_id=DEVICE_ID,
        announced_versions=("3.5",),
        socket_factory=lambda *_args: opened.append(True),
        clock=FakeClock(),
        entropy=lambda length: b"N" * length,
        interface_reader=_network_interfaces,
    )

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)

    assert error.value.failure is ReadOnlyFailure.DEPENDENCY_UNSUPPORTED
    assert opened == []


def test_invalid_local_key_fails_before_socket():
    opened = []
    client = TinyTuya35ReadOnlyClient(
        _config(key="too-short"),
        ADDRESS,
        candidate_device_id=DEVICE_ID,
        announced_versions=("3.5",),
        socket_factory=lambda *_args: opened.append(True),
        clock=FakeClock(),
        entropy=lambda length: b"N" * length,
        interface_reader=_network_interfaces,
    )

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)

    assert error.value.failure is ReadOnlyFailure.PROTOCOL_NOT_ELIGIBLE
    assert opened == []


def test_closed_client_returns_distinct_closed_failure():
    fake_socket = FakeSocket(_response_factory())
    client = _client(fake_socket)
    client.close()

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)

    assert error.value.failure is ReadOnlyFailure.CLOSED
    assert fake_socket.connected is None


def test_validation_budget_caps_caller_deadline_and_covers_interface_enumeration():
    clock = FakeClock()
    opened = []

    def slow_interfaces():
        clock.now = 3.0
        return _network_interfaces()

    client = TinyTuya35ReadOnlyClient(
        _config(),
        ADDRESS,
        candidate_device_id=DEVICE_ID,
        announced_versions=("3.5",),
        socket_factory=lambda *_args: opened.append(True),
        clock=clock,
        entropy=lambda length: b"N" * length,
        interface_reader=slow_interfaces,
    )

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=100.0)

    assert error.value.failure is ReadOnlyFailure.TIMEOUT
    assert opened == []


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), True, "2.5"])
def test_rejects_invalid_deadline(deadline):
    fake_socket = FakeSocket(_response_factory())
    client = _client(fake_socket)

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=deadline)

    assert error.value.failure is ReadOnlyFailure.INVALID_REQUEST
    assert fake_socket.connected is None


def test_rejects_candidate_outside_private_connected_subnet_before_socket():
    opened = []
    client = TinyTuya35ReadOnlyClient(
        _config(),
        "198.51.100.20",
        candidate_device_id=DEVICE_ID,
        announced_versions=("3.5",),
        socket_factory=lambda *_args: opened.append(True),
        clock=FakeClock(),
        entropy=lambda length: b"N" * length,
        interface_reader=_network_interfaces,
    )

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)
    assert error.value.failure is ReadOnlyFailure.PROTOCOL_NOT_ELIGIBLE
    assert opened == []


def test_candidate_device_id_must_match_registered_config_before_socket():
    opened = []
    client = TinyTuya35ReadOnlyClient(
        _config(),
        ADDRESS,
        candidate_device_id="different-synthetic-id",
        announced_versions=("3.5",),
        socket_factory=lambda *_args: opened.append(True),
        clock=FakeClock(),
        entropy=lambda length: b"N" * length,
        interface_reader=_network_interfaces,
    )

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)

    assert error.value.failure is ReadOnlyFailure.PROTOCOL_NOT_ELIGIBLE
    assert opened == []


@pytest.mark.parametrize("address", ["8.8.8.8", "10.70.4.0", "10.70.4.255", "10.70.4.10"])
def test_candidate_address_must_be_private_host_on_other_connected_subnet(address):
    assert not validate_candidate_address(
        ipaddress.IPv4Address(address), _network_interfaces()
    )


def test_candidate_address_accepts_private_host_on_connected_subnet():
    assert validate_candidate_address(
        ipaddress.IPv4Address(ADDRESS), _network_interfaces()
    )


def test_candidate_requires_specific_connected_private_netmask():
    candidate = ipaddress.IPv4Address(ADDRESS)

    assert not validate_candidate_address(candidate, (("10.70.4.10", "0.0.0.0", True),))
    assert not validate_candidate_address(candidate, (("10.70.4.10", "255.255.255.254", True),))
    assert validate_candidate_address(
        candidate,
        (
            ("10.70.5.10", "255.255.255.0", True),
            ("10.70.4.10", "255.255.255.0", True),
        ),
    )


def test_interface_enumeration_failure_is_typed_before_socket():
    opened = []
    client = TinyTuya35ReadOnlyClient(
        _config(),
        ADDRESS,
        candidate_device_id=DEVICE_ID,
        announced_versions=("3.5",),
        socket_factory=lambda *_args: opened.append(True),
        clock=FakeClock(),
        entropy=lambda length: b"N" * length,
        interface_reader=lambda: (_ for _ in ()).throw(OSError("synthetic interface failure")),
    )

    with pytest.raises(ReadOnlyError) as error:
        client.read_authenticated_dps(deadline=2.5)

    assert error.value.failure is ReadOnlyFailure.INTERFACE_UNAVAILABLE
    assert opened == []

