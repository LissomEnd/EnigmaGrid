# Contributing

There are two ways to contribute: volunteer compute and source-code improvements.

## Volunteer compute
Install the official Windows Setup from a project release, choose a display name, and select how much CPU/GPU capacity you want to contribute. You can pause or stop at any time.

Public credit is opt-in. When enabled, the public leaderboard shows the display name you chose and aggregate verified contribution statistics. Credit is based on independently verified work, not raw submissions.

A result is not considered final merely because it has a high language score or round-trips through Enigma. The coordinator applies deterministic validation and redundant independent computation before granting final credit.

## Fair-use rules
Do not modify a client to fabricate work, replay another contributor's results, bypass resource controls, flood registration, or manipulate credit. Devices producing invalid or inconsistent work may lose trust and be quarantined automatically.

Unexpected shutdowns and network loss are normal: leases expire and are safely requeued. Volunteers do not need to stop the application before shutting down Windows.

## Source changes
Keep security-sensitive changes small and testable. New solver engines must be deterministic enough for server-side or redundant validation and must never execute arbitrary coordinator-provided code.

Before opening a pull request, run the source security/integration suite and the platform-specific tests relevant to your change. Do not commit private coordinator state, tokens, signing keys, local IP addresses, Tailscale private addresses, or build output.

## Attribution
Repository contributors are credited through Git history and GitHub. Volunteer-compute contributors are credited separately through verified aggregate work when they opt into public credit.

## Security reports
Do not disclose exploitable vulnerabilities publicly before they can be fixed. Follow SECURITY.md for security reporting guidance.
