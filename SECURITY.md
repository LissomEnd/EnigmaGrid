# Security Policy

## Reporting a vulnerability
Do not open a public issue for a security vulnerability. Once the GitHub repository is public, use GitHub Private Vulnerability Reporting / Security Advisories.

Include the affected version, reproduction steps, impact and any proposed mitigation. Do not include real user tokens or private data.

## Update trust model
Clients accept update packages only when the release manifest verifies against the Ed25519 public key embedded in the worker and the downloaded asset matches the signed SHA-256 and size.

The private release-signing key is intentionally kept off the public coordinator and must never be committed to GitHub. GitHub artifact attestations are an additional provenance signal, not a replacement for the pinned release signature.

## Server exposure
The coordinator must bind to loopback only. Public access must go through Tailscale Funnel or an equivalent authenticated TLS reverse tunnel. Do not port-forward the coordinator from the home router.

## Secrets
Database files, server configuration, backups, update state, release bundles and environment files are excluded from Git. Rotate credentials after any suspected disclosure.

## Supported versions
Critical releases may raise `min_worker_version`. Older workers then stop receiving leases and must update or close safely.
