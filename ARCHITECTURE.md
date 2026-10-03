# Architecture

## Coordinator and transport

The Windows coordinator runs `server/coordinator.py` on loopback port 8765. Tailscale Funnel terminates public HTTPS and proxies only to that local service. Volunteers do not join the private tailnet. Docker/Caddy files are an alternative deployment template, not the current public deployment.

The HTTP server bounds concurrent request handlers and request size. Global, registration and per-device rate limits apply; anonymous visitors share a separate budget because Funnel presents a loopback peer address. Forwarded IP headers are not trusted for authentication.

## Identity and privacy

A contributor owns one or more devices. Random contributor, dashboard and device secrets are stored as hashes on the server. Windows client state uses DPAPI CurrentUser. The private browser dashboard keeps its token in memory and clears outstanding display requests when the user clears it. The desktop onboarding defaults to private credit.

## Portable CPU and GPU search

`portable_event_v1` runs deterministic trajectories in blocks of at most 256 keys. CPU and OpenCL implementations use the same integer scoring and mutation decisions. Each detected GPU must reproduce CPU scores for the supported event models before use. Final candidates are decrypted and scored again with the CPU reference path. A combined job divides scoring batches between CPU and GPU without changing the trajectory results.

The CPU slider sets affinity/thread budget; the GPU slider sets a work/rest budget between scoring iterations. Zero disables assignment to that resource. GPU computation still requires host CPU coordination. These are scheduling controls, not exact instantaneous utilization guarantees. Changes apply to the next job. Pause blocks at search checkpoints; safe stop completes the current job and preserves the stop request across restarts.

The prepared public campaign uses three plugboard profiles and six operator-event hypotheses. Seed intervals do not overlap between profiles. Equal-priority segments are scheduled according to fraction assigned so each profile can make progress. None of these fractions represents probability of decryption or exhaustive keyspace coverage.

## Leases and validation

Work ranges are half-open `[start_unit, end_unit)`. Heartbeats renew leases; expired primary work is requeued. Duplicate or stale submissions cannot receive duplicate credit.

Every submitted candidate passes type, range, key and event checks before native scoring. The coordinator reproduces its plaintext and score. A first valid submission remains pending until a different contributor or the local server verifier independently recomputes the search and produces a matching fingerprint. The server does not read submitted candidates to generate its result and receives no contribution credit. Disagreement requests a third replica; unresolved disagreement enters manual review. Repeated invalid work reduces trust and can quarantine a device.

Redundant computation is not cryptographic proof of total effort or strong identity verification. Colluding accounts remain a limitation; registration challenges, rate limits and quarantine reduce abuse but do not establish that each account is a different person. A reproducible or high-scoring candidate is not proof of historical decryption.

## Storage and updates

SQLite WAL stores campaigns, leases, results and credit. Backups use SQLite's online backup API. State, private configuration and backups are excluded from Git and restricted by host ACLs. Account deletion removes personal records while retaining anonymous completed ranges.

Updates require a manifest signed by the pinned Ed25519 release key plus matching file size and SHA-256. The updater verifies staging, waits for the worker to exit, applies at a job boundary and restores the prior runtime if the post-update check fails. The private signing key remains outside the repository.
