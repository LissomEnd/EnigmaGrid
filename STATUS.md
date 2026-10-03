# Release validation status — 2026-10-03

[EnigmaGrid 0.4.0 is publicly released](https://github.com/LissomEnd/EnigmaGrid/releases/tag/v0.4.0), with real CPU and OpenCL search, a Windows x64 installer, resource controls, a tray application, a public dashboard and signed updates.

## Verified locally

- Source security, HTTP integration, public-surface, consensus and quarantine tests pass.
- Native-array input bounds, coordinator redirect rejection, shared-proxy rate limits and safe uninstall path tests pass.
- Resource routing, pause checkpoints and safe-stop completion tests pass.
- CPU/OpenCL parity passes on AMD integrated graphics and Intel Iris Plus.
- The installed Windows client completed matching CPU+GPU and CPU work on both Lenovo and Surface, with independent contribution credit.
- Installer lifecycle, payload hashes, registry cleanup and uninstall pass.
- A signed update succeeds; an intentionally mismatched version triggers rollback.
- A pattern scan of the pre-release Git history and working tree found no matching credential or private-address patterns. This is not a guarantee against every possible secret.

## Deployment and publication

The coordinator is bound to loopback and exposed through Tailscale Funnel HTTPS. Public registration is open and the 75,000-unit portable campaign is running. A Surface with Intel Iris Plus is contributing real CPU+GPU work; initial accepted results await independent volunteer reproduction before final credit.

The published installer and ZIP were built from commit `de1404bb3b7e4c9085d5136d71be7a7f02733cb8` in [release workflow 37110771127](https://github.com/LissomEnd/EnigmaGrid/actions/runs/37110771127). Both GitHub attestations were verified locally, their uploaded digests matched, and the exact ZIP's update manifest was signed and verified. The exact published installer was downloaded anonymously on Surface, hash-checked and tested: CPU+GPU and CPU runs produced the same fingerprint and independent test credit. Signed update success and intentional rollback were also tested against the published package.

[An independent public-service check](https://github.com/LissomEnd/EnigmaGrid/actions/runs/37111855534) passed from a GitHub-hosted Ubuntu machine outside the private network after launch. See the release assets for checksums and signatures. Old local research campaigns are stopped and their scientific results are preserved separately; they are not part of the public participant database.

## Limits

The executables are not Authenticode-signed. NVIDIA OpenCL compatibility has not been tested on a physical device in this release audit. The official installer targets Windows x64. The search is heuristic and no confirmed historical decryption has been established. See README.md, SECURITY.md and THIRD_PARTY_NOTICES.md.
