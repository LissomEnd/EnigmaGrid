# Enigma Volunteer Grid

Volunteer-computing platform for the unresolved P1030680 Naval Enigma M4 message.

Current local release: coordinator 0.3 / worker 0.3.0. Lenovo is the private coordinator. The global campaign is prepared but NOT activated, no GitHub remote exists, and nothing has been published.

## Volunteer experience
- Windows volunteers use a standalone `EnigmaGridSetup.exe`; Python and administrator rights are not required.
- Setup installs under the current user's `%LOCALAPPDATA%`, starts the tray app automatically and registers an HKCU uninstall entry.
- Tray controls pause/resume, CPU/GPU contribution percentages, update checks and safe shutdown.
- Worker credentials are DPAPI-encrypted on Windows.
- Uninstall first stops contribution safely and removes autostart/runtime files. Local identity data is retained by default and can be purged explicitly.

## Distributed-computing guarantees
- One long-lived append-only campaign with deterministic work units.
- Crash-safe leases and automatic requeue after power/network loss.
- Independent contributor/device identities with opt-in public credit.
- Final credit only after independent redundant validation.
- 2-of-2 consensus by default; disagreements expand to 2-of-3 majority, otherwise manual review.
- Server-side reproduction of Enigma result/key/event before acceptance.
- Trust score, penalties, audit log and automatic device quarantine.

## Resource and update controls
- Capability-aware CPU/CUDA scheduling.
- User-selectable CPU and GPU contribution percentages.
- CPU limits use affinity + Numba thread limits; GPU work uses an average duty-cycle limit.
- Signed Ed25519 updates are downloaded in the background and applied only at a safe lease boundary.
- Mandatory updates can stop obsolete workers; failed updates automatically roll back.

## Security boundary
The coordinator never sends shell commands or executable code in a lease. It only selects engines already shipped with the worker. Device/dashboard/contributor secrets are hashed server-side; client secrets use DPAPI on Windows. Public plaintext HTTP is rejected by the worker.

Lenovo's coordinator is loopback-only. The intended public entrypoint is Tailscale Funnel/HTTPS so the Lenovo's public IP is not exposed. Funnel is not yet enabled.

## Still required before public launch
- Configure and verify the Tailscale Funnel endpoint and inject only that HTTPS endpoint into public releases.
- Final public bootstrap so volunteers do not manually enter the server URL.
- Final security/privacy review and contributor terms.
- Decide whether to ship a production GPU search segment; current global manifest is CPU-focused.
- Optional future PostgreSQL/failover only if volunteer concurrency outgrows the single Lenovo/SQLite coordinator.
