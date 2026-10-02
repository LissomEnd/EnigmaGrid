# Release validation status — 2026-10-03

The 0.4.0 candidate includes real CPU and OpenCL search, a Windows x64 installer, resource controls, a tray application, a public dashboard and signed updates.

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

The coordinator is bound to loopback and exposed through Tailscale Funnel HTTPS. Version 0.4.0 responds on the configured endpoint. Registration remains closed while publication is being completed. The portable campaign manifest is prepared and has not yet been activated.

This file records development evidence, not a claim that a release is published. Consult GitHub Releases for the exact published version, assets, hashes, provenance and known limitations. Candidate hashes are intentionally kept out of this document because rebuilds change them.

## Limits

The executables are not Authenticode-signed. NVIDIA OpenCL compatibility has not been tested on a physical device in this release audit. The official installer targets Windows x64. The search is heuristic and no confirmed historical decryption has been established. See README.md, SECURITY.md and THIRD_PARTY_NOTICES.md.
