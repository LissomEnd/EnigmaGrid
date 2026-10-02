# Enigma Volunteer Grid

Volunteer-computing platform for the unresolved P1030680 Naval Enigma M4 message.

Current local release candidate: coordinator 0.3 / Windows worker 0.3.0. The coordinator remains private on loopback. The repository has not been published yet.

## For volunteers
Download `EnigmaGridSetup.exe` from an official GitHub Release and run it. Python, PowerShell, administrator rights and manual server configuration are not required.

The Windows app provides:
- guided first-run onboarding with a contributor display name and explicit resource-use consent;
- user-selectable CPU and GPU contribution percentages;
- pause/resume, safe stop, Windows autostart and update checks;
- live global and personal verified-contribution statistics;
- automatic hardware capability detection;
- a tray menu and browser dashboard;
- clean uninstall with an optional purge of the local contributor identity.

The public endpoint is bundled as signed release configuration. Volunteers never enter or see the coordinator's private IP address.

## Validation and credit
Work is issued as deterministic units with crash-safe leases. Unexpected shutdown or network loss does not damage the campaign; expired work is requeued.

Final credit requires independent reproduction. The default policy is 2-of-2 agreement; disagreement expands validation and can enter manual review. Invalid work receives no credit, repeated serious failures reduce trust, and devices can be quarantined.

The coordinator also reproduces accepted Enigma result/key/event structures before final acceptance. A high language score or software round-trip alone is never treated as proof of a historical decryption.

## Security
The coordinator sends structured work descriptions only for solver engines already shipped with the worker. It cannot send shell commands or arbitrary executable code.

Windows client credentials are encrypted with DPAPI. Server-side device, contributor and dashboard secrets are stored as hashes. Public metadata is sanitized and excludes hostname, Python details and GPU UUIDs.

Updates use an Ed25519-signed manifest, SHA-256/size verification, safe-boundary application, mandatory-version enforcement and automatic rollback after a failed health check.

The Lenovo coordinator binds only to `127.0.0.1:8765`. Public access is designed exclusively through Tailscale Funnel HTTPS, so no router port-forward or home public IP is exposed.

## Public launch status
The application, installer, updater, rollback path, public HTTP surface, consensus validation and security tests are complete locally.

One external account action remains before public access can work: Tailscale Funnel must be enabled for the tailnet. Until that approval is granted, the configured HTTPS hostname is intentionally unreachable from the public internet.

The Windows binaries are not Authenticode-signed because the project currently has no paid code-signing certificate. Windows SmartScreen may therefore show an Unknown Publisher warning on early releases. Official release SHA-256 hashes, the GitHub artifact attestation and the project's signed update chain provide independent integrity checks.

See `PRIVACY.md`, `SECURITY.md`, `CONTRIBUTING.md` and `RELEASE.md` before publishing or contributing.
