"""Strict, single-session Tuya 3.5 read-only transport for recovery validation.

This client uses only the audited TinyTuya 1.20.0 frame and AES-GCM helpers.
It does not instantiate a TinyTuya Device, perform discovery, or expose a write
operation. Its narrow compatibility gate is intentional and fail-closed.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.metadata
import ipaddress
import json
import math
import os
import socket
import time
from collections.abc import Callable, Iterable
from enum import StrEnum
from typing import Any

from smart_home_tray.models import DeviceConfig

MAX_FRAMES = 8
MAX_BYTES = 12 * 1024
MAX_FRAME_PAYLOAD = 1440
MAX_VALIDATION_SECONDS = 2.5
DEVICE_PORT = 6668
_HEADER_6699_BYTES = 18
_RFC1918_NETWORKS = tuple(
    ipaddress.IPv4Network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)

InterfaceRecord = tuple[str, str, bool]
SocketFactory = Callable[..., Any]
InterfaceReader = Callable[[], Iterable[InterfaceRecord]]
Clock = Callable[[], float]
Entropy = Callable[[int], bytes]


class ReadOnlyFailure(StrEnum):
    INVALID_REQUEST = "invalid_request"
    CLOSED = "closed"
    PROTOCOL_NOT_ELIGIBLE = "protocol_not_eligible"
    DEPENDENCY_UNSUPPORTED = "dependency_unsupported"
    INTERFACE_UNAVAILABLE = "interface_unavailable"
    TIMEOUT = "timeout"
    TRANSPORT_FAILED = "transport_failed"
    AUTH_FAILED = "auth_failed"
    INVALID_RESPONSE = "invalid_response"
    CLEANUP_FAILED = "cleanup_failed"


class ReadOnlyError(Exception):
    """Safe typed transport error without the original exception or payload."""

    def __init__(self, failure: ReadOnlyFailure, phase: str) -> None:
        self.failure = failure
        self.phase = phase
        super().__init__(f"{failure.value}:{phase}")


def _tinytuya():
    try:
        import tinytuya
    except Exception:
        raise ReadOnlyError(ReadOnlyFailure.DEPENDENCY_UNSUPPORTED, "preflight") from None
    return tinytuya


def _default_interface_reader() -> tuple[InterfaceRecord, ...]:
    """Enumerate local IPv4 addresses through the declared psutil dependency."""
    import psutil

    stats = psutil.net_if_stats()
    records: list[InterfaceRecord] = []
    for name, addresses in psutil.net_if_addrs().items():
        status = stats.get(name)
        if status is None or not status.isup:
            continue
        for address in addresses:
            if address.family != socket.AF_INET or not address.address or not address.netmask:
                continue
            records.append((address.address, address.netmask, True))
    return tuple(records)


def validate_candidate_address(
    candidate: ipaddress.IPv4Address,
    interfaces: Iterable[InterfaceRecord],
) -> bool:
    """Require an RFC1918 host on an up, directly connected private subnet."""
    if not isinstance(candidate, ipaddress.IPv4Address):
        return False
    if not any(candidate in network for network in _RFC1918_NETWORKS):
        return False

    for address, netmask, is_up in interfaces:
        if not is_up:
            continue
        try:
            local = ipaddress.IPv4Address(address)
            network = ipaddress.IPv4Network((local, netmask), strict=False)
        except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, TypeError):
            continue
        private_block = next(
            (private for private in _RFC1918_NETWORKS if local in private and candidate in private),
            None,
        )
        if private_block is None or not network.subnet_of(private_block):
            continue
        # Exclude point-to-point/tunnel host routes from this LAN-only client.
        if network.prefixlen < private_block.prefixlen or network.prefixlen > 30 or candidate == local:
            continue
        if candidate in network and candidate not in {network.network_address, network.broadcast_address}:
            return True
    return False


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _parse_finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite JSON number")
    return number


def _decode_dps(payload: bytes) -> dict[str, object]:
    """Decode strict 3.5 JSON and validate scalar DPS values without logging them."""
    tinytuya = _tinytuya()

    protocol_header = b"3.5" + tinytuya.PROTOCOL_3x_HEADER
    if payload.startswith(protocol_header):
        payload = payload[len(protocol_header) :]
    document = json.loads(
        payload.decode("utf-8", errors="strict"),
        object_pairs_hook=_strict_object,
        parse_float=_parse_finite_float,
        parse_constant=_reject_json_constant,
    )
    if not isinstance(document, dict):
        raise ValueError("response must be an object")
    dps = document.get("dps")
    if not isinstance(dps, dict) or not dps:
        raise ValueError("missing DPS map")

    normalized: dict[str, object] = {}
    for index, value in dps.items():
        if not isinstance(index, str) or not index.isascii() or not index.isdecimal():
            raise ValueError("invalid DPS index")
        if index.startswith("0") or int(index) <= 0:
            raise ValueError("invalid DPS index")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("invalid DPS number")
        if not isinstance(value, (str, int, float, bool, type(None))):
            raise ValueError("invalid DPS value")
        normalized[index] = value
    return normalized


class TinyTuya35ReadOnlyClient:
    """One connection, authenticated handshake, one query, observed cleanup."""

    def __init__(
        self,
        config: DeviceConfig,
        candidate_address: str | ipaddress.IPv4Address,
        *,
        candidate_device_id: str,
        announced_versions: tuple[str, ...],
        socket_factory: SocketFactory | None = None,
        clock: Clock | None = None,
        entropy: Entropy | None = None,
        interface_reader: InterfaceReader | None = None,
    ) -> None:
        self._config = config
        self._candidate_address = candidate_address
        self._candidate_device_id = candidate_device_id
        self._announced_versions = announced_versions
        self._socket_factory = socket_factory or socket.socket
        self._clock = clock or time.monotonic
        self._entropy = entropy or os.urandom
        self._interface_reader = interface_reader or _default_interface_reader
        self._socket: Any | None = None
        self._closed = False
        self._tx_ivs: set[bytes] = set()
        self._rx_ivs: set[bytes] = set()
        self._frames = 0
        self._bytes = 0
        self._phase = "preflight"

    def read_authenticated_dps(self, *, deadline: float) -> dict[str, object]:
        """Return private DPS only after exchange and cleanup both succeed."""
        result: dict[str, object] | None = None
        failure: ReadOnlyError | None = None
        unhandled: BaseException | None = None
        try:
            started = self._clock()
        except Exception:
            started = 0.0
        try:
            if (
                isinstance(deadline, bool)
                or not isinstance(deadline, (int, float))
                or not math.isfinite(deadline)
            ):
                raise ReadOnlyError(ReadOnlyFailure.INVALID_REQUEST, "preflight")
            bounded_deadline = min(float(deadline), started + MAX_VALIDATION_SECONDS)
            if bounded_deadline <= started:
                raise ReadOnlyError(ReadOnlyFailure.TIMEOUT, "preflight")
            result = self._read(bounded_deadline)
        except ReadOnlyError as error:
            failure = error
        except (socket.timeout, TimeoutError):
            failure = ReadOnlyError(ReadOnlyFailure.TIMEOUT, self._phase)
        except OSError:
            failure = ReadOnlyError(
                ReadOnlyFailure.TIMEOUT if self._clock() >= bounded_deadline else ReadOnlyFailure.TRANSPORT_FAILED,
                self._phase,
            )
        except Exception:
            failure = ReadOnlyError(ReadOnlyFailure.INVALID_RESPONSE, self._phase)
        except BaseException as error:
            unhandled = error
        finally:
            try:
                self.close()
            except ReadOnlyError as error:
                failure = error
            except BaseException as error:
                unhandled = error
            finally:
                # Drop retained references after the single operation. Python
                # bytes and strings cannot be reliably zeroized.
                self._config = None
                self._candidate_address = None
                self._candidate_device_id = None
                self._announced_versions = ()
                self._tx_ivs.clear()
                self._rx_ivs.clear()

        if unhandled is not None:
            raise unhandled

        if failure is None and self._clock() >= bounded_deadline:
            failure = ReadOnlyError(ReadOnlyFailure.TIMEOUT, "cleanup")
        if failure is not None:
            raise failure from None
        assert result is not None
        return result

    def close(self) -> None:
        """Close the sole owned socket, propagating cleanup failure safely."""
        if self._closed:
            return
        self._closed = True
        sock, self._socket = self._socket, None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                raise ReadOnlyError(ReadOnlyFailure.CLEANUP_FAILED, "cleanup") from None

    def _read(self, deadline: float) -> dict[str, object]:
        tinytuya = _tinytuya()

        self._phase = "preflight"
        self._check_deadline(deadline)
        key = self._preflight_key()
        address = self._preflight_address()
        self._phase_deadline(deadline)

        self._phase = "connect"
        self._socket = self._socket_factory(socket.AF_INET, socket.SOCK_STREAM)
        self._phase_deadline(deadline)
        self._set_timeout(deadline)
        try:
            self._socket.connect((str(address), DEVICE_PORT))
        except socket.timeout:
            raise ReadOnlyError(ReadOnlyFailure.TIMEOUT, self._phase) from None
        except OSError:
            raise ReadOnlyError(ReadOnlyFailure.TRANSPORT_FAILED, self._phase) from None
        self._check_deadline(deadline)

        self._phase = "handshake"
        local_nonce = self._random_bytes(16, self._tx_ivs)
        self._send_message(
            seqno=1,
            command=tinytuya.SESS_KEY_NEG_START,
            payload=local_nonce,
            key=key,
            deadline=deadline,
        )
        response = self._receive_message(key=key, deadline=deadline)
        if response.cmd != tinytuya.SESS_KEY_NEG_RESP:
            raise ReadOnlyError(ReadOnlyFailure.INVALID_RESPONSE, self._phase)
        if response.retcode != 0 or len(response.payload) != 48:
            raise ReadOnlyError(ReadOnlyFailure.INVALID_RESPONSE, self._phase)
        remote_nonce = response.payload[:16]
        expected_hmac = hmac.new(key, local_nonce, hashlib.sha256).digest()
        if not hmac.compare_digest(expected_hmac, response.payload[16:48]):
            raise ReadOnlyError(ReadOnlyFailure.AUTH_FAILED, self._phase)

        finish_hmac = hmac.new(key, remote_nonce, hashlib.sha256).digest()
        self._send_message(
            seqno=2,
            command=tinytuya.SESS_KEY_NEG_FINISH,
            payload=finish_hmac,
            key=key,
            deadline=deadline,
        )
        derivation_iv = local_nonce[:12]
        if derivation_iv in self._tx_ivs:
            raise ReadOnlyError(ReadOnlyFailure.AUTH_FAILED, self._phase)
        self._tx_ivs.add(derivation_iv)
        mixed_nonce = bytes(left ^ right for left, right in zip(local_nonce, remote_nonce, strict=True))
        session_blob = tinytuya.AESCipher(key).encrypt(
            mixed_nonce,
            use_base64=False,
            pad=False,
            iv=local_nonce[:12],
        )
        session_key = session_blob[12:28]
        if len(session_key) != 16:
            raise ReadOnlyError(ReadOnlyFailure.AUTH_FAILED, self._phase)

        self._phase = "status"
        # TinyTuya 1.20.0's merged v3.5 DP_QUERY_NEW payload is the empty
        # object; the command itself is the allowlisted read-only operation.
        query = b"{}"
        self._send_message(
            seqno=3,
            command=tinytuya.DP_QUERY_NEW,
            payload=query,
            key=session_key,
            deadline=deadline,
        )
        status = self._receive_message(key=session_key, deadline=deadline)
        if status.cmd != tinytuya.DP_QUERY_NEW or status.retcode != 0:
            raise ReadOnlyError(ReadOnlyFailure.INVALID_RESPONSE, self._phase)
        try:
            return _decode_dps(status.payload)
        except Exception:
            raise ReadOnlyError(ReadOnlyFailure.INVALID_RESPONSE, self._phase) from None

    def _preflight_key(self) -> bytes:
        tinytuya = _tinytuya()

        try:
            installed = importlib.metadata.version("tinytuya")
        except Exception:
            installed = ""
        if installed != "1.20.0":
            raise ReadOnlyError(ReadOnlyFailure.DEPENDENCY_UNSUPPORTED, self._phase)
        if (
            self._config.protocol_version != 3.5
            or self._candidate_device_id != self._config.device_id
            or self._announced_versions != ("3.5",)
        ):
            raise ReadOnlyError(ReadOnlyFailure.PROTOCOL_NOT_ELIGIBLE, self._phase)
        try:
            key = self._config.local_key.encode("latin-1")
        except (UnicodeEncodeError, AttributeError):
            raise ReadOnlyError(ReadOnlyFailure.PROTOCOL_NOT_ELIGIBLE, self._phase) from None
        if len(key) != 16:
            raise ReadOnlyError(ReadOnlyFailure.PROTOCOL_NOT_ELIGIBLE, self._phase)
        if not tinytuya.AESCipher.CRYPTOLIB_HAS_GCM:
            raise ReadOnlyError(ReadOnlyFailure.DEPENDENCY_UNSUPPORTED, self._phase)
        return key

    def _preflight_address(self) -> ipaddress.IPv4Address:
        try:
            address = ipaddress.IPv4Address(self._candidate_address)
        except (ipaddress.AddressValueError, TypeError):
            raise ReadOnlyError(ReadOnlyFailure.PROTOCOL_NOT_ELIGIBLE, self._phase) from None
        try:
            interfaces = tuple(self._interface_reader())
        except Exception:
            raise ReadOnlyError(ReadOnlyFailure.INTERFACE_UNAVAILABLE, self._phase) from None
        try:
            eligible = validate_candidate_address(address, interfaces)
        except Exception:
            raise ReadOnlyError(ReadOnlyFailure.INTERFACE_UNAVAILABLE, self._phase) from None
        if not eligible:
            raise ReadOnlyError(ReadOnlyFailure.PROTOCOL_NOT_ELIGIBLE, self._phase)
        return address

    def _send_message(
        self, *, seqno: int, command: int, payload: bytes, key: bytes, deadline: float
    ) -> None:
        tinytuya = _tinytuya()

        self._phase_deadline(deadline)
        iv = self._random_bytes(12, self._tx_ivs)
        message = tinytuya.TuyaMessage(
            seqno, command, None, payload, 0, True, tinytuya.PREFIX_6699_VALUE, iv
        )
        try:
            frame = tinytuya.pack_message(message, hmac_key=key)
        except Exception:
            raise ReadOnlyError(ReadOnlyFailure.DEPENDENCY_UNSUPPORTED, self._phase) from None
        try:
            header = tinytuya.parse_header(frame)
        except Exception:
            raise ReadOnlyError(ReadOnlyFailure.INVALID_RESPONSE, self._phase) from None
        if (
            len(payload) > MAX_FRAME_PAYLOAD
            or header.length > MAX_FRAME_PAYLOAD
            or len(frame) > MAX_FRAME_PAYLOAD + 64
        ):
            raise ReadOnlyError(ReadOnlyFailure.INVALID_RESPONSE, self._phase)
        self._account(len(frame), deadline, outgoing=True)
        try:
            self._set_timeout(deadline)
            self._socket.sendall(frame)
        except socket.timeout:
            raise ReadOnlyError(ReadOnlyFailure.TIMEOUT, self._phase) from None
        except OSError:
            raise ReadOnlyError(ReadOnlyFailure.TRANSPORT_FAILED, self._phase) from None

    def _receive_message(self, *, key: bytes, deadline: float):
        tinytuya = _tinytuya()

        self._phase_deadline(deadline)
        if self._frames >= MAX_FRAMES:
            raise ReadOnlyError(ReadOnlyFailure.INVALID_RESPONSE, self._phase)
        self._frames += 1
        header_bytes = self._recv_exact(_HEADER_6699_BYTES, deadline)
        if header_bytes[:4] != b"\x00\x00\x66\x99":
            raise ReadOnlyError(ReadOnlyFailure.INVALID_RESPONSE, self._phase)
        try:
            header = tinytuya.parse_header(header_bytes)
        except Exception:
            raise ReadOnlyError(ReadOnlyFailure.INVALID_RESPONSE, self._phase) from None
        if header.prefix != tinytuya.PREFIX_6699_VALUE or header.length > MAX_FRAME_PAYLOAD:
            raise ReadOnlyError(ReadOnlyFailure.INVALID_RESPONSE, self._phase)
        frame = header_bytes + self._recv_exact(header.total_length - len(header_bytes), deadline)
        if frame[-4:] != tinytuya.SUFFIX_6699_BIN:
            raise ReadOnlyError(ReadOnlyFailure.INVALID_RESPONSE, self._phase)
        try:
            message = tinytuya.unpack_message(
                frame,
                hmac_key=key,
                header=header,
                # 3.5 validation requires the explicit four-byte retcode.
                # The helper's False mode rejects frames with no retcode by
                # leaving that prefix in the payload for strict JSON parsing.
                no_retcode=False,
            )
        except Exception:
            raise ReadOnlyError(ReadOnlyFailure.INVALID_RESPONSE, self._phase) from None
        if message.prefix != tinytuya.PREFIX_6699_VALUE or not message.crc_good:
            raise ReadOnlyError(ReadOnlyFailure.AUTH_FAILED, self._phase)
        if message.iv in self._rx_ivs:
            raise ReadOnlyError(ReadOnlyFailure.AUTH_FAILED, self._phase)
        self._rx_ivs.add(message.iv)
        return message

    def _recv_exact(self, size: int, deadline: float) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            self._phase_deadline(deadline)
            self._set_timeout(deadline)
            try:
                part = self._socket.recv(size - len(chunks))
            except socket.timeout:
                raise ReadOnlyError(ReadOnlyFailure.TIMEOUT, self._phase) from None
            except OSError:
                raise ReadOnlyError(ReadOnlyFailure.TRANSPORT_FAILED, self._phase) from None
            if not part:
                raise ReadOnlyError(ReadOnlyFailure.TRANSPORT_FAILED, self._phase)
            self._account(len(part), deadline, outgoing=False)
            chunks.extend(part)
        return bytes(chunks)

    def _random_bytes(self, length: int, used: set[bytes]) -> bytes:
        try:
            value = self._entropy(length)
        except Exception:
            raise ReadOnlyError(ReadOnlyFailure.DEPENDENCY_UNSUPPORTED, self._phase) from None
        if not isinstance(value, bytes) or len(value) != length or value in used:
            raise ReadOnlyError(ReadOnlyFailure.AUTH_FAILED, self._phase)
        used.add(value)
        return value

    def _account(self, size: int, deadline: float, *, outgoing: bool) -> None:
        self._phase_deadline(deadline)
        if outgoing and self._frames >= MAX_FRAMES:
            raise ReadOnlyError(ReadOnlyFailure.INVALID_RESPONSE, self._phase)
        if outgoing:
            self._frames += 1
        self._bytes += size
        if self._bytes > MAX_BYTES:
            raise ReadOnlyError(ReadOnlyFailure.INVALID_RESPONSE, self._phase)

    def _set_timeout(self, deadline: float) -> None:
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise ReadOnlyError(ReadOnlyFailure.TIMEOUT, self._phase)
        self._socket.settimeout(remaining)

    def _phase_deadline(self, deadline: float) -> None:
        if self._closed:
            raise ReadOnlyError(ReadOnlyFailure.CLOSED, self._phase)
        if self._clock() >= deadline:
            raise ReadOnlyError(ReadOnlyFailure.TIMEOUT, self._phase)

    def _check_deadline(self, deadline: float) -> None:
        self._phase_deadline(deadline)
