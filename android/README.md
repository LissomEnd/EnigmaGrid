# EnigmaGrid for Android 0.4.5

Experimental volunteer client, Android 8+ (API 26). Install the signed APK from
GitHub Releases, register under Account, then choose Start contributing.

Separate CPU/GPU duty sliders, charging-only option, battery and thermal guards,
public and personal dashboards, encrypted credentials and durable pending
receipts are included. The GPU requires a successful device qualification under
Device before its slider is enabled. CPU must remain above zero for the solver.

Supported work engine: bounded_crib_v1. Existing campaigns are not replaced.
The native Vulkan row generator has passed 4,992 contact comparisons and 60
complete synthetic receipts on RedMagic NX789J / Adreno 830 / Android 15.
CPU and GPU network tests exercised a real isolated coordinator, lost responses,
process death and replay without duplicate credit, and independent Python parity.
These results do not prove a decryption, speed advantage or all-device support.
ARM64, ARMv7 and x86_64 native libraries are included; other devices remain untested.

## Background work

An ongoing foreground notification offers Pause, Resume and Stop. A bounded,
renewed partial wake lock keeps requested work running with the screen off.
Android may recreate the service after reclaiming its process; saved receipts
are replayed before new work. Allow unrestricted battery use and vendor auto-start
in Android app settings. Force-stop and reboot require opening the app and
starting again. Android and vendor firmware can still stop applications.

Account registration and statistics are available in-app; advanced account
management does not yet have full parity with the volunteer web interface.
No admin functionality is included.

## Build

Use JDK 17, Gradle 8.9, Android SDK 35, NDK 27.2.12479018 and CMake 3.22.1.
Run `gradle -p android :app:assembleDebug` for development.
Release signing uses ENIGMAGRID_ANDROID_KEYSTORE and
ENIGMAGRID_ANDROID_STORE_PASSWORD environment variables, alias `enigmagrid`.
Keep the signing key outside the repository. Run `:app:assembleRelease`.

The separate lab variant is for isolated loopback instrumentation only; it is
not included in release builds. Do not install it for normal contribution.

## Updates and controls

Device includes an automatic release check when the app opens, a manual retry,
and opt-in automatic APK download on Wi-Fi. Optional updates can be postponed;
the coordinator's minimum version prevents incompatible clients from taking new
work. If a required version has no downloadable Android APK, the app reports it
without deleting account data or pending results. APKs are checked for SHA-256,
size, application ID, increasing version code and matching signing certificate.
Installation uses Android's confirmation screen and per-app install permission.
Version 0.4.8 schedules background checks approximately every six hours, subject
to Android network/battery scheduling. Automatic Wi-Fi download is opt-in;
installation still requires Android confirmation.

Compute displays Start while idle, a single Pause/Resume action and Stop while
active, and automatically refreshed status. Device contains diagnostic tests.
Android declares supported_engines=[bounded_crib_v1]; coordinator eligibility
must honor that field so CPU capability does not imply portable_event_v1 support.

Account displays the contributor name fetched from the coordinator and hides
registration controls for enrolled devices. GPU availability is reported only
when the qualified Vulkan backend is enabled and has not failed; Compute shows
successful GPU dispatches. Dashboard GPU counts indicate eligible devices, not
instantaneous utilization. A failed backend falls back to CPU.

Update validation includes controlled transport tests for payload size, digest,
redirects, package identity, version code and signer rejection. These adapter
tests do not replace testing the Android system installer on each device.

## Work scheduling (0.4.6)

Acknowledged results request another job immediately, with a one-transaction-per-
second ceiling for tiny jobs. Empty assignments and transient network failures
retain a 30-second backoff. Search preparation uses available CPU processors
(up to 32) and reduces results in canonical core order, preserving receipt bytes
and candidate caps. CPU duty, pause, cancellation and resource guards apply to
all workers. Vulkan calls remain serialized; GPU batching remains
an optimization opportunity; 0.4.7 adds context reuse. A 100% setting permits activity but does not promise
full hardware utilization for every job.

Parallel qualification compares complete receipts with Python and sequential
Java, including candidate caps and 128-core domains. Other Android hardware
still requires on-device qualification.

Version 0.4.7 reuses bounded Vulkan buffers, device, pipeline and synchronization
objects across serialized dispatches. Errors invalidate the cache. GPU
qualification must be repeated after this backend change; CPU remains available.
RedMagic validation passed 4,992 contact comparisons, 60 full receipts and
network replay across process restart with independent Python verification.

## Verified update path and compatibility limits

On RedMagic NX789J / Android 15, the production 0.4.6 app discovered 0.4.7,
downloaded and verified its APK, and opened the Android package installer.
The owner confirmed installation. Version 0.4.7 retained account identity and
CPU/GPU preferences; GPU requalification passed and contribution resumed.
This validates that upgrade path on this device, not unattended installation.

| Target | Build coverage | Physical-device evidence |
| --- | --- | --- |
| ARM64 / Adreno 830 / Android 15 | Release compiled | CPU/GPU parity, network replay, upgrade and production receipts |
| ARMv7 | Native library compiled | Not yet tested on hardware |
| x86_64 | Native library compiled | Not yet tested on hardware |
| Other Vulkan GPUs (including Mali) | Optional backend with CPU fallback | Not yet tested on hardware |

Android 8/API 26 is the configured minimum, not a claim of hardware testing on
every supported API level. Mandatory-update policy and invalid-APK rejection
have controlled tests; a production mandatory-version change was not performed
for testing. Background checks were exercised through Android JobScheduler on RedMagic
(including a forced test invocation), not an elapsed six-hour reliability test.
Advanced volunteer account management is still pending.

## Throughput changes (0.4.8)

Search-local Vulkan batches pack up to 16 keys per dispatch and cache only the
current bounded search (at most 128 keys). RedMagic qualification compared
41,054 contacts and 60 complete receipts, plus a 128-key receipt matching CPU
with exactly eight Vulkan dispatches. This reduces IPC calls; it is not evidence
of full GPU utilization or an end-to-end throughput multiplier. The backend
qualification key changes, so a new device test is required before GPU use.

The worker reuses its transaction state, sends settings only after a change or
failed acknowledgement, and relies on lease responses for revocation and minimum
version checks. Long searches retain periodic heartbeats. Completed receipts
remain durable until acknowledged. Fractional compute seconds are sent as decimal
text accepted by the coordinator, keeping the integer/ASCII receipt format intact.
Android HTTPS/Keystore/GPU tests cover lost acknowledgements and process restart
without duplicate credit. The one-transaction-per-second ceiling remains.

Additional host checks: compile `core/BatchRowsChecks.java` with the core sources
and run `BatchRowsChecks`; run `core/qualify_network_cycle.py --jdk PATH`.
Batch checks cover cache invalidation, cancellation, CPU fallback, disabled GPU,
request order and dispatch telemetry. These changes are included starting with Android 0.4.8.

The update notification opens Device > App updates on both cold and warm app
launch. A cached APK is rechecked against release size/SHA-256, package/version
and installed signer before reuse. The periodic checker completed a real check
on RedMagic with state CURRENT; optional/required policy branches additionally
have controlled tests. These updater changes are included starting with Android 0.4.8.
