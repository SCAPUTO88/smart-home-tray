# Project instructions

These rules complement the global instructions and memory protocol supplied by the workspace. Do not copy or replace those global rules here.

## Smart Home Tray handoff

- Update `docs/PROJECT_STATUS.md` when a functional delivery or review checkpoint is completed.
- Record approved architectural decisions and superseded decisions in `docs/DECISIONS.md` with their rationale and trade-offs.
- Keep documentation synchronized with verified code and test results.
- Never record credentials, Local Keys, tokens, or other secrets in source, tests, documentation, logs, IPC, or memory.
- Do not mark a phase complete until its acceptance criteria have been checked with evidence.
- Signal material architectural changes for review before implementing them.
- At each checkpoint, provide a short summary that can be shared with ChatGPT for architectural review.

## Device safety

- Automated tests must use mocks and must not contact or modify physical devices.
- Any test that can change a physical device must require an explicit opt-in and stay outside the default test suite.
- Runtime device control must use the local network; do not add a cloud dependency.
