# Security Policy

## Reporting a vulnerability
Do not open a public issue for a security vulnerability. Once the GitHub repository is public, use GitHub Private Vulnerability Reporting / Security Advisories.

Include the affected version, reproduction steps, impact and any proposed mitigation. Do not include real user tokens or private data.

## Update trust model
Clients accept update packages only when the release manifest verifies against the Ed25519 public key embedded in the worker and the downloaded asset matches the signed SHA-256 and size.

The private release-signing key is kept outside the repository in an ACL-restricted DPAPI CurrentUser vault on Lenovo and must never be committed to GitHub. Normal signing decrypts it only in memory. This protects against repository/CI disclosure and offline theft of the blob, but a compromise running as the Lenovo signing user could still obtain signing authority. GitHub artifact attestations are an additional provenance signal, not a replacement for the pinned release signature.

## Server exposure
The coordinator must bind to loopback only. Public access must go through Tailscale Funnel or an equivalent authenticated TLS reverse tunnel. Do not port-forward the coordinator from the home router.

## Secrets
Database files, server configuration, backups, update state, release bundles and environment files are excluded from Git. Rotate credentials after any suspected disclosure.

On Windows, volunteer client credentials are stored with DPAPI CurrentUser encryption. Older plaintext client-state files are migrated automatically on first load. Non-Windows fallback files are written with user-only permissions where supported.

On the Lenovo coordinator host, the live state directory, backups and private server configuration are ACL-restricted to the service owner and SYSTEM. The coordinator refuses non-loopback binds unless an explicit isolated-container override is set.

## Privilege isolation
The preferred Windows deployment runs the coordinator under LOCAL SERVICE using scripts/Install-HardenedServerTask.ps1. This one-time step requires an elevated Administrator session; until then, the current-user deployment must retain the restricted ACLs above.

## Supported versions
Critical releases may raise `min_worker_version`. Older workers then stop receiving leases and must update or close safely.
