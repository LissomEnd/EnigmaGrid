# Privacy

Enigma Volunteer Grid is designed to collect the minimum data needed to coordinate volunteer computation.

## Data collected
- Contributor display name chosen by the user. It is public only when public credit is enabled.
- Random contributor/device identifiers and cryptographic authentication tokens. Server-side tokens are stored only as hashes.
- Coarse compute capabilities: CPU logical-core count, architecture, GPU vendor/model/memory, supported CPU/GPU backends, and the CPU/GPU percentages selected by the user.
- Worker version, last-seen timestamp, trust/validation counters, completed work units and compute-time statistics.

## Data deliberately not collected
- Public/home IP addresses are not written to the database or application logs.
- Computer hostname, GPU UUID/serial, email address, precise location, browser history, personal files and document contents are not collected.
- The dashboard does not use advertising or tracking cookies. Its private token is kept only in browser session storage.

## Network providers
Public coordinator traffic is intended to use Tailscale Funnel. Software updates are downloaded from GitHub Releases. Those providers may process ordinary network metadata under their own privacy terms.

## Retention
- Technical audit records: 30 days.
- Hardware metadata of disabled devices: scrubbed after 90 days.
- Contribution records remain until the contributor requests deletion.
- Expired registration proof-of-work nonces are automatically deleted.

## Deletion
A contributor authenticated with the private dashboard token can request account deletion. Devices, contribution statistics, pending submissions and associated audit records are removed. Completed cryptographic search results remain only as anonymous research data with the device identity replaced.

Do not publish dashboard tokens, device tokens or contributor-link keys.
