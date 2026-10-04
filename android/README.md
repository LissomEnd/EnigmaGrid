# EnigmaGrid for Android 0.4.3

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
