# F2C.1 implementation plan

## Task 1 — DTO and frontend boundary (TDD)
- Add public DTO types and mapper tests for capabilities, nulls, unknown/offline.
- Extend safe operation error codes and test mapping.
- Implement TauriDeviceController tests for full HSV composition, consecutive partial channels, mode selection, errors and capability guards.

## Task 2 — Python fixture process (TDD)
- Add deterministic JSONL module with existing envelopes/public statuses; no TinyTuya/config/network imports.
- Add Python tests for fixture commands, null/quality states and framing.

## Task 3 — Rust process bridge (TDD)
- Add Rust process mode config, MOCK default; REAL requires separate opt-in and config path.
- Add typed requests, exact JSONL serialization and 64 KiB limit.
- Implement child pipes, bounded framing, request correlation, concurrency, sanitized errors/timeouts/EOF/exit, stderr drain and shutdown.
- Add Rust fixture integration tests for startup, concurrency, timeout, malformed/oversize, child exit and cleanup.
- Add only narrow Tauri invoke commands.

## Task 4 — runtime UI wiring
- Resolve mode once at bootstrap; browser stays mock and native MOCK stays mock.
- Surface startup failure without unhandled promises/spinner/fallback; display mode; scenario only in mock.
- Add fixture UI integration tests and preserve session behavior.

## Task 5 — CI, docs, verification
- Add fixture integration coverage to Windows CI; keep backend Python matrix.
- Update status, architecture, decisions and desktop README; record CR-20 and flexible COB strip as backlog only.
- Run requested frontend, Rust/Tauri, backend checks and diff check.
- Commit locally; no push, merge, device or LAN tests.