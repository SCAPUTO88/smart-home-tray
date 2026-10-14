# F2B CR-18/CR-19 plan

- Add Rust RED tests for taskbar edge placement, negative monitor coordinates, DPI-scaled preferred size (100/125/150%), bounds, and restoring 420x720 logical size after moving to a larger monitor.
- Implement one Tauri positioning flow using the physical tray event rect, selected monitor work area/scale, and 10px edge gap; test all four taskbar orientations and fallback.
- Add frontend RED tests for Tauri startDragging, browser no-op, and interactive header controls; grant only core:window:allow-start-dragging.
- Update docs, run frontend/Rust/Tauri verification, diff review, and create local commits. No push, merge, backend, LAN, devices, or F2C.

## Execution outcome

- `npm run typecheck`, `npm run lint`, `npm test` (53 passed), `npm run build`, `cargo fmt --all -- --check`, `cargo check --locked`, `cargo test --locked` (12 passed), `npm run tauri:build -- --no-bundle`, and `git diff --check` passed.
- Tauri emitted the existing non-blocking PDB filename collision warning for the bin/lib targets.
- Native dragging and tray layout/DPI checks remain manual Windows validation items.
- CR-16's stated preferred-size restoration behavior is integrated. No separate CR-17 acceptance text was present in this prompt or the accessible PR #17 record, so no unprovided behavior is claimed.
