# Enigma Volunteer Grid

Volunteer-computing platform for the unresolved P1030680 Naval Enigma M4 message.

Help investigate a historical ciphertext by donating spare computing time. This is an independent community project. No decryption has been established by this project.

The original exploratory campaign remains active. An additional experimental
crib campaign has been added, with an independently verified initial lot and
its continuation queued behind the original work. It has no demonstrated
recovery advantage. See [research qualification](RESEARCH.md) for limitations.

## Source and coordinator compatibility

This repository includes a reference coordinator with the baseline
`/api/lease` and `/api/complete` protocol. The deployed service can advertise
additional capabilities independently of this public client source. Clients
use `/api/capabilities` when available, fall back to individual leases and
completions when optional batch endpoints are unavailable, and use long work
blocks only when their protocol format is advertised. Private performance
diagnostics are sent only when `device_telemetry_v1` is advertised. A source
checkout, a deployed coordinator and an installed release can therefore have
different capabilities; check each separately. The client never grants itself
credit or treats a submitted receipt as independently verified.

Optional wire fields include `batch_completions`, `long_work_blocks`,
`work_result_groups` and `device_telemetry`. Clients use a feature only when
the coordinator advertises its supported format. A long-block reservation
includes `valid_for_seconds`; if its remaining lifetime is unknown, the client
checks authoritative block status before continuing. Absence of an extension
is a compatibility fallback, not permission to assume unlimited work or
verified credit.

Compatible long primary blocks target a thirty-minute reserve, with early
refill near ten minutes and a fresh fill estimate after a measured speed
increase. Available work, reservation limits and validation fragmentation can
make the reserve shorter; legacy portable work uses separate leases. When compatible primary work is exhausted, a
contributor cannot validate its own results to keep a device busy: the client
waits for eligible independent work. Waiting does not mean a computed result
has been lost, and adding another device to the same contributor does not make
its results independent.

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
- global and personal contribution statistics, separating independent verification and sampling-accepted credit where the service reports both;
- a Monitor with CPU/GPU measurement sources, available temperatures and separate work-rate charts;
- automatic hardware capability detection;
- a tray menu and browser dashboard;
- clean uninstall with an optional purge of the local contributor identity.

The public HTTPS endpoint is bundled with the installer. Volunteers do not need Tailscale or access to the server's private network.

### Experimental Android client

See the [Android client guide](android/README.md) for APK installation, resource
controls, background-work limitations and optional update downloads. Use the
official `org.enigmagrid.android` app from
[published Android releases](https://github.com/LissomEnd/EnigmaGrid/releases).
A separate Lab app is not required. The current official Android client runs
`bounded_crib_v1` work; it does not run the Windows portable-event engine.
Installed version, release availability and
GPU qualification are separate facts; a package supporting a GPU backend does
not mean that every driver has passed its correctness check. See each release's
hardware results and limitations before upgrading.

### Hardware and resource controls
CPU contribution works without a compatible GPU. On Windows, the OpenCL GPU backend checks each detected GPU against the CPU scorer before enabling it. AMD integrated graphics and Intel Iris Plus have passed real-device parity tests; other GPUs, including NVIDIA OpenCL devices, require compatible drivers and the same startup check. Detection does not guarantee that every device or driver will work. The official Windows installer targets Windows x64. Android uses the official app described above; other platforms are not release-tested.

The CPU slider sets a computation-thread budget. The GPU slider sets a work/rest budget. These are scheduling limits, not guarantees of a particular Task Manager utilization reading. GPU work still needs some CPU time for coordination. Set a resource to zero to stop assigning it new work; changed budgets apply at the next job. Pause suspends portable search at its next checkpoint, and safe stop finishes the current job before closing. Closing the window keeps the tray application running; use its stop control to end contribution.

Public leaderboard credit is optional and is off by default. Read the [privacy policy](PRIVACY.md) before joining. Computing uses electricity and may increase fan noise; choose limits appropriate for your device.

## Validation and credit
Need help or found a problem? [Open an issue](https://github.com/LissomEnd/EnigmaGrid/issues/new/choose)
or read the [troubleshooting guide](SUPPORT.md). Security vulnerabilities should
be reported privately using the repository's Security tab.

Work is issued as deterministic units with crash-safe leases. Unexpected shutdown or network loss does not damage the campaign; expired work is requeued.

The reference coordinator requires matching separate computations: another
contributor or a fresh server CPU reproduction can supply the second result.
The deployed service may also report sampling-accepted credit for qualified
devices, separately from independently verified work. Its credited leaderboard
can include both; receiving a submission alone is not independent verification.
The server verifier uses
spare capacity, yields to host/server load and never earns volunteer credit.
This is computational reproduction, not independent human endorsement.
Disagreement expands validation and can enter manual review. Invalid work
receives no credit, repeated serious failures reduce trust, and devices can be
quarantined.

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
CPU and GPU claim separate deterministic cohorts instead of receiving a fixed
equal split. GPU work is shared across qualified devices. The bounded-crib
engine has a separate Vulkan qualification: portable OpenCL support alone does
not qualify that backend. Resource limits and campaign priorities remain
authoritative. Performance must be compared on the same work scope using
completed units per wall-clock second, not merely a larger job count.

For portable work at full resource budgets, the development worker can compare
GPU batch sizes automatically on the current device and exact workload. It
keeps the default unless complete receipts match and repeated whole-job timings
improve. This bounded local check runs once per workload/device profile in a
session, respects pause, stop, memory and thermal controls, and submits no test
results to the campaign. Its profile is invalidated by hardware, driver or code
changes; it does not promise a gain on every GPU.

`tests/test_scoring_pool.py` checks concurrent dispatch, ordering and error cleanup.
`tests/qualify_multi_gpu.py` is an opt-in hardware check of complete CPU, GPU and
hybrid worker results. Current physical validation covers one AMD GPU; concurrent
multiple-device execution has adapter coverage but awaits physical multi-GPU
validation. No utilization or speedup guarantee.

The earlier [Windows 0.4.4 stabilization release](https://github.com/LissomEnd/EnigmaGrid/releases/tag/v0.4.4)
is historical. Its tests and receipts do not qualify the 0.5.0 source candidate
or any package built from it; each release needs checks on its exact bytes.
