# F2E.D.3.A Confirmation and Atomic Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add internal token-only confirmation, serialized revalidation and atomic in-memory address adoption, followed by a revision-guarded normal readback in the same device FIFO turn.

**Architecture:** `RecoveryService` acquires the existing process slot, atomically claims only proposals owned by its instance, then submits a typed confirmation barrier. The scheduler's fixed handler delegates to `DeviceManager`, which validates under one device lease, closes the old adapter through `TuyaAdapter`, commits under a short lifecycle guard, releases the lease, and performs a normal readback guarded by the committed revision. Adoption and readback are separate result fields.

**Tech Stack:** Python 3.12+, `threading`, `concurrent.futures.Future`, pytest, existing `ProposalStore`, `CommandScheduler`, `DeviceManager`, `CandidateValidator`, and `TuyaAdapter`.

**Spec:** `docs/superpowers/specs/2026-10-19-f2e-d3a-confirmacao-adocao-design.md`

## Global Constraints

- Preserve D-018/D-019: Tuya 3.5 only; one process-wide active recovery slot; max four pending proposals; 60-second monotonic TTL; one prepare and one confirmation validation, no automatic retries.
- Confirmation accepts only an opaque proposal token; it never accepts an arbitrary address.
- Claim compares owner atomically before consuming and preserves original `expires_at`.
- Lock order at commit is Device ID → service lifecycle; never reacquire the same non-reentrant Device ID lock while held.
- No scheduler condition/mutex during manager calls or LAN I/O; no Future wait on the scheduler worker.
- Queue admission/recovery work never abandons active I/O or releases capacity before actual completion.
- After commit, `ADOPTED` remains final regardless of timeout, shutdown, or readback failure.
- Tests use fakes, Events/barriers, and monotonic fake clocks; no real LAN, cloud, hardware, or credentials.
- No JSONL/IPC/UI, TOML persistence, Tuya 3.3, automatic recovery, or DPS writes.
- Stop for code review before functional commit, push, or merge.

## File Map

- `backend/src/smart_home_tray/recovery_proposals.py`: owner-checked atomic claim result carrying original expiry.
- `backend/src/smart_home_tray/command_scheduler.py`: typed, discrete `CONFIRM_RECOVERY` FIFO request and fixed handler.
- `backend/src/smart_home_tray/tuya_adapter.py`: observable, sanitized, idempotent adapter close; failed cleanup poisons the adapter against reuse.
- `backend/src/smart_home_tray/device_manager.py`: leased revalidation, cleanup, lifecycle-guarded address-only commit, and separate expected-revision readback.
- `backend/src/smart_home_tray/recovery.py`: token-only `confirm_internal`, process-slot/lifecycle/deadline coordination, and adoption/readback result mapping.
- `backend/tests/test_recovery_proposals.py`: owner claim and expiry-preservation tests.
- `backend/tests/test_tuya_adapter.py`: close success/idempotency, cleanup failure sanitization, and poison/no-reuse tests.
- `backend/tests/test_recovery_confirm.py`: end-to-end fake scheduler/manager/service concurrency and state invariant regressions.
- `docs/architecture.md`, `docs/contracts.md`, `docs/PROJECT_STATUS.md`: verified contracts and checkpoint.

## Tasks

### Task 1 — Owner-checked, expiry-preserving claim

- [x] Add a failing store test: owner mismatch returns unavailable and leaves the proposal claimable by its owner.
- [x] Add a failing store test: successful claim returns the exact original owner and expiry, without changing TTL.
- [x] Run `rtk py -m pytest backend/tests/test_recovery_proposals.py -q`; verify expected RED failures.
- [x] Extend the internal claim API/result so owner comparison and consumption happen in one store mutex section. Keep owner out of repr and logs; preserve the stored `expires_at`.
- [x] Rerun the focused store tests and confirm GREEN.

### Task 2 — Observable fail-closed adapter cleanup

- [x] Add failing fake-device tests for close idempotency and for a socket close error being sanitized and preventing adapter reuse.
- [x] Run `rtk py -m pytest backend/tests/test_tuya_adapter.py -q`; verify expected RED failures.
- [x] Add `TuyaAdapter.close()` and an unusable/poisoned state. Encapsulate socket/resource inspection and closure inside this adapter only. On partial failure, propagate a typed sanitized `BackendError`, retain controlled ownership of the resource, and reject all later reads/writes on that instance.
- [x] Rerun adapter tests and existing adapter tests.

### Task 3 — Typed confirmation FIFO barrier

- [x] Add scheduler tests proving confirmation is discrete/non-coalescible, ordered after prior commands and before later commands, and uses the fixed DeviceManager method with no caller callback.
- [x] Run `rtk py -m pytest backend/tests/test_command_scheduler.py -q`; verify expected RED failures.
- [x] Add the typed `CONFIRM_RECOVERY` request and submit method. The handler passes only internal claim data, deadline, cancellation/lifecycle guard and expected revision context to DeviceManager. Preserve no-Future-wait-in-worker and no scheduler mutex during I/O.
- [x] Rerun scheduler tests.

### Task 4 — Transactional adoption and guarded normal readback

- [x] Add failing DeviceManager tests for successful revalidation/commit, auth failure, adapter cleanup failure, `update_address()` before lease, pending/configuration invariants, and readback revision supersession.
- [x] Run the focused new manager tests and verify expected RED failures.
- [x] Add one internal confirmation method that acquires one device lease, validates token binding/current config/expiry/deadline/cancellation, performs `CandidateValidator` validation, and calls `TuyaAdapter.close()` before commit.
- [x] At the commit point, under the device lock then lifecycle lock, repeat deadline, original TTL, revision/address/protocol, cancellation and lifecycle checks. Apply address with an unlocked transactional helper; increment revision once; invalidate old adapter/knowledge while preserving identity, key, capabilities, and pending intent.
- [x] Release the adoption lease, then reacquire through a normal manager readback helper that checks the captured committed revision inside the lock before any LAN I/O. Return `SUPERSEDED` without I/O if a later update won.
- [x] Rerun focused manager tests and existing manager/recovery tests.

### Task 5 — Internal confirmation coordinator and concurrency regressions

- [x] Add failing `confirm_internal(token)` tests for invalid token/no arbitrary address, owner mismatch, replay, global BUSY, lifecycle recheck after slot acquisition, expiry in FIFO and during validation, deadline drain, shutdown before/after commit, same-token race, command interleavings, independent-device progress, and separate readback failure.
- [x] Run the focused confirmation tests and verify expected RED failures.
- [x] Implement token-only coordination: check service lifecycle after acquiring process slot; claim owner atomically; enqueue typed barrier; drain started I/O; keep slot through readback; preserve `ADOPTED` after commit for all later outcomes.
- [x] Rerun confirmation plus focused recovery/scheduler/manager/adapter/proposal tests.

### Task 6 — Documentation and full verification

- [x] Update architecture/contracts/status to describe verified confirmation semantics, cleanup limitations, lock ordering, revision-guarded readback, and separate results.
- [x] Run focused suite for changed backend files.
- [x] Run full backend suite: `rtk py -m pytest backend/tests -q`.
- [x] Run `rtk py -m compileall -q backend/src backend/tests` and `rtk git diff --check`.
- [x] Inspect the final diff and worktree status; report test counts, limitations, and stop for code review without commit/push/merge.

## Execution

Execute inline in this worktree using test-first cycles. Do not create subagents. Keep each task independently verified; do not commit intermediate or final functional changes.
