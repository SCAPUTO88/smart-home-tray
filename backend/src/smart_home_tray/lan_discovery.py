"""Bounded TinyTuya UDP discovery; results are unverified announcements only."""

from __future__ import annotations

import ipaddress
import itertools
import json
import logging
import math
import select
import socket
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

from .discovery import DiscoveryAnnouncement

_LOG = logging.getLogger(__name__)
_PORTS = (6666, 6667, 7000)
_GLOBAL_SCAN_LOCK = threading.Lock()
_SUPPORTED_VERSIONS = {"3.1", "3.2", "3.3", "3.4", "3.5"}
_MAX_BROADCAST_INTERFACES = 16
_MAX_INTERFACE_RECORDS = 64
_MAX_RECEIVE_FAILURES_PER_LISTENER = 3


def _version_text(value: object) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (str, int, float)):
        result = str(value).strip()
        return result or None
    return None


def decode_announcement(packet: bytes, source: tuple[str, int]) -> DiscoveryAnnouncement | None:
    """Decode a synthetic or live UDP announcement into allowlisted fields."""
    try:
        source_ip = str(ipaddress.IPv4Address(source[0]))
        if not isinstance(packet, bytes) or not packet:
            return None
        import tinytuya

        decoded = json.loads(tinytuya.decrypt_udp(packet))
        if not isinstance(decoded, dict):
            return None
        device_id = decoded.get("gwId", decoded.get("id"))
        version = _version_text(decoded.get("version"))
        if not isinstance(device_id, str) or not device_id.strip():
            return None
        if version not in _SUPPORTED_VERSIONS:
            return None
        return DiscoveryAnnouncement(device_id, source_ip, version)
    except Exception:
        # Parser exceptions can include packet data; deliberately discard them.
        return None


