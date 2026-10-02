# Enigma Volunteer Grid

Volunteer-computing platform for the unresolved P1030680 Naval Enigma M4 message.

Help investigate a historical ciphertext by donating spare computing time. The project is independent and is not affiliated with Veritasium. No decryption has been established by this project.

## For volunteers
Download `EnigmaGridSetup.exe` from [official releases](https://github.com/LissomEnd/EnigmaGrid/releases), run it, choose a display name and set your resource limits. The Windows x64 installer includes the runtime; Python, administrator rights and manual server configuration are not required. Only download a published release, not an unfinished development build.

The Windows app provides:
- guided first-run onboarding with a contributor display name and explicit resource-use consent;
- real CPU computation and optional OpenCL GPU computation, with separate resource controls;
- pause/resume, safe stop, Windows autostart and update checks;
- live global and personal verified-contribution statistics;
- automatic hardware capability detection;
- a tray menu and browser dashboard;
- clean uninstall with an optional purge of the local contributor identity.

The public HTTPS endpoint is bundled with the installer. Volunteers do not need Tailscale or access to the server's private network.

### Hardware and resource controls
CPU contribution works without a compatible GPU. The GPU backend uses OpenCL and checks each detected GPU against the CPU scorer before enabling it. AMD integrated graphics and Intel Iris Plus have passed real-device parity tests; other GPUs, including NVIDIA OpenCL devices, require compatible drivers and the same startup check. Detection does not guarantee that every device or driver will work. The official installer targets Windows x64; other operating systems and architectures are not yet release-tested.

The CPU slider sets a computation-thread budget. The GPU slider sets a work/rest budget. These are scheduling limits, not guarantees of a particular Task Manager utilization reading. GPU work still needs some CPU time for coordination. Set a resource to zero to stop assigning it new work; changed budgets apply at the next job. Pause suspends portable search at its next checkpoint, and safe stop finishes the current job before closing. Closing the window keeps the tray application running; use its stop control to end contribution.

Public leaderboard credit is optional and is off by default. Read the [privacy policy](PRIVACY.md) before joining. Computing uses electricity and may increase fan noise; choose limits appropriate for your device.

## Validation and credit
Work is issued as deterministic units with crash-safe leases. Unexpected shutdown or network loss does not damage the campaign; expired work is requeued.

Final credit requires independent reproduction. The default policy is 2-of-2 agreement; disagreement expands validation and can enter manual review. Invalid work receives no credit, repeated serious failures reduce trust, and devices can be quarantined.

The coordinator also reproduces accepted Enigma result/key/event structures before final acceptance. A high language score or software round-trip alone is never treated as proof of a historical decryption.

## Security
The coordinator sends structured work descriptions only for solver engines already shipped with the worker. It cannot send shell commands or arbitrary executable code.

Windows client credentials are encrypted with DPAPI. Server-side device, contributor and dashboard secrets are stored as hashes. Public metadata is sanitized and excludes hostname, Python details and GPU UUIDs.

Updates use an Ed25519-signed manifest, SHA-256/size verification, safe-boundary application, mandatory-version enforcement and automatic rollback after a failed health check.

The Lenovo coordinator binds only to `127.0.0.1:8765`. Public access is designed exclusively through Tailscale Funnel HTTPS, so no router port-forward or home public IP is exposed.

## Research and release status
This is a heuristic search, not an exhaustive proof over every Enigma key and transcription model. Progress percentages describe the scheduled search campaign, not the probability of solving the message. A completed campaign can still leave the message unresolved.

Release-specific validation and known limitations belong in the corresponding GitHub release notes. Development builds and a reachable dashboard alone do not establish that a public release is ready.

The Windows binaries are not Authenticode-signed. Windows SmartScreen may therefore show an Unknown Publisher warning. Check the source, release notes and published integrity information before deciding whether to install. Signed updates verify the project's release key; they do not certify that software is free of defects.

See `PRIVACY.md`, `SECURITY.md`, `CONTRIBUTING.md` and `RELEASE.md` before publishing or contributing.

Original project code is MIT licensed. Bundled third-party data and runtime
components retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).
