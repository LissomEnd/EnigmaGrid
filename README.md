# Enigma Volunteer Grid

Volunteer-computing platform for the unresolved P1030680 Naval Enigma M4 message.

Help investigate a historical ciphertext by donating spare computing time. This is an independent community project. No decryption has been established by this project.

The original exploratory campaign remains active. An additional experimental
crib campaign has been added, with an independently verified initial lot and
its continuation queued behind the original work. It has no demonstrated
recovery advantage. See [research qualification](RESEARCH.md) for limitations.

## For volunteers

[Watch the Windows setup and resource-control guide on YouTube](https://youtu.be/VfLBCZG5yc0)
(2 minutes 52 seconds, English narration and subtitles).
The tutorial covers installation, consent, CPU/GPU budgets, pause and safe stop,
verified work, and updates. Download the current installer from the releases below;
the interface and live statistics may change after the recording.

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

### Experimental Android client

See the [Android client guide](android/README.md) for APK installation, resource
controls, background-work limitations and optional update downloads. Android
[0.4.12 is published as an experimental APK](https://github.com/LissomEnd/EnigmaGrid/releases/tag/android-v0.4.12)
and has resumed contribution on RedMagic; one real production
receipt was independently reproduced. Its consolidated build includes bounded
compute/upload overlap, batched assignments and CPU row-generation improvements.
ARM64, ARMv7 and x86_64 libraries pass package/ELF alignment checks; this does not
prove execution on every device, GPU driver or Android version. Sliders set
activity budgets, not guaranteed hardware utilization. Use only APKs actually
published in official releases; local qualification is not publication.

### Hardware and resource controls
CPU contribution works without a compatible GPU. The GPU backend uses OpenCL and checks each detected GPU against the CPU scorer before enabling it. AMD integrated graphics and Intel Iris Plus have passed real-device parity tests; other GPUs, including NVIDIA OpenCL devices, require compatible drivers and the same startup check. Detection does not guarantee that every device or driver will work. The official Windows installer targets Windows x64. A separate experimental Android client is described below; other platforms are not release-tested.

The CPU slider sets a computation-thread budget. The GPU slider sets a work/rest budget. These are scheduling limits, not guarantees of a particular Task Manager utilization reading. GPU work still needs some CPU time for coordination. Set a resource to zero to stop assigning it new work; changed budgets apply at the next job. Pause suspends portable search at its next checkpoint, and safe stop finishes the current job before closing. Closing the window keeps the tray application running; use its stop control to end contribution.

Public leaderboard credit is optional and is off by default. Read the [privacy policy](PRIVACY.md) before joining. Computing uses electricity and may increase fan noise; choose limits appropriate for your device.

## Validation and credit
Need help or found a problem? [Open an issue](https://github.com/LissomEnd/EnigmaGrid/issues/new/choose)
or read the [troubleshooting guide](SUPPORT.md). Security vulnerabilities should
be reported privately using the repository's Security tab.

Work is issued as deterministic units with crash-safe leases. Unexpected shutdown or network loss does not damage the campaign; expired work is requeued.

Final credit requires matching separate computations. The default policy is 2-of-2 agreement: another contributor or a fresh server CPU reproduction can supply the second result. The server verifier uses spare capacity, yields to host/server load and never earns volunteer credit. This is computational reproduction, not independent human endorsement. Disagreement expands validation and can enter manual review. Invalid work receives no credit, repeated serious failures reduce trust, and devices can be quarantined.

The coordinator also reproduces accepted Enigma result/key/event structures before final acceptance. A high language score or software round-trip alone is never treated as proof of a historical decryption.

## Security
The coordinator sends structured work descriptions only for solver engines already shipped with the worker. It cannot send shell commands or arbitrary executable code.

Windows client credentials are encrypted with DPAPI. Server-side device, contributor and dashboard secrets are stored as hashes. Public metadata is sanitized and excludes hostname, Python details and GPU UUIDs.

Updates use an Ed25519-signed manifest, SHA-256/size verification, safe-boundary application, mandatory-version enforcement and automatic rollback after a failed health check.

Volunteers connect to the bundled public HTTPS endpoint. No private network access is required.

## Research and release status


This is a heuristic search, not an exhaustive proof over every Enigma key and transcription model. Progress percentages describe the scheduled search campaign, not the probability of solving the message. A completed campaign can still leave the message unresolved.

Release-specific validation and known limitations belong in the corresponding GitHub release notes. Development builds and a reachable dashboard alone do not establish that a public release is ready.

The Windows binaries are not Authenticode-signed. Windows SmartScreen may therefore show an Unknown Publisher warning. Check the source, release notes and published integrity information before deciding whether to install. Signed updates verify the project's release key; they do not certify that software is free of defects.

See `PRIVACY.md`, `SECURITY.md`, `CONTRIBUTING.md` and `RELEASE.md` before publishing or contributing.

Original project code is MIT licensed. Bundled third-party data and runtime
components retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).

### Windows multi-GPU development status

The development worker splits portable-event scoring batches across qualified
OpenCL devices concurrently, preserving key order and deterministic results.
CPU/GPU hybrid mode retains its current equal CPU/GPU split; GPU work is shared
across the qualified devices. This does not accelerate the separate CPU-only
bounded-crib engine. Resource limits and campaign priorities are unchanged.

`tests/test_scoring_pool.py` checks concurrent dispatch, ordering and error cleanup.
`tests/qualify_multi_gpu.py` is an opt-in hardware check of complete CPU, GPU and
hybrid worker results. Current physical validation covers one AMD GPU; concurrent
multiple-device execution has adapter coverage but awaits physical multi-GPU
validation and a Windows installer release. No utilization or speedup guarantee.

The [Windows 0.4.4 stabilization candidate](https://github.com/LissomEnd/EnigmaGrid/releases/tag/v0.4.4)
is published and installed on two participating Windows PCs. CI, frozen-worker
computation, installer lifecycle and artifact-attestation checks passed; new
production receipts have been independently verified. Extra bounded-search
processes are limited by available RAM, with a serial fallback. Background
process creation suppresses console windows. Sustained utilization remains under
observation; an active-job native update-dialog test is inconclusive, so this
candidate is not promoted to the automatic latest-release channel.
