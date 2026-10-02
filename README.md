# Enigma Volunteer Grid

Volunteer-computing platform for the unresolved P1030680 Naval Enigma M4 message.

Current local release: coordinator 0.2 / worker 0.2.1. Lenovo is the current private coordinator; the public campaign is NOT activated and nothing has been published to GitHub.

## What works
- One long-lived append-only campaign model with deterministic work units.
- Crash-safe leases and automatic requeue after power/network loss.
- Independent contributor/device identities with opt-in public credit.
- Credit becomes final only after independent redundant validation.
- Server-side validation reproduces Enigma candidate plaintext/score/key/event before accepting a submission.
- 2-of-2 consensus by default; disagreements expand to 2-of-3 majority, otherwise manual review.
- Trust score, penalties, audit log and automatic device quarantine.
- Capability-aware scheduler for CPU and CUDA/GPU work.
- User-selectable CPU and GPU contribution percentages.
- CPU limits use process affinity + Numba thread limits; GPU jobs use an average duty-cycle limit.
- Global dashboard, personal dashboard, trust state and CPU/GPU sliders.
- Public HTTP is rejected by the worker; plaintext HTTP is allowed only for local/private/Tailscale endpoints.
- User-level install/autostart/uninstall without administrator rights.

## Security boundary
The coordinator never sends shell commands or executable code in a lease. It only chooses an engine already shipped with the worker. Device/dashboard/contributor secrets are stored hashed server-side. Result size is capped and rate limiting is enabled.

## Public deployment
`deploy/` contains a Docker + Caddy layout. Caddy terminates HTTPS; the coordinator is only exposed inside the private container network. State/config paths are environment-controlled, so moving from Lenovo to a VPS does not change the worker protocol.

## Still required before public launch
- Signed standalone Windows application/tray UI so volunteers do not need Python.
- A real packaged GPU solver engine; GPU scheduling/throttling is ready but the giant campaign currently contains CPU search segments only.
- Public domain/VPS, DNS, TLS deployment and release signing.
- Privacy notice, contributor terms and final security review.
- PostgreSQL/storage scale-out when concurrency outgrows a single SQLite coordinator.
