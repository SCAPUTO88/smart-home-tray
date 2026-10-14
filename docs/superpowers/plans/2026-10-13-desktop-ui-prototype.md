# F2A Desktop UI Prototype Implementation Plan

> **For agentic workers:** Execute inline with superpowers:executing-plans. Steps are checkboxes and each behavior follows TDD.

**Goal:** Deliver an animated, accessible Smart Home Tray prototype that runs in a browser and uses deterministic simulated lighting devices only.

**Architecture:** Vite React UI is independent of Tauri native APIs. Components consume normalized public types and a `DeviceController`; a per-device store separates immediate preview and user intent from mock-confirmed state and protects newer values from stale responses.

**Tech Stack:** React, TypeScript, Vite, Tauri 2, Tailwind v4 Vite plugin, Motion React, Lucide React, Vitest, Testing Library, npm.

**Spec:** `docs/superpowers/specs/2026-10-13-desktop-ui-prototype-design.md` and the user-provided F2A requirements.

## Global Constraints

- All frontend operations use mocks; no devices, backend, sockets, LAN, cloud, credentials, or native Tauri APIs.
- Public device IDs and all sample state are synthetic; do not copy private backend configuration or DPS structures.
- Support approximately 420 × 720 px and widths near 360 px, with no horizontal overflow and vertical scrolling as needed.
- Respect keyboard access, visible focus, readable status, and `prefers-reduced-motion`.
- Do not add tray management, complex window lifecycle, sidecar, or real IPC.
- Do not declare Phase 2 complete or claim physical validation.

## Review Focus

- Older async result after a newer slider intention must not replace its preview.
- A canceled operation must settle pending feedback without claiming confirmation.
- Offline and error states must be communicated by text/icon in addition to color.
- Device switch must retain each independent state and capabilities must hide unsupported controls.
- RGB intensity must apply HSV Value before conversion to a true RGB color.

---

### Task 1: Frontend and Tauri foundation

**Files:** Create `desktop/package.json`, lockfile, Vite/TypeScript/ESLint/Vitest configs, `desktop/src-tauri/tauri.conf.json`, Rust crate scaffold, HTML and global CSS entry.

**Interfaces:** Produces npm scripts `dev`, `build`, `typecheck`, `lint`, `test`, `tauri`; Vite root/dist paths usable by the Tauri 2 config.

- [ ] Create Vite React TypeScript app in `desktop/`, install official current stable dependencies, and initialize Tauri 2 config.
- [ ] Add Tailwind via `@tailwindcss/vite`, test tooling, and scripts without native API use in the browser.
- [ ] Add responsive dark shell smoke test; verify RED before shell implementation.
- [ ] Run `npm ci`, typecheck, lint, test, build; commit `build: scaffold desktop prototype`.

### Task 2: Normalized types and mock controller

**Files:** `desktop/src/features/devices/types.ts`, `desktop/src/lib/color.ts`, `desktop/src/mock/MockDeviceController.ts`, associated tests.

**Interfaces:** `DeviceController.list(): Promise<Device[]>`, `DeviceController.command(deviceId, patch, scenario?): Promise<Device>`; `LightingPatch` covers `enabled`, `mode`, `hsv`, `whiteBrightness`, `whiteTemperature`.

- [ ] Test two synthetic device catalog entries, capability split, HSV-to-RGB, asynchronous confirmation, cancellation, offline/error and stale completion handling.
- [ ] Run tests and observe expected failures before implementation.
- [ ] Implement normalized public models and deterministic mocks with independent state and operation sequence protection.
- [ ] Run controller tests and commit `feat: add normalized mock lighting controller`.

### Task 3: Accessible lighting controls and illustrations

**Files:** `desktop/src/components/controls/*`, `desktop/src/components/lighting/*`, tests.

**Interfaces:** Reusable labeled range control; `PowerButton`; `DeviceArtwork` for bulb and segmented LED strip; controls receive values, labels and callbacks.

- [ ] Test keyboard range interaction, power state, HSV preview/intensity, bulb white/RGB mode, and capability-specific controls.
- [ ] Verify RED, then implement accessible controls and SVG/CSS artwork with Motion transitions and reduced-motion behavior.
- [ ] Run focused tests and commit `feat: build animated lighting controls`.

### Task 4: Main experience and operation feedback

**Files:** `desktop/src/app/*`, `desktop/src/components/layout/*`, integration tests and visual styles.

- [ ] Test device switching/state preservation, pending/confirmed/canceled/offline/error labels, and out-of-order response behavior.
- [ ] Verify RED; implement compact responsive device selector, hero artwork, mode-aware controls, operation scenario controls, and color-linked ambient lighting.
- [ ] Run interaction tests, launch Vite and inspect initial, RGB, white, LED, off, and error states at desktop/mobile widths; capture screenshots when browser tooling supports it.
- [ ] Run all frontend checks and commit `feat: assemble smart home lighting prototype`.

### Task 5: CI, docs and delivery checkpoint

**Files:** `.github/workflows/desktop-tests.yml`, `desktop/README.md`, `docs/PROJECT_STATUS.md`, `docs/architecture.md`, `docs/DECISIONS.md`.

- [ ] Add independent Node LTS workflow for PRs targeting `develop`/`main`: npm ci, typecheck, lint, tests, Vite build.
- [ ] Document Windows usage, mock scenarios, contract mapping, native/Rust/JSON Lines work deferred, and lack of physical validation.
- [ ] Run npm ci and every validation command, existing backend tests (mocks only), `git diff --check`; record environment limitation if Rust/Cargo unavailable.
- [ ] Commit `docs: record F2A prototype checkpoint`.
