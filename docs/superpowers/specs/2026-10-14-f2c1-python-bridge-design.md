# F2C.1 design — secure Tauri/Python bridge

## Approved scope
Implement F2C.1 on feature/tauri-python-bridge: keep browser and default native mode MOCK; add explicit Rust-selected FIXTURE and guarded REAL modes; preserve DeviceController and JSON Lines contract; never use real hardware in automated tests. CR-20 tray placement and flexible COB strip remain backlog only.

## Boundary
React calls narrow typed Tauri commands through TauriDeviceController; it cannot provide executable, args, config path, environment or arbitrary JSONL commands. Rust owns process supervision, fixed command construction, framing/size validation, correlation, timeout and shutdown. Frontend maps backend public DTO into normalized UI state; nullable fields remain unknown.

## Modes
- Browser: MockDeviceController, unchanged.
- Native default: MOCK.
- FIXTURE: explicit Rust process environment selection starts a fixed Python fixture module; fixture never imports TinyTuya or uses network.
- REAL: requires explicit REAL mode, separate opt-in and config path from the Rust process environment; fixed `python -m smart_home_tray.cli --config <path> serve`. This stage does not run physical tests. Failure never falls back to mock.

## Typed operations
Expose only existing commands: `devices.list`, `device.get/status`, `device.power`, `device.whiteBrightness`, `device.colorTemperature`, `device.hsv`, `device.colorBrightness`. Full HSV composition uses normalized status plus latest pending intentions; mode changes map to capability-supported operations and fail safely when state is insufficient. No `device.setMode` or second scheduler.

## Process behavior
One managed child per app, private pipes. Dedicated bounded reader parses exact envelopes up to 65,536 bytes, dispatches by requestId and supports out-of-order requests. Stderr is drained separately without echoing content. Timeout, EOF, malformed/oversized protocol and child exit fail pending operations safely. Child stops only at actual app exit, never panel hide.

## Risks
REAL configuration passes secrets only through documented Local Key environment references; never log env/payload/exception values. Python runtime packaging remains external. Rust supervisor, fixture invocation and state-quality mapping are review areas. Equipment validation is outside this phase.