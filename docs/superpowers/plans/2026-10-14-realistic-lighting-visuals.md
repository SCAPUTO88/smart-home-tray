# F2A.1 Realistic Lighting Visual Polish Implementation Plan

> **For agentic workers:** execute task by task with test-first changes and local commits.

**Goal:** Give the existing bulb and LED strip convincing material depth and responsive emitted light while preserving the current dark UI, behavior, and performance.

**Architecture:** Keep rendering in DeviceArtwork and its CSS. Add small pure presentation helpers for normalized HSV and white-temperature colors; derive every visual from the provided preview state. Keep device/session/controller and IPC layers unchanged.

**Tech Stack:** React 19, TypeScript, inline SVG, CSS gradients/transitions, Vitest, Testing Library, Motion.

**Spec:** Approved F2A.1 request and visual proposal in the conversation.

## Global Constraints

- Keep DeviceController, MockDeviceController, useLightingSession, field reconciliation, backend, scheduler, and JSON Lines contracts unchanged.
- Use only normalized preview state; no LAN, cloud, or physical devices.
- Keep the dark identity and approximately 420 × 720 layout; avoid horizontal overflow at 360 px.
- Keep Tuya white-temperature direction labeled as unvalidated on hardware.
- Do not push, merge, or start F2B/F2C.

## Review Focus

- Power-off must remove every emitted-light layer while retaining the physical object.
- Low HSV Value must reduce core, halo, ambient spill, and LED emission without changing selected hue.
- White mode must visibly interpolate warm, neutral, and cool color at fixed brightness.
- Device artwork must derive color and intensity only from its own state and avoid cross-device SVG IDs.
- Reduced motion must suppress nonessential transitions/animations, including Motion entry behavior.

---

### Task 1: Presentation color and intensity behavior

**Files:** Create desktop/src/lib/lightingVisuals.ts and desktop/src/lib/lightingVisuals.test.ts; create desktop/src/components/lighting/DeviceArtwork.test.tsx.

**Interfaces:** Consume DeviceState and existing hsvToRgb/rgbCss. Produce selectedLightingColor(state): string and lightingIntensity(state): number.

- [x] Write tests for HSV cyan/purple, warm-neutral-cool white, RGB/white brightness, and power-off intensity.
- [x] Run focused tests and observe expected failures.
- [x] Implement helpers and artwork assertions for CSS variables, power off, and independent device renders.
- [x] Run focused tests and verify they pass.

### Task 2: Physical bulb SVG and layered light

**Files:** Modify desktop/src/components/lighting/DeviceArtwork.tsx and desktop/src/app/LightingApp.css; test DeviceArtwork.test.tsx.

**Interfaces:** Consume Task 1 helpers and normalized artwork props. Produce unique SVG definition IDs, layered glass/surface/specular/base elements, and emitted-light layers driven by CSS variables.

- [x] Add component tests for glass, internal light, and powered-off rendering.
- [x] Run focused tests and observe expected failures.
- [x] Implement glass/transmission, inner light, side highlight, static specular reflection, and metal base with SVG gradients/masks.
- [x] Add core, halo, and ambient layers; animate opacity/color only, not blur filters.
- [x] Run focused tests and verify they pass.

### Task 3: Physical LED strip and responsive layout

**Files:** Modify DeviceArtwork.tsx and LightingApp.css; adjust desktop/src/app/App.test.tsx only if an integration assertion is needed.

**Interfaces:** Consume Task 1 color/intensity and selected device state. Produce dimensional strip body, translucent diffuser, subtle emitters, continuous selected-color spill.

- [x] Add tests for selected-color-only emission, low intensity, power off, and per-device isolation.
- [x] Run focused tests and observe expected failures.
- [x] Implement restrained extrusion, diffuser reflections, and LEDs beneath the diffuser without fixed rainbow emission.
- [x] Refine narrow-width rules without changing control hierarchy.
- [x] Run focused tests and verify they pass.

### Task 4: Motion, accessibility, and documentation

**Files:** Modify LightingApp.css and DeviceArtwork.tsx only if needed; update docs/PROJECT_STATUS.md, docs/architecture.md, and docs/DECISIONS.md.

**Interfaces:** Consume finished artwork and existing MotionConfig reduced-motion preference. Produce reduced-motion compliant transitions, documented rendering trade-offs and visual validation limits.

- [x] Add/adjust focused accessibility and reduced-motion assertions using observable UI behavior.
- [x] Run focused tests and observe expected failures.
- [x] Implement motion preference handling and document static filters, CSS-driven intensity, white-temperature hardware caveat, and visual inspection status.
- [x] Run npm run typecheck, npm run lint, npm test, npm run build, and git diff --check from desktop as applicable.
- [ ] Inspect requested states and responsive widths in an available browser; if unavailable, document the limitation without claiming visual validation.
- [x] Commit completed, verified changes locally; do not push or merge.
