# EnigmaGrid for Android

Experimental volunteer client, Android 8+ (API 26). Install the signed APK from
[GitHub Releases](https://github.com/LissomEnd/EnigmaGrid/releases/tag/android-v0.4.13),
register under Account, then choose Start contributing. Version 0.4.13 is published
as an experimental APK.

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
in Android app settings. Force-stop requires opening the app and starting again. Version 0.4.12 also
attempts to restore requested work after boot; physical reboot recovery remains
unverified. Android and vendor firmware can still stop applications.

Account registration and statistics are available in-app; advanced account
management does not yet have full parity with the volunteer web interface.
No admin functionality is included.

### Compatibility safeguards (0.4.13)

Version 0.4.13 checks Android's `ActivityManager.MemoryInfo.lowMemory`
alongside battery and thermal restrictions, with the same one-second cache.
The cooperative gate suspends computation and resumes when the system clears the
signal; Stop remains available while waiting. It preserves the current search
stack, so this is not a promise to release all allocated memory or prevent Android
from reclaiming the process. Controlled host tests cover the gate's recovery and
Stop behavior; forced system-wide memory exhaustion has not been tested on a phone.

Version 0.4.13 also explicitly excludes app state from Android 12+ cloud backup
and device transfer. Credentials and pending receipts already use no-backup storage;
GPU qualification, resource preferences and requested-work state must likewise not
be inherited by another phone. Existing installations keep their local data when
updated. Manifest/resource compilation and lint passed; a physical phone-to-phone
transfer has not been tested. See Android's
[backup rules](https://developer.android.com/identity/data/autobackup).

## Reporting another device

Use the [Android compatibility form](https://github.com/LissomEnd/EnigmaGrid/issues/new?template=android_compatibility.yml)
for successful tests as well as failures. CPU-only contributions are welcome.
Record the app version, model and Android version, the CPU check and optional
Vulkan computation check under Device. Report untested steps as untested.
If you observe background work, include the observation duration and whether the
screen was off; distinguish acknowledged receipts from independently verified work.
Do not include tokens, serial numbers, private addresses or full logs.

Compatibility evidence has different scopes:

| Evidence | What it establishes | What remains unproven |
| --- | --- | --- |
| Packaged ARM64, ARMv7 and x86_64 libraries | Native binaries are supplied for those architectures | Installation and execution on every model |
| Host CPU/adapter tests | Receipt parity and fallback behavior in controlled cases | Android vendor driver behavior |
| RedMagic NX789J physical tests | Observed CPU/GPU operation on the tested device and OS | Other Adreno models, Mali and other GPU families |
| A successful Device GPU check | The tested backend produced matching output during that check | Sustained utilization, speed advantage or future driver stability |

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
all workers. Vulkan calls remain serialized; 0.4.7 adds context reuse and
0.4.8 batches up to 16 core row tables per dispatch. A 100% setting permits activity but does not promise
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

Run `core/qualify_accelerator.py --jdk PATH` with a Windows JDK 17 to check the
CPU reference, adaptive fallback, batching and parallel receipt parity. Controlled
backend tests also cover a timeout-shaped exception, cancellation during a driver
failure and cancellation returned by the backend. A failed backend is latched off;
the same work uses CPU rows, while cancellation remains cancellation. These are
host adapter tests, not a simulated Android Binder timeout or physical driver crash.
The saved GPU qualification is tied to the backend revision and Android build
fingerprint; an OS build change requires requalification before GPU work resumes.

The lab-only `GpuRecoveryQualification` instrumentation was run on RedMagic
NX789J on 2026-10-04: a successful Vulkan request was followed by termination of
the lab's own GPU process. The next request recovered with CPU-identical rows
within the test's 12-second bound, and subsequent work kept the failed backend
disabled. The production app and its GPU process were not terminated. This covers
Binder process death, not every driver hang. Run with
`adb shell am instrument -w org.enigmagrid.android.lab/org.enigmagrid.android.GpuRecoveryQualification`
after installing the lab APK; remove the lab APK after testing.

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

## Client changes in 0.4.9

Registration now offers an explicit public-leaderboard choice, off by default.
Joining an existing contributor keeps that profile's visibility setting. Account
status distinguishes public and private profiles; verified work is required for
ranking. This does not yet provide an in-app toggle for an existing profile.

The bounded receipt outbox supports up to eight results, preserves legacy saved
receipts, and removes only the acknowledged result. Experimental multi-lease
support is disabled in normal client construction. It falls back to the single
lease route only when the batch endpoint returns HTTP 404. It validates the
whole batch before computation and rejects duplicate lease IDs.

Isolated RedMagic testing exercised eight-job batches, Vulkan, encrypted storage,
process restart and lost acknowledgment recovery. Sixteen replica receipts were
verified independently without duplicate credit. A host HTTPS comparison used
26 requests for batching versus 39 for single assignments on the same synthetic
workload, including a lost acknowledgment. This is not a device throughput or
CPU/GPU utilization measurement. Batch completion still sends receipts separately.

Single-core jobs no longer create a redundant executor. Cancellation disconnects
network sockets off the calling thread, and status distinguishes computation from
network waits. The reported production UI stall has not yet been reproduced or
confirmed resolved; these changes are not proof of its root cause.

## Client changes in 0.4.10

Normal clients now negotiate up to eight leases per request when the coordinator
provides the batch endpoint. HTTP 404 selects and caches single-lease mode for
that worker session; other failures retain their normal retry/error behavior.
The production 0.4.9 APK still uses single assignments. This source change alone
does not enable server batching or change campaign priorities or compute limits.

One renewal scheduler covers the complete batch, including slow receipt uploads.
A delayed-acknowledgment regression checks that heartbeat renewal continues while
the completion response is pending; the scheduler is closed on success or failure.

## Update policy compatibility (0.4.12)

The update checker accepts an Android-specific minimum version from the coordinator,
falling back to the shared minimum on older servers. This allows Android and Windows
release requirements to evolve independently. No production minimum is raised by
this client change; installation still requires Android confirmation.

## Background resume (0.4.12)

A system receiver attempts to resume user-requested, unpaused computation after
package replacement or completed boot. Stopped or paused sessions stay idle.
OEM restrictions may reject the start; the app records a manual-resume message.
Controlled adapter tests cover these decisions. Package replacement on RedMagic
resumed contribution with the existing account and resource preferences. Physical
reboot recovery remains unverified. Version 0.4.10 does not include this receiver. Run `python android/core/qualify_resume.py --jdk PATH` from the repository.

### Consolidated accelerator changes (0.4.12)

Cached GPU rows no longer wait for the next GPU dispatch duty interval. The
interval still applies to actual dispatches. Backend preparation failures now
latch CPU fallback, while cancellation still propagates. These changes are installed on RedMagic; compatibility across other physical GPU
drivers remains unverified.

Run `python android/core/qualify_accelerator.py --jdk <JDK-directory>` from the
repository root for controlled fallback, batching, duty, and parallel receipt
checks. No Android build or connected phone is required.

The CPU row implementation steps once per position and evaluates all
26 contacts, instead of running 26 complete decryptions. Host checks compare
1,344 rotor/reflector configurations, randomized rings and intervals, and explicit
double-step boundaries against the retained crypt primitive. This is a CPU
optimization; it does not establish physical GPU compatibility or whole-job speed.

### Qualification and remaining deployment limits

The Windows 0.4.4 constrained path uses reusable spawn processes with bounded
ordered batches. Host tests cover receipt parity, pause/resume preference changes,
CPU disable, pool resize/reuse, and cleanup on normal or exceptional exit. Child
processes enforce CPU duty; the parent avoids restricting their inherited CPU
affinity. The stabilization candidate is published and installed on two Windows
PCs. CI, frozen computation, installer lifecycle and artifact attestation passed.
Memory limits now reduce the process count or select serial fallback. Sustained
utilization and the active-job native update-dialog scenario remain open; it is
not promoted to the automatic latest-release channel.

Server lease responses can carry the control snapshot to avoid a redundant
heartbeat on short Windows jobs, with a legacy fallback. Queue indexes have been
measured on an isolated database copy. These changes do not establish that the
production validation backlog is resolved. Android physical GPU compatibility
beyond the tested device, full release testing and deployment remain open.

The on-device GPU qualification exercises batch sizes 1, 2 and 16 at
window lengths 1, 2, 3, 16, 71 and 72, including windows ending at position 72.
It compares GPU contacts against CPU results and checks full canonical receipts.
The final CPU/GPU receipt comparisons now also honor thread interruption. Host
batch tests cover packing and parity at the same boundaries; passing those tests
does not qualify Vulkan execution on a device. Release Java compilation and lint
are separate from these mathematical checks.

Windows also retains a completed receipt locally before upload, using the same
Windows DPAPI protection as enrollment state. On restart it retries that receipt
before requesting more work, and removes it only after an explicit successful
acknowledgement (including an idempotent duplicate). Network errors, malformed
acknowledgements and coordinator/device identity mismatches retain the receipt.
A rejected receipt currently blocks new work until investigated; it is never
silently discarded. This protects process-restart recovery, not a guarantee
against storage failure or sudden power loss.

The Windows renewal thread now remains active through completion upload, instead
of stopping when computation ends. A regression covers successful and failed
uploads, saved-result retention and thread cleanup. Upload time is excluded from
reported compute time. This source change is pending the coordinated deployment.

Native release compilation has passed for `arm64-v8a`, `armeabi-v7a` and `x86_64`.
Inspection of the generated Vulkan libraries confirms the corresponding ELF
architectures and 16 KiB LOAD-segment alignment. The final 0.4.12 APK also passes ZIP alignment checks. Execution on physical
devices with different page sizes/drivers remains a separate check; packaging
alone does not establish that compatibility.

Run `python android/core/qualify_apk_layout.py path/to/app.apk` to inspect every
packaged native library's ABI and ELF alignment and the ZIP alignment of stored
libraries. The local consolidated qualification APK passes this check, Android
`zipalign -c -P 16 4`, and signature verification with the existing release
certificate. Version 0.4.12 is installed on RedMagic. One real production receipt from this
version was independently reproduced successfully. This checks that calculation,
not a historical decryption, sustained throughput or all-device reliability.
The experimental Android 0.4.12 release is published. Coordinated Windows
deployment remains a separate gate.

Android 0.4.12 overlaps one receipt upload with the next
computation in an assigned batch. Both results are saved before delivery; only
the compute thread removes acknowledged receipts. At most two computed receipts
are pending in this pipeline, and one upload is active. Renewal continues until
the final acknowledgement. Host regressions require computation to advance while
an upload is blocked and verify recovery of both receipts after the first upload
fails. This pipeline is included in the built, layout-checked and installed 0.4.12 APK.
A device performance measurement is still needed; no throughput gain is claimed.

The pending Windows client also negotiates up to eight reservations per request.
It refreshes controls while consuming the batch and refetches expired local
snapshots after long pauses. Only HTTP 404 selects legacy single-job mode;
other errors are reported. Host tests exercise eight completions and safe stop
through the full worker loop, plus expired reservations, mandatory updates,
revocation, malformed batches and legacy fallback. Installed clients are still
unchanged; these checks do not measure production throughput.

## Android 0.4.13 deployment

Published as an experimental prerelease after CI passed for commit `6e82802`.
The signed APK was installed over 0.4.12 on RedMagic; contribution resumed with
LissomEnd 3 and the existing CPU/GPU settings. One new production receipt was
independently replayed with an exact match. Signature continuity and all three
native ABI layouts passed. Other physical devices remain unverified.

## Android 0.4.14 deployment

The experimental 0.4.14 prerelease prevents UI-started GPU diagnostics from
overlapping contribution or local checks. Cancelling diagnostics preserves the
previous GPU qualification. RedMagic UI instrumentation exercised both exclusion
directions and cancellation. CI passed for release commit `45ee858`; the signed
APK was installed in place and its foreground service resumed automatically,
preserving account identity and resource preferences. This restart check alone
does not prove a new completed receipt or sustained hardware utilization.

The host regression `qualify_native_unavailable.py --jdk PATH` also executes the
actual `VulkanBackend` class with an empty native-library path. It verifies CPU
fallback at six window boundaries, avoids repeated failed GPU attempts, and
checks that unavailable acceleration is not reported as active. This tests
missing JNI support, not physical Vulkan driver compatibility. No new phone
build is needed for this host-only regression.
