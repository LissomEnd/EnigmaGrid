# Status — 2026-10-02

## Main local service
- LENOVO5 is running Enigma Volunteer Grid coordinator v0.2 on port 8765.
- Global campaign `p1030680-global-v1` is `prepared`, not activated.
- C3 remains a completely separate live system on port 8750.

## Implemented and tested
- Crash/power-loss lease recovery and exact-range requeue.
- Duplicate late results receive no double credit.
- Two independent contributors: first result pending, second matching result verifies both.
- Real `event_stochastic` Enigma work reproduced server-side with identical fingerprint.
- 2-of-3 majority logic tested; dissenting submission rejected and penalized.
- Invalid result rejected before consensus with zero credit.
- Trust/quarantine: severe invalid results 1 -> trust 0.65; 2 -> trust 0.30 + quarantined/disabled.
- CUDA capability routing tested: CUDA device with GPU 40% got GPU work; non-CUDA device got none.
- Surface worker v0.2.1 tested at CPU 30%: effective 2 logical threads of 8, GPU 0%.
- Personal dashboard settings update is reflected by heartbeat.
- Backup created and SQLite integrity check returned `ok`.
- Installer parses cleanly and retains user-level HKCU autostart/uninstall design.

## Deployment prepared
- Dockerfile + Docker Compose.
- Caddy reverse proxy with HTTPS/security headers.
- Coordinator container drops Linux capabilities, uses no-new-privileges and read-only root filesystem.
- Secrets live in ignored `.env` / production config, not Git.
- Backup/restore scripts and migration guide are present.

## Current limitations before public launch
- Docker is not installed on Lenovo, so the container stack is prepared but not executed locally.
- No VPS/domain has been provided yet; Lenovo therefore remains the central development server.
- GPU scheduling is implemented, but the production P1030680 manifest currently uses CPU engines only.
- Worker still depends on Python 3.13; standalone signed Windows packaging/tray UI remains to be built.
- PostgreSQL/failover is a future scale step, not required for the current local coordinator.

## Publication
No GitHub remote exists and nothing has been published.

## Final hygiene checks
- Main coordinator DB was cleaned after testing: only `p1030680-global-v1` remains and it is `prepared`; test identities/results were removed after backup.
- Clean volunteer source bundle: `dist/enigma-volunteer-dev.zip`, 1,230,263 bytes.
- Bundle SHA-256: `D9327541AFB8134500501E610320AD9452F989596C5282FA4C15CD55A6614DBD`.
- Bundle contains 14 files and zero `__pycache__`, `.pyc`, `.nbc` or `.nbi` artifacts.
