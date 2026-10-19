from __future__ import annotations

import ipaddress
import threading

from smart_home_tray.recovery_proposals import (
    ProposalBinding,
    ProposalStore,
    ProposalStoreStatus,
)


class Clock:
    def __init__(self):
        self.value = 10.0

    def __call__(self):
        return self.value


def binding(device_id: str, revision: int = 0) -> ProposalBinding:
    return ProposalBinding(device_id, ipaddress.IPv4Address("192.0.2.20"), 3.5, revision, "192.0.2.10")


def test_proposal_store_uses_opaque_32_byte_tokens_and_digest_index():
    clock = Clock()
    store = ProposalStore(clock=clock, token_bytes=lambda size: bytes(range(size)))

    created = store.create_validated(binding("lamp-a"))

    assert created.status is ProposalStoreStatus.CREATED
    descriptor = created.descriptor
    assert descriptor is not None
    assert len(descriptor.token) > 32
    assert "token" not in repr(descriptor)
    assert store._by_digest
    assert descriptor.token.encode() not in repr(store._by_digest).encode()
    assert store.lookup(descriptor.token).binding == binding("lamp-a")


def test_proposal_store_enforces_capacity_and_one_per_device():
    clock = Clock()
    next_byte = iter(range(1, 10))
    store = ProposalStore(clock=clock, token_bytes=lambda size: bytes([next(next_byte)]) * size)
    descriptors = [store.create_validated(binding(f"lamp-{index}")).descriptor for index in range(4)]

    assert all(descriptors)
    assert store.create_validated(binding("lamp-0", revision=1)).status is ProposalStoreStatus.DEVICE_PENDING
    assert store.create_validated(binding("lamp-e")).status is ProposalStoreStatus.CAPACITY
    assert store.pending_count == 4


def test_proposal_ttl_is_monotonic_and_claim_is_single_use():
    clock = Clock()
    store = ProposalStore(clock=clock, token_bytes=lambda size: b"x" * size)
    descriptor = store.create_validated(binding("lamp-a")).descriptor
    assert descriptor is not None

    clock.value += 59.999
    assert store.lookup(descriptor.token).status is ProposalStoreStatus.AVAILABLE
    claimed = store.claim(descriptor.token)
    assert claimed.status is ProposalStoreStatus.CLAIMED
    assert claimed.binding == binding("lamp-a")
    assert store.claim(descriptor.token).status is ProposalStoreStatus.NOT_FOUND


def test_expired_proposal_is_removed_and_device_can_prepare_again():
    clock = Clock()
    entropy = iter((b"a" * 32, b"b" * 32))
    store = ProposalStore(clock=clock, token_bytes=lambda _size: next(entropy))
    first = store.create_validated(binding("lamp-a")).descriptor
    assert first is not None
    clock.value += 60

    assert store.lookup(first.token).status is ProposalStoreStatus.EXPIRED
    second = store.create_validated(binding("lamp-a", revision=1))
    assert second.status is ProposalStoreStatus.CREATED


def test_revision_invalidation_handles_a_to_b_to_a_and_shutdown_clears_tokens():
    clock = Clock()
    entropy = iter((b"c" * 32, b"e" * 32))
    store = ProposalStore(clock=clock, token_bytes=lambda _size: next(entropy))
    first = store.create_validated(binding("lamp-a", revision=0)).descriptor
    assert first is not None
    store.invalidate_older("lamp-a", 2)
    assert store.lookup(first.token).status is ProposalStoreStatus.NOT_FOUND

    current = store.create_validated(binding("lamp-a", revision=2)).descriptor
    assert current is not None
    store.invalidate_all()
    assert store.lookup(current.token).status is ProposalStoreStatus.NOT_FOUND


def test_token_collision_fails_closed_without_overwriting_existing_proposal():
    clock = Clock()
    store = ProposalStore(clock=clock, token_bytes=lambda size: b"z" * size)
    first = store.create_validated(binding("lamp-a"))
    second = store.create_validated(binding("lamp-b"))

    assert first.status is ProposalStoreStatus.CREATED
    assert second.status is ProposalStoreStatus.TOKEN_COLLISION
    assert second.descriptor is None
    assert store.pending_count == 1
    assert store.lookup(first.descriptor.token).status is ProposalStoreStatus.AVAILABLE


def test_claimed_token_cannot_be_reissued_during_its_original_ttl():
    clock = Clock()
    store = ProposalStore(clock=clock, token_bytes=lambda size: b"r" * size)
    first = store.create_validated(binding("lamp-a")).descriptor
    assert first is not None
    assert store.claim(first.token).status is ProposalStoreStatus.CLAIMED

    second = store.create_validated(binding("lamp-b"))

    assert second.status is ProposalStoreStatus.TOKEN_COLLISION
    assert store.pending_count == 0


def test_deadline_expiring_during_token_generation_prevents_publication():
    clock = Clock()

    def entropy(size):
        clock.value += 6
        return b"d" * size

    store = ProposalStore(clock=clock, token_bytes=entropy)
    result = store.create_validated(binding("lamp-a"), deadline=clock() + 5)

    assert result.status is ProposalStoreStatus.DEADLINE_EXPIRED
    assert result.descriptor is None
    assert store.pending_count == 0


def test_concurrent_claim_consumes_token_exactly_once():
    store = ProposalStore(clock=Clock(), token_bytes=lambda size: b"q" * size)
    descriptor = store.create_validated(binding("lamp-a")).descriptor
    assert descriptor is not None
    barrier = threading.Barrier(3)
    results = []

    def claim():
        barrier.wait()
        results.append(store.claim(descriptor.token).status)

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=1)

    assert results.count(ProposalStoreStatus.CLAIMED) == 1
    assert results.count(ProposalStoreStatus.NOT_FOUND) == 1
