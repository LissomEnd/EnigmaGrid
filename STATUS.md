# Status — 2026-10-02

## Current services
- Lenovo runs Enigma Volunteer Grid coordinator v0.3 on `127.0.0.1:8765` only.
- Global campaign `p1030680-global-v1` is `prepared`, not activated.
- C3 is a separate live campaign/service on port 8750 and is not modified by Grid development.
- No GitHub remote exists and nothing has been published.

## Distributed grid verified
- Crash/power-loss lease recovery and exact-range requeue.
- Duplicate late submissions do not receive duplicate credit.
- 2-of-2 independent consensus; mismatch expands to 2-of-3; unresolved disagreement enters review.
- Real `event_stochastic` result reproduction and independent verification.
- Invalid submissions receive zero credit; repeated serious failures reduce trust and quarantine devices.
- Capability routing for CPU/CUDA and per-device CPU/GPU percentages.
- DPAPI client credential storage on Windows; server token hashes only.
- Public metadata sanitization removes hostname, Python details and GPU UUID.
- Loopback-only coordinator bind guard.

## Standalone Windows release candidate
- `EnigmaGrid.exe`: tray/control UI.
- `EnigmaGridWorker.exe`: headless compute worker.
- `EnigmaGridUpdater.exe`: signed update/apply/rollback helper.
- `EnigmaGridSetup.exe`: single-file per-user installer; no Python or administrator rights required.
- Setup installs under `%LOCALAPPDATA%`, registers HKCU autostart and Windows uninstall metadata.
- Installer verifies embedded payload SHA-256 before copying any runtime executable.
- Installer lifecycle test covers install, binary hash equality, registry/autostart, purge-data uninstall and removal of the install directory: PASS.
- The old PowerShell volunteer installer/uninstaller has been removed from the public source path.

## Signed updates
- Ed25519 release private key is outside Git and stored as an ACL-restricted DPAPI blob on Lenovo.
- Frozen signed update success path: PASS.
- Forced broken-version rollback (`9.9.9`): PASS, previous runtime restored automatically.
- Mandatory-update refusal stops safely and is not restarted by the tray.
- Update application happens only between leases.

## Current binary hashes
- Update ZIP: 111,965,838 bytes; SHA-256 `94AF531A56BE3BF7138F8533A43C9836D0125A940C7F3DDCEF96BCB6EA0883DC`.
- Setup EXE: 122,329,812 bytes; SHA-256 `8C89D4965497F5EC72E3EA8A61854E13C25E7796A1CBEB4EB02D8AF8ADA1910E`.

## Remaining before public launch
- Configure and verify Tailscale Funnel/HTTPS. The Lenovo public IP must never be used as the volunteer endpoint.
- Add release bootstrap so Setup/tray receives the Funnel URL automatically; volunteers should not type a server address.
- Run final secret/IP scan and security regression from a clean checkout.
- Finalize public privacy/contributor terms and repository-facing documentation.
- Create GitHub repository only after the items above pass.

## Known minor issue
During uninstall, a temporary copy of `EnigmaGridUpdater.exe` can remain briefly in `%TEMP%` because the PyInstaller bootloader may keep its own executable locked. It contains no credentials/user data and is removed by the next Setup run or normal temporary-file cleanup. Installed runtime, autostart, uninstall registry entry and optional local data are removed correctly.
