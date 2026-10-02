# Architecture v0.2

## Control plane
Lenovo currently runs `server/coordinator.py` on port 8765. Public deployment is containerized and places Caddy in front of the coordinator; only Caddy exposes 80/443.

## Identity
A contributor owns one or more devices. The contributor join key, dashboard token and per-device token are generated randomly and stored only as hashes on the server. Public leaderboard credit is opt-in.

## Resource policy
Each device reports CPU count and GPU capabilities. Settings contain `cpu_percent`, `gpu_percent`, `allow_cpu` and `allow_gpu`. Segment configs declare `requires`, e.g. `['cpu']` or `['cuda']`. The scheduler leases only eligible work.

CPU percentage maps to logical-core affinity and Numba thread count. GPU percentage is returned in the lease and enforced by worker duty-cycle between GPU jobs. This avoids changing global GPU power limits on the volunteer's machine.

## Lease/failure model
Work is `[start_unit,end_unit)` and deterministic. Heartbeats renew leases. A crashed primary lease expires and is requeued. Validation leases can simply expire because the pending validation itself remains schedulable.

Late/duplicate work is safe: accepted unique ranges live in `done_ranges`; stale completions cannot receive duplicate credit.

## Validation and anti-cheat
Every submitted result first passes server validation. Demo jobs are recomputed exactly. Enigma event-stochastic candidates are checked for valid range/seed, key/event structure, 72-character plaintext, and server-side reproduction of plaintext and score.

Valid first submissions remain pending. A different contributor must independently recompute the same range. Matching fingerprints verify the range and both contributors receive credit. A mismatch raises the target to a third replica; 2-of-3 matching results win. Three different results enter manual review.

Verified devices gain trust slowly. Invalid server validation receives a severe penalty; consensus mismatch receives a smaller penalty. Repeated serious failures automatically quarantine and disable a device.

## Data and migration
SQLite WAL is used for the current single coordinator. DB/config locations are environment-overridable (`GRID_DATA_DIR`, `GRID_DB`, `GRID_CONFIG`). Backup uses SQLite's online backup API. Docker deployment mounts state as an external volume, so moving hosts is copy/restore rather than a protocol change.

## HTTPS
The worker refuses plaintext HTTP to public addresses. Local/private/Tailscale HTTP is allowed for development. Production uses Caddy automatic HTTPS and a private HTTP hop from Caddy to the coordinator container.

## Scale path
Workers/campaign manifests are storage-agnostic. When concurrency requires it, replace the coordinator storage implementation with PostgreSQL and add coordinator failover/object storage for archives without changing the worker lease protocol.
