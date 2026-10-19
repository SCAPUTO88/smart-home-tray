"""Process-local, single-use store for validated recovery proposals."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable

MAX_PENDING_PROPOSALS = 4
PROPOSAL_TTL_SECONDS = 60.0
TOKEN_ENTROPY_BYTES = 32


class ProposalStoreStatus(StrEnum):
    CREATED = "created"
    AVAILABLE = "available"
    ADMISSION_ALLOWED = "admission_allowed"
    CLAIMED = "claimed"
    EXPIRED = "expired"
    NOT_FOUND = "not_found"
    DEVICE_PENDING = "device_pending"
    CAPACITY = "capacity"
    TOKEN_COLLISION = "token_collision"
    DEADLINE_EXPIRED = "deadline_expired"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ProposalBinding:
    """Allowlisted configuration facts; never contains private device config."""

    device_id: str
    candidate_address: ipaddress.IPv4Address
    protocol_version: float
    revision: int
    original_address: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.device_id, str)
            or not self.device_id.strip()
            or not isinstance(self.candidate_address, ipaddress.IPv4Address)
            or self.protocol_version != 3.5
            or isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
            or not isinstance(self.original_address, str)
        ):
            raise ValueError("invalid proposal binding")


@dataclass(frozen=True)
class ProposalDescriptor:
    token: str = field(repr=False)
    device_id: str
    candidate_address: ipaddress.IPv4Address
    expires_at: float


@dataclass(frozen=True)
class ProposalStoreResult:
    status: ProposalStoreStatus
    descriptor: ProposalDescriptor | None = None
    binding: ProposalBinding | None = None


@dataclass(frozen=True)
class _StoredProposal:
    binding: ProposalBinding
    created_at: float
    expires_at: float
    owner: object | None = field(repr=False, compare=False)


class ProposalStore:
    """Bounded in-memory store indexed only by a digest of each opaque token."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        token_bytes: Callable[[int], bytes] = secrets.token_bytes,
    ) -> None:
        if not callable(clock) or not callable(token_bytes):
            raise TypeError("store dependencies must be callable")
        self._clock = clock
        self._token_bytes = token_bytes
        self._lock = threading.Lock()
        self._by_digest: dict[bytes, _StoredProposal] = {}
        self._digest_by_device: dict[str, bytes] = {}
        self._retired_digests: dict[bytes, float] = {}

    @property
    def pending_count(self) -> int:
        with self._lock:
            self._purge_expired(self._clock())
            return len(self._by_digest)

    def create_validated(
        self,
        binding: ProposalBinding,
        *,
        cancellation: threading.Event | None = None,
        deadline: float | None = None,
        owner: object | None = None,
    ) -> ProposalStoreResult:
        """Publish an already validated binding after a final cancellation check."""
        if not isinstance(binding, ProposalBinding):
            return ProposalStoreResult(ProposalStoreStatus.NOT_FOUND)
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            if cancellation is not None and cancellation.is_set():
                return ProposalStoreResult(ProposalStoreStatus.CANCELLED)
            if deadline is not None and now >= deadline:
                return ProposalStoreResult(ProposalStoreStatus.DEADLINE_EXPIRED)
            if binding.device_id in self._digest_by_device:
                return ProposalStoreResult(ProposalStoreStatus.DEVICE_PENDING)
            if len(self._by_digest) >= MAX_PENDING_PROPOSALS:
                return ProposalStoreResult(ProposalStoreStatus.CAPACITY)
            try:
                raw_token = self._token_bytes(TOKEN_ENTROPY_BYTES)
            except Exception:
                return ProposalStoreResult(ProposalStoreStatus.TOKEN_COLLISION)
            if not isinstance(raw_token, bytes) or len(raw_token) != TOKEN_ENTROPY_BYTES:
                return ProposalStoreResult(ProposalStoreStatus.TOKEN_COLLISION)
            token = base64.urlsafe_b64encode(raw_token).rstrip(b"=").decode("ascii")
            digest = hashlib.sha256(raw_token).digest()
            if digest in self._by_digest or digest in self._retired_digests:
                return ProposalStoreResult(ProposalStoreStatus.TOKEN_COLLISION)
            now = self._clock()
            if cancellation is not None and cancellation.is_set():
                return ProposalStoreResult(ProposalStoreStatus.CANCELLED)
            if deadline is not None and now >= deadline:
                return ProposalStoreResult(ProposalStoreStatus.DEADLINE_EXPIRED)
            expires_at = now + PROPOSAL_TTL_SECONDS
            self._by_digest[digest] = _StoredProposal(binding, now, expires_at, owner)
            self._digest_by_device[binding.device_id] = digest
            descriptor = ProposalDescriptor(
                token, binding.device_id, binding.candidate_address, expires_at
            )
            return ProposalStoreResult(ProposalStoreStatus.CREATED, descriptor=descriptor)

    def lookup(self, token: str) -> ProposalStoreResult:
        return self._get(token, consume=False)

    def admission(self, device_id: str) -> ProposalStoreStatus:
        """Check capacity before discovery; publication rechecks under this lock."""
        with self._lock:
            self._purge_expired(self._clock())
            if device_id in self._digest_by_device:
                return ProposalStoreStatus.DEVICE_PENDING
            if len(self._by_digest) >= MAX_PENDING_PROPOSALS:
                return ProposalStoreStatus.CAPACITY
            return ProposalStoreStatus.ADMISSION_ALLOWED

    def claim(self, token: str) -> ProposalStoreResult:
        """Atomically consume a live token; later claims cannot replay it."""
        return self._get(token, consume=True)

    def retract(self, token: str) -> bool:
        """Remove only the exact still-pending token named by a late result."""
        raw_token = _decode_token(token)
        if raw_token is None:
            return False
        digest = hashlib.sha256(raw_token).digest()
        with self._lock:
            self._purge_expired(self._clock())
            stored = self._by_digest.get(digest)
            if stored is None:
                return False
            self._remove(digest, stored)
            self._retired_digests[digest] = stored.expires_at
            return True

    def _get(self, token: str, *, consume: bool) -> ProposalStoreResult:
        raw_token = _decode_token(token)
        if raw_token is None:
            return ProposalStoreResult(ProposalStoreStatus.NOT_FOUND)
        digest = hashlib.sha256(raw_token).digest()
        with self._lock:
            expired = self._purge_expired(self._clock())
            if digest in expired:
                return ProposalStoreResult(ProposalStoreStatus.EXPIRED)
            stored = self._by_digest.get(digest)
            if stored is None:
                return ProposalStoreResult(ProposalStoreStatus.NOT_FOUND)
            if consume:
                del self._by_digest[digest]
                self._digest_by_device.pop(stored.binding.device_id, None)
                self._retired_digests[digest] = stored.expires_at
                status = ProposalStoreStatus.CLAIMED
            else:
                status = ProposalStoreStatus.AVAILABLE
            return ProposalStoreResult(status, binding=stored.binding)

    def invalidate_older(self, device_id: str, revision: int) -> None:
        """Remove proposals made against an earlier monotonic configuration revision."""
        with self._lock:
            self._purge_expired(self._clock())
            digest = self._digest_by_device.get(device_id)
            stored = self._by_digest.get(digest) if digest is not None else None
            if stored is not None and stored.binding.revision < revision:
                self._remove(digest, stored)
                self._retired_digests[digest] = stored.expires_at

    def invalidate_owner(self, owner: object) -> None:
        """Invalidate only proposals published by one service instance."""
        with self._lock:
            self._purge_expired(self._clock())
            owned = tuple(
                (digest, stored)
                for digest, stored in self._by_digest.items()
                if stored.owner is owner
            )
            for digest, stored in owned:
                self._remove(digest, stored)
                self._retired_digests[digest] = stored.expires_at

    def _purge_expired(self, now: float) -> set[bytes]:
        expired = {
            digest for digest, item in self._by_digest.items()
            if now >= item.expires_at
        }
        for digest in expired:
            stored = self._by_digest.get(digest)
            if stored is not None:
                self._remove(digest, stored)
        for digest, expires_at in tuple(self._retired_digests.items()):
            if now >= expires_at:
                self._retired_digests.pop(digest, None)
        return expired

    def _remove(self, digest: bytes, stored: _StoredProposal) -> None:
        self._by_digest.pop(digest, None)
        if self._digest_by_device.get(stored.binding.device_id) == digest:
            self._digest_by_device.pop(stored.binding.device_id, None)


def _decode_token(token: str) -> bytes | None:
    if not isinstance(token, str) or len(token) != 43:
        return None
    try:
        encoded = token.encode("ascii")
        raw = base64.urlsafe_b64decode(encoded + b"=")
    except (UnicodeEncodeError, ValueError):
        return None
    if len(raw) != TOKEN_ENTROPY_BYTES:
        return None
    if base64.urlsafe_b64encode(raw).rstrip(b"=") != encoded:
        return None
    return raw


_PROCESS_PROPOSAL_STORE = ProposalStore()


def process_proposal_store() -> ProposalStore:
    """Return the one process-wide proposal table shared by service instances."""
    return _PROCESS_PROPOSAL_STORE
