# 0.5.1 release candidate

Source preparation for Windows and Android update distribution. The existing latest published release was v0.4.14 when prepared. **This file is not proof of publication.**

Changes:
- Android qualified Vulkan row computation, separate full solver timeout handling, optional 128-key batch on Samsung SM-T500 and retained CPU fallback.
- New Android and Windows block and telemetry work, bounded durable result transport and automatic C4 eligibility for all registered platforms.
- Live public C3/C4 stage presentation and enhanced localhost-only admin transition, backup, validation and client diagnostics.
- Windows and Android version moved to 0.5.1; Android versionCode 75.

Safety: no unilateral thermal override, no reduction of independent verification rules, no private account or coordinator configuration in this source release. C4 activation remains gated on C3 completion and an integrity-verified restoreable backup. No claims that an untested GPU backend accelerates all workloads.

Publish ONLY after source CI passes and the exact candidate binary payloads are verified. Windows automatic updates require the separately Ed25519-signed update manifest, a matching ZIP and published release assets. Android upgrades require the original signing certificate and strictly increasing versionCode. A source-only GitHub commit will not automatically update installed clients.