class TinyTuyaLanDiscoveryProvider:
    """Collect Tuya UDP announcements with hard packet, duration and concurrency caps."""

    def __init__(
        self,
        *,
        socket_factory: Callable[..., Any] = socket.socket,
        interface_provider: Callable[[], Sequence[tuple[str, str, str]]] | None = None,
        wait_readable: Callable[[Sequence[Any], float], tuple[Sequence[Any], Any, Any]] = select.select,
        monotonic: Callable[[], float] = time.monotonic,
        max_packets: int = 256,
        max_candidates: int = 64,
        max_broadcast_interfaces: int = _MAX_BROADCAST_INTERFACES,
        max_duration_seconds: float = 3.0,
    ) -> None:
        if (
            max_packets < 1
            or max_candidates < 1
            or not 1 <= max_broadcast_interfaces <= _MAX_BROADCAST_INTERFACES
            or not math.isfinite(max_duration_seconds)
            or max_duration_seconds <= 0
        ):
            raise ValueError("invalid discovery limits")
        self._socket_factory = socket_factory
        self._interface_provider = interface_provider or self._default_interfaces
        self._wait_readable = wait_readable
        self._monotonic = monotonic
        self._max_packets = max_packets
        self._max_candidates = max_candidates
        self._max_broadcast_interfaces = max_broadcast_interfaces
        self._max_duration_seconds = max_duration_seconds

    @staticmethod
    def _default_interfaces() -> tuple[tuple[str, str, str], ...]:
        """Enumerate local IPv4 broadcasts from the required psutil runtime dependency."""
        import psutil

        interfaces: list[tuple[str, str, str]] = []
        interface_stats = psutil.net_if_stats()
        for interface_name, addresses in psutil.net_if_addrs().items():
            stats = interface_stats.get(interface_name)
            if stats is None or not stats.isup:
                continue
            for address in addresses:
                if (
                    address.family == socket.AF_INET
                    and address.address
                    and address.broadcast
                    and address.netmask
                    and address.address != address.broadcast
                ):
                    # Keep duplicate broadcast addresses: separate adapters may
                    # use them while requiring different source addresses.
                    interfaces.append((address.broadcast, address.address, address.netmask))
        return tuple(interfaces)

    @staticmethod
    def _discovery_packet(source_ip: str) -> bytes:
        import tinytuya

        payload = json.dumps({"from": "app", "ip": source_ip}, separators=(",", ":")).encode()
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

    def _open_listeners(self, deadline: float, opened: list[Any]) -> list[Any]:
        listeners = []
        for port in _PORTS:
            if self._monotonic() >= deadline:
                break
            sock = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            opened.append(sock)
            if self._monotonic() >= deadline:
                break
            try:
                sock.bind(("", port))
                sock.settimeout(0.0)
                listeners.append(sock)
            except OSError:
                _LOG.debug("LAN discovery could not bind a listener")
        if not listeners:
            raise OSError("LAN discovery listeners unavailable")
        return listeners

    def _send_v35_requests(
        self,
        interfaces: Sequence[tuple[str, str, str]],
        deadline: float,
        opened: list[Any],
    ) -> tuple[bool, bool]:
        try:
            import tinytuya

            if not tinytuya.AESCipher.CRYPTOLIB_HAS_GCM:
                return False, False
        except Exception:
            return False, False
        attempted = 0
        failed = False
        truncated = len(interfaces) > _MAX_INTERFACE_RECORDS
        for broadcast, source, netmask in itertools.islice(interfaces, _MAX_INTERFACE_RECORDS):
            if self._monotonic() >= deadline:
                return failed, truncated
            try:
                source_address = ipaddress.IPv4Address(source)
                broadcast_address = ipaddress.IPv4Address(broadcast)
                network = ipaddress.IPv4Network(f"{source_address}/{netmask}", strict=False)
            except (ValueError, TypeError):
                continue
            if (
                source_address.is_unspecified
                or source_address.is_loopback
                or source_address.is_multicast
                or source_address == ipaddress.IPv4Address("255.255.255.255")
                or broadcast_address.is_unspecified
                or broadcast_address.is_loopback
                or broadcast_address.is_multicast
                or broadcast_address == ipaddress.IPv4Address("255.255.255.255")
                or source_address == broadcast_address
                or broadcast_address != network.broadcast_address
            ):
                continue
            if attempted >= self._max_broadcast_interfaces:
                truncated = True
                break
            source_ip = str(source_address)
            broadcast_ip = str(broadcast_address)
            attempted += 1
            try:
                sock = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                opened.append(sock)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.bind((source_ip, 0))
                if self._monotonic() >= deadline:
                    return failed, truncated
                sock.sendto(self._discovery_packet(source_ip), (broadcast_ip, 7000))
            except Exception:
                # A failed adapter is tolerated when listeners or other adapters work.
                _LOG.debug("LAN discovery broadcast unavailable on one adapter")
                failed = True
        return failed, truncated

    def discover(self, expected_device_id: str, *, timeout_seconds: float) -> list[DiscoveryAnnouncement]:
        if not isinstance(expected_device_id, str) or not expected_device_id.strip():
            raise ValueError("invalid discovery request")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("invalid discovery timeout")
        if not _GLOBAL_SCAN_LOCK.acquire(blocking=False):
            raise RuntimeError("LAN discovery already active")

        opened: list[Any] = []
        started_at = self._monotonic()
        deadline = started_at + min(float(timeout_seconds), self._max_duration_seconds)
        announcements: list[DiscoveryAnnouncement] = []
        candidate_addresses: set[str] = set()
        processed = 0
        waited_for_packets = False
        receive_failures: dict[Any, int] = {}
        retired_listener = False
        broadcast_failed = False
        interfaces_truncated = False
        try:
            listeners = self._open_listeners(deadline, opened)
            interfaces: Sequence[tuple[str, str, str]] = ()
            if self._monotonic() < deadline:
                try:
                    discovered_interfaces = self._interface_provider()
                    if isinstance(discovered_interfaces, Sequence) and not isinstance(
                        discovered_interfaces, (str, bytes)
                    ):
                        interfaces = discovered_interfaces
                except Exception:
                    _LOG.debug("LAN interface enumeration unavailable")
                    raise OSError("LAN interface enumeration failed") from None
            if interfaces and self._monotonic() < deadline:
                broadcast_failed, interfaces_truncated = self._send_v35_requests(
                    interfaces, deadline, opened
                )
            while self._monotonic() < deadline and listeners:
                if processed >= self._max_packets or len(candidate_addresses) >= self._max_candidates:
                    raise RuntimeError("LAN discovery collection limit reached")
                remaining = deadline - self._monotonic()
                waited_for_packets = True
                try:
                    ready, _, _ = self._wait_readable(listeners, min(remaining, 0.1))
                except OSError:
                    raise OSError("LAN discovery listener wait failed") from None
                if not ready:
                    continue
                for sock in ready:
                    if sock not in listeners:
                        continue
                    if (
                        processed >= self._max_packets
                        or len(candidate_addresses) >= self._max_candidates
                    ):
                        raise RuntimeError("LAN discovery collection limit reached")
                    try:
                        packet, source = sock.recvfrom(4096)
                    except (BlockingIOError, socket.timeout):
                        receive_failures[sock] = receive_failures.get(sock, 0) + 1
                    except OSError:
                        receive_failures[sock] = receive_failures.get(sock, 0) + 1
                    else:
                        receive_failures[sock] = 0
                        processed += 1
                        announcement = decode_announcement(packet, source)
                        if announcement is not None and announcement.device_id == expected_device_id:
                            candidate_addresses.add(announcement.address)
                            announcements.append(announcement)
                        continue
                    if receive_failures[sock] >= _MAX_RECEIVE_FAILURES_PER_LISTENER:
                        listeners.remove(sock)
                        retired_listener = True
                        _LOG.debug("LAN discovery listener retired after repeated receive failures")
                if not listeners:
                    raise OSError("LAN discovery listeners failed")
            if not waited_for_packets and self._monotonic() >= deadline:
                raise TimeoutError("LAN discovery budget expired before listening")
            if retired_listener:
                raise OSError("LAN discovery listener receive failed")
            if broadcast_failed:
                raise OSError("LAN discovery broadcast failed")
            if interfaces_truncated:
                raise RuntimeError("LAN discovery interface limit reached")
            if processed >= self._max_packets or len(candidate_addresses) >= self._max_candidates:
                raise RuntimeError("LAN discovery collection limit reached")
            return announcements
        finally:
            for sock in reversed(opened):
                try:
                    sock.close()
                except Exception:
                    _LOG.debug("LAN discovery socket cleanup failed")
            _GLOBAL_SCAN_LOCK.release()
