# F2E.B Discovery Core Implementation Plan

> **For agentic workers:** Execute inline in this session using TDD. Steps use checkbox syntax; no commits are part of this task.

**Goal:** Add an internal, deterministic LAN candidate discovery core that never validates identity or changes a device address.

**Architecture:** `discovery.py` defines immutable untrusted announcements, normalized candidate records, typed outcomes, and an injected provider protocol. A pure processor filters exact IDs and unusable IPv4 values, collapses identical announcements, preserves version conflicts, and reports multi-IP ambiguity; a wrapper normalizes provider errors. The deterministic fake stays in tests. No component depends on TinyTuya, sockets, DeviceManager, or TuyaAdapter.

**Tech Stack:** Python 3.12+, dataclasses, StrEnum, typing.Protocol, ipaddress, pytest.

**Spec:** User request “Smart Home Tray — F2E.B: Núcleo de descoberta LAN” (2026-10-15); `docs/F2E_A_DISCOVERY_INVESTIGATION.md`.

## Global Constraints

- Do not run or implement `find_device()`, `deviceScan()`, `scanner.devices()` or any socket-opening discovery path.
- Do not change DeviceManager, TuyaAdapter, config, CLI, JSONL, Rust/Tauri, frontend or lighting behavior.
- Do not read private files, Local Keys, devices.json or snapshot.json; do not access LAN, devices, cloud or REAL mode.
- Candidate means untrusted announcement; no `verified`/`recovered` result and no address mutation.
- Use reserved documentation IPv4 addresses and synthetic identifiers in tests.
- Do not commit or push.

## Review Focus

- Wrong Device ID and unusable IPv4: filtered or failed without exposing an address.
- Same ID at multiple IPs and conflicting version announcements: preserve evidence and never select by input order.
- Malformed candidates and provider exceptions: return generic typed failure without exception text or partial candidate selection.
- Version announcement versus configured version: announcement remains informational and never proves endpoint identity.
- Isolation: provider fake must not open sockets or receive manager/adapter references.

---

### Task 1: Typed discovery boundary and pure candidate processing

**Files:**
- Create: `backend/src/smart_home_tray/discovery.py`
- Test: `backend/tests/test_discovery.py`

**Interfaces:**
- Produces immutable `DiscoveryAnnouncement(device_id, address, announced_version)`, `DiscoveryCandidate(device_id, IPv4Address, announced_versions)`, `DiscoveryResult(status, candidates, failure)`, `DiscoveryProvider.discover(device_id, timeout_seconds)`, and `discover_candidates(provider, device_id, timeout_seconds)`.
- Outcome states: `NOT_FOUND`, `CANDIDATES`, `AMBIGUOUS`, `FAILED`. Failure codes: `INVALID_REQUEST`, `INVALID_ANNOUNCEMENT`, `TIMEOUT`, `PROVIDER_ERROR`.
- Only IPv4 parsing and rejection of unspecified, loopback, multicast and limited broadcast are fixed here. Do not infer LAN membership from `is_private`/`is_global` or introduce a subnet policy.

- [x] Add RED tests for empty/mismatched announcements, exact ID, invalid/special IPv4, and malformed data.
- [x] Run focused tests and confirm failure due to missing module/contracts.
- [x] Implement immutable types and pure deterministic normalization; fail the entire batch if a matching-ID announcement is malformed, dedupe exact records, aggregate distinct version strings for one IP, and sort candidates deterministically by numeric IPv4.
- [x] Run focused tests and confirm pass.

### Task 2: Injected provider orchestration and failure sanitization

**Files:**
- Modify: `backend/src/smart_home_tray/discovery.py`
- Test: `backend/tests/test_discovery.py`

**Interfaces:**
- `discover_candidates` calls the injected provider exactly once, with an explicit finite positive timeout and expected Device ID.
- The fake provider lives only in tests. Provider timeout and all other exceptions become typed generic failure results with no exception cause/text exposed.

- [x] Add RED tests for provider timeout, generic exception, deterministic output under reversed announcement order, duplicate/conflicting versions, multiple IP ambiguity, advertised version remaining informational, and socket/update isolation.
- [x] Run focused tests and confirm failure at the missing behavior.
- [x] Implement the minimal provider wrapper and safe result invariants; do not add a production TinyTuya provider or logs.
- [x] Run focused tests and confirm pass.

### Task 3: Document F2E.A review, F2E.B checkpoint, and F2E.C boundary

**Files:**
- Modify: `docs/F2E_A_DISCOVERY_INVESTIGATION.md`
- Modify: `docs/PROJECT_STATUS.md`
- Do not modify: `docs/DECISIONS.md` (no newly approved decision)

**Interfaces:**
- State that candidate collection is independent of identity validation and address acceptance.
- Record the unapproved protocol trust proposal and that failures, ambiguity, or insufficient identity never auto-update an address.
- F2E.C entry conditions: reviewed TinyTuya access path avoiding private default files, finite limits/cancellation and candidate preservation; reviewed identity/adoption policy by protocol; no implicit approval in this PR.

- [x] Add/adjust documentation after behavior and tests are known; distinguish investigated, implemented and tested facts.
- [x] Run backend focused tests, full suite, compileall, `git diff --check`, and scope/secret inspection.
- [x] Confirm no commit or push and summarize remaining F2E.C decisions.
