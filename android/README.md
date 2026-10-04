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
Background periodic update checking is not yet implemented.

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
all workers. Vulkan calls remain serialized; GPU batching/context reuse remains
an optimization opportunity. A 100% setting permits activity but does not promise
full hardware utilization for every job.

Parallel qualification compares complete receipts with Python and sequential
Java, including candidate caps and 128-core domains. Other Android hardware
still requires on-device qualification.
