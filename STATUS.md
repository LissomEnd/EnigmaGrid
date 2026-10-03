# Release validation status — 2026-10-03

[EnigmaGrid 0.4.1 is publicly released](https://github.com/LissomEnd/EnigmaGrid/releases/tag/v0.4.1), with real CPU and OpenCL search, a Windows x64 installer, resource controls, a tray application, a public dashboard and signed updates.

## Final launch audit and 0.4.1 reliability fix

Production logs exposed a Windows status-file sharing violation in 0.4.0 that could stop and restart the worker. Version 0.4.1 retries temporary write locks and prevents a failed telemetry write from aborting computation. Durable identity and control writes still report persistent failures. Regression tests include a real Windows file-sharing lock.

The 0.4.1 packages were built from `6b7c26a10c2cdc595197fec45da987be79787900` in [build 37114159341](https://github.com/LissomEnd/EnigmaGrid/actions/runs/37114159341). [Source CI](https://github.com/LissomEnd/EnigmaGrid/actions/runs/37114159012), frozen client and installer lifecycle tests passed. Both package attestations, uploaded asset digests and the signed update manifest were verified. The exact ZIP passed successful update and intentional rollback tests. The latest [outside-network HTTPS check](https://github.com/LissomEnd/EnigmaGrid/actions/runs/37114161818) passed.

Surface downloaded the public 0.4.1 installer, verified its SHA-256 and upgraded without changing the existing contributor identity or settings. Physical Intel Iris Plus qualification passed. During live CPU+GPU computation, 60 forced status-file locks over about two minutes caused no worker exit or restart, no new unhandled exception, and health updates recovered on the same process. Windows autostart remains enabled.

The coordinator remains bound only to loopback; Funnel proxies HTTPS to that service. Windows Firewall and Defender are enabled. Internal Git, configuration and database paths return 404 over the public endpoint. The scheduled backup was manually run successfully and its SQLite integrity check passed. These are scoped checks, not a comprehensive independent penetration test.

[Issue forms](https://github.com/LissomEnd/EnigmaGrid/issues/new/choose) are enabled and checked in the browser for bug reports, installation help and feature/accessibility requests. Private vulnerability reporting is enabled separately. See [SUPPORT.md](SUPPORT.md) for reporting guidance and expected pending-validation behavior with a single contributor.

## Verified locally

- Source security, HTTP integration, public-surface, consensus and quarantine tests pass.
- Native-array input bounds, coordinator redirect rejection, shared-proxy rate limits and safe uninstall path tests pass.
- Resource routing, pause checkpoints and safe-stop completion tests pass.
- CPU/OpenCL parity passes on AMD integrated graphics and Intel Iris Plus.
- The installed Windows client completed matching CPU+GPU and CPU work on both Lenovo and Surface, with independent contribution credit.
- Installer lifecycle, payload hashes, registry cleanup and uninstall pass.
- A signed update succeeds; an intentionally mismatched version triggers rollback.
- A pattern scan of the pre-release Git history and working tree found no matching credential or private-address patterns. This is not a guarantee against every possible secret.

## Initial 0.4.0 deployment validation

The coordinator is bound to loopback and exposed through Tailscale Funnel HTTPS. Public registration is open and the 75,000-unit portable campaign is running. A Surface with Intel Iris Plus is contributing real CPU+GPU work; initial accepted results await independent volunteer reproduction before final credit.

The published installer and ZIP were built from commit `de1404bb3b7e4c9085d5136d71be7a7f02733cb8` in [release workflow 37110771127](https://github.com/LissomEnd/EnigmaGrid/actions/runs/37110771127). Both GitHub attestations were verified locally, their uploaded digests matched, and the exact ZIP's update manifest was signed and verified. The exact published installer was downloaded anonymously on Surface, hash-checked and tested: CPU+GPU and CPU runs produced the same fingerprint and independent test credit. Signed update success and intentional rollback were also tested against the published package.

[An independent public-service check](https://github.com/LissomEnd/EnigmaGrid/actions/runs/37111855534) passed from a GitHub-hosted Ubuntu machine outside the private network after launch. See the release assets for checksums and signatures. Old local research campaigns are stopped and their scientific results are preserved separately; they are not part of the public participant database.

## Limits

The executables are not Authenticode-signed. NVIDIA OpenCL compatibility has not been tested on a physical device in this release audit. The official installer targets Windows x64. The search is heuristic and no confirmed historical decryption has been established. See README.md, SECURITY.md and THIRD_PARTY_NOTICES.md.
