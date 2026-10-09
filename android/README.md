# EnigmaGrid for Android

EnigmaGrid is an experimental Windows and Android volunteer-computing project.
One official Android app is sufficient for contribution; the separate Lab package
is only an isolated development tool. Download published packages from
[GitHub Releases](https://github.com/LissomEnd/EnigmaGrid/releases).
This client currently computes `bounded_crib_v1` jobs; the Windows
`portable_event_v1` search is not included in its Android engine list.

The current source targets the coordinated **0.5.0 candidate**. A source version
is not evidence that a package is published, installed or qualified on a device.
Release notes identify the tested package hashes and hardware.

## Contributing

Open **Compute**, create or join a contributor identity, then start contribution.
CPU and GPU sliders control the app's aggregate duty budget. At 100%, the app
requests continuous work without duty pauses. This is not a promise that every
engine can occupy every hardware execution unit. Useful completed units per wall
second, queue starvation and the selected backend explain actual performance.

The client negotiates the coordinator's capabilities. Where long work blocks
are enabled, compatible primary work can target thirty minutes of local work,
subject to available work and safety bounds. With fewer than two reservations,
the client initially fills toward thirty minutes, then requests the next block
when its estimated reserve reaches ten minutes. A measured speed increase can
reopen the initial fill so a stale estimate does not delay prefetch. Validation
exposure and fragmented eligible ranges can prevent a thirty-minute reserve;
the client never bypasses these checks or validates its own contributor's work.
CPU computation, durable result
storage and result upload overlap. Two-hour reservation validity is distinct
from the thirty-minute work target; expired or recovered reservations require
authoritative confirmation before execution. An older coordinator uses the
supported legacy lease path instead.

CPU executors and Vulkan resources are reused. CPU and qualified GPU solver
lanes can consume separate work from the same reservation. A GPU row generator
alone is not a GPU solver: Monitor reports the backend actually in use. Device
qualification compares canonical receipts, checks performance and falls back
with a reason when a backend fails or does not help. Supported ABI packaging
alone does not qualify a physical GPU or driver.

When only the CPU backend is available at a 100% CPU budget, the client can
compare one and two compute lanes using four short windows of actual assigned
work. It measures receipts saved durably per wall second, checks acknowledgment
progress and rejects comparisons interrupted by starvation, memory pressure or
protection limits. A second lane is retained only after a consistent measured
gain; switching lanes waits for current receipts to be saved. The saved profile
is specific to the app, hardware and work configuration. This performance
profile does not grant scientific credit or replace independent verification.

## Four sections

- **Compute:** start, pause, resume and stop, with the current restriction or task.
- **Monitor:** CPU/GPU utilization with coloured legends, available temperatures,
  separate Units/s and Jobs/s charts, queue state and sensor provenance.
- **Results:** personal contribution and the global scoreboard. Accepted, trusted
  and independently verified results are distinct.
- **Settings:** resource preferences, updates, account controls and one general
  device check, with detailed diagnostics available when needed.

Sensors are sampled independently of computation. Unavailable readings remain
unavailable; they are not zero and gaps are not filled with invented values.
System GPU utilization and app CPU utilization have different scopes and are
labelled accordingly. Jobs/s must not be compared across different job sizes as
though it measured equal scientific work.

## Safety and background work

Android thermal protection, battery protection, memory pressure and the
charging-only preference remain effective at every slider setting. Configurable
CPU/GPU temperature ceilings supplement these protections; they do not override
the operating system or hardware. Raising a ceiling cannot make unavailable GPU
work parallel or remove memory contention.

Contribution runs in a foreground service with a bounded renewed partial wake
lock. Android shows the ongoing notification when notification permission is
granted; denying it does not prevent user-started work, and the service remains
visible in Android's foreground-service task manager. For screen-off or overnight
work, the app offers Android's standard battery-optimization permission with
explicit user consent. Declining that request does not stop contribution or
discard pending results. The permission does not guarantee continuous execution:
Android and vendor firmware can still restrict or stop an app. Force-stop
requires reopening it. Pending
results are encrypted and retained until individually acknowledged; a rejected
result is reported rather than silently discarded.

The dark cooling screen is not an operating-system lock screen. The app cannot
set the REDMAGIC fan speed through an approved Android interface; its cooling
dialog offers a button to open the OEM fan controls so the user can set it.
The black screen does not imply maximum fan speed.

## Private performance diagnostics

While contributing to a capable coordinator, the client samples once per second,
aggregates into five-second buckets and sends a bounded diagnostic packet every
thirty seconds. It includes performance, queue and restriction information with
version, backend and sensor scope. This is separate from durable scientific
receipts: a diagnostic failure must not block computation or result delivery.
See [Privacy](../PRIVACY.md) for fields, retention and account deletion behavior.

## Updates

Use an in-place update signed by the original certificate. Do not uninstall the
app to work around a signature mismatch: that would remove its local identity
and pending receipts. Updates check the APK's size, SHA-256, application ID,
increasing version code and signing certificate. Android still controls install
permission and confirmation. Background update checks are subject to Android's
network and battery scheduling; automatic Wi-Fi download is optional.

Credentials, pending receipts and device-specific configuration are excluded
from cloud backup and phone-to-phone transfer. They must not be cloned as the
identity of a second volunteer device.

## Compatibility and verification

The configured minimum is Android 8/API 26. Native ARM64, ARMv7 and x86_64
libraries are packaged; physical execution on each device remains a separate
qualification. CPU-only contributions are supported. Vulkan behavior depends
on the device, driver, available memory and workload.

A qualification result proves the tested comparisons on that backend and driver.
It does not establish a historical decryption, universal speed advantage or
future driver stability. Report successes and failures through the
[compatibility form](https://github.com/LissomEnd/EnigmaGrid/issues/new?template=android_compatibility.yml),
including app version, model, Android version, backend and observation duration.
Do not include tokens, serial numbers, private addresses or full private logs.

## Building and host checks

Use JDK 17, Gradle 8.9, Android SDK 35, NDK 27.2.12479018 and CMake 3.22.1.
Build development code with `gradle -p android :app:assembleDebug`.
Release signing uses `ENIGMAGRID_ANDROID_KEYSTORE` and
`ENIGMAGRID_ANDROID_STORE_PASSWORD`, alias `enigmagrid`; keep the key outside
this repository. `:app:assembleRelease` remains unsigned if the keystore
variable is absent. Verify the APK signer against the installed app before
any in-place update.

Before packaging, host checks exercise receipt parity, resource controls,
cancellation, pipeline recovery and updates without a connected phone:

```text
python android/core/qualify_accelerator.py --jdk <JDK-directory>
python android/core/qualify_network_cycle.py --jdk <JDK-directory>
python android/core/qualify_work_blocks.py --jdk <JDK-directory>
```

Host checks do not replace the consolidated physical-device qualification.
The Lab variant is never required to increase production throughput.
