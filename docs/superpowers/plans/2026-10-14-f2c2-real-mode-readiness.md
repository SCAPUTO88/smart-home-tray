# F2C.2 Real Mode Readiness - Implementation Plan

> Execute inline with TDD. Automated tests use mocks, fixture, or artificial subprocesses only.

**Goal:** Add per-field knowledge, granular controls, explicit device refresh, and observable backend startup while preserving MOCK/FIXTURE isolation.

**Architecture:** Python stores field knowledge in each immutable state snapshot and adds it to public status. TypeScript maps metadata directly, gates each operation by its prerequisites, and refreshes one device with per-device concurrency guards. Rust validates REAL opt-in/configuration and probes devices.list before reporting the subprocess ready.

**Tech Stack:** Python, Rust/Tauri 2, React, TypeScript, Vitest, pytest, JSON Lines.

**Spec:** User-provided F2C.2 request and approved additive field-knowledge contract (2026-10-14).

## Global Constraints

- MOCK is default; MOCK/FIXTURE never access LAN or hardware.
- REAL requires SMART_HOME_TRAY_BACKEND_MODE=real, SMART_HOME_TRAY_ALLOW_REAL=1, and an absolute SMART_HOME_TRAY_CONFIG path.
- Add only public status knowledge metadata; preserve JSON Lines envelopes, commands, limits, errors, and scheduler semantics.
- Do not add polling, retries, automatic process restart, cloud dependencies, or hardware tests.
- Preserve global quality semantics; field observation does not confirm a pending write.
- Preserve CR-20 and flexible COB strip refinement as backlog.

## Review Focus

- Missing/invalid DPS after a prior valid read becomes stale without losing its value.
- Read failure stales prior fields and cannot falsely recover offline or enable unsafe commands.
- Refresh racing with a command or newer refresh never overwrites newer results.
- A subprocess that starts but cannot load/import/configure the backend is not reported ready and exposes no diagnostics.
- Unknown/partial state never renders as zero/default or disables unrelated known controls.

### Task 1: Backend snapshot knowledge and additive DTO

Files: backend models, DeviceManager, fixture; model, manager, and fixture tests.

Produces typed knowledge values observed/stale/unknown for power, workMode, whiteBrightness, colorTemperature, hsv, colorValue, and scene, stored with immutable LightState snapshots.

- [ ] Add failing tests for initial unknown; partial observed to stale; unknown to observed; invalid DPS; read failure/offline staling; pending write quality independence; DTO and fixture metadata.
- [ ] Run focused backend tests and verify failures.
- [ ] Implement immutable snapshot updates and allowlisted additive serialization.
- [ ] Run focused tests and verify transitions.
- [ ] Commit feat: publish per-field device knowledge.

### Task 2: Frontend knowledge and safe operation composition

Files: frontend device types, public mapper, TauriDeviceController, MockDeviceController and tests.

Produces typed DeviceState knowledge directly from public metadata. Operations require online connection plus field-specific observed data or complete safely composed pending HSV.

- [ ] Add failing tests for power known/HSV unknown, power unknown/HSV known, independent white fields, unknown mode, partial state, offline/unknown connection, and HSV safety.
- [ ] Run focused tests and verify failures.
- [ ] Implement typed mapping, per-field operation bases, and mock metadata.
- [ ] Run focused frontend tests.
- [ ] Commit fix: gate lighting commands by field knowledge.

### Task 3: Refresh and granular UI

Files: DeviceController implementations, session, platform bridge, LightingApp/controls and tests.

Interface: refresh(deviceId) returns the refreshed device; a superseded response raises COMMAND_CANCELED and is discarded by the session. Session keeps per-device loading/error state and merges only that device.

- [ ] Add failing tests for MOCK/FIXTURE isolation, offline to online, failed/null refresh, concurrent refresh, refresh/write race, selection changes, and unmount safety.
- [ ] Add app tests for granular gating, accessible refresh status, and known/unknown/offline/pending presentation.
- [ ] Run focused tests and verify failures.
- [ ] Implement sequence guards and refresh action; block refresh while that device already has a pending write.
- [ ] Run focused session/controller/app tests.
- [ ] Commit feat: add safe manual device refresh.

### Task 4: REAL preflight and subprocess readiness

Files: Rust bridge and tests; Python config/CLI tests only if needed.

- [ ] Add failing tests for default/invalid modes, missing config file, unavailable Python, import/config failure, startup timeout/EOF, and premature child exit.
- [ ] Run focused tests and verify failures.
- [ ] Implement regular absolute file preflight, devices.list startup probe with the existing request timeout, and shutdown after failed startup.
- [ ] Run Rust tests including fixture integration.
- [ ] Commit fix: report bridge readiness only after safe probe.

### Task 5: Documentation and complete verification

Files: contracts, architecture, decisions, project status, desktop README.

- [ ] Document DTO semantics, refresh concurrency, safe startup, and fixture checklist. Correct F2C.1 as approved/validated/merged to develop and main; retain backlog.
- [ ] Run frontend typecheck/lint/test/build; Rust fmt/check/test/Tauri no-bundle; backend pytest/compileall; git diff --check.
- [ ] Review outputs, confirm no physical/LAN tests, and commit documentation/verification updates.


## Execution record

Implementation and automated validation completed in the isolated worktree. Final evidence: frontend typecheck/lint/build and 82 Vitest tests; backend 182 pytest tests and compileall; Rust fmt/check and 24 tests; Windows Tauri build without bundle; git diff --check. The bridge readiness test uses fake child processes for a valid catalog, malformed catalog, and early EOF. Existing backend configuration tests cover invalid TOML and missing Local Key handling. Hardware/LAN/REAL paths were not executed. Manual refresh was verified with controller/session fakes; maintainers should perform the fixture UI checklist before enabling REAL.
