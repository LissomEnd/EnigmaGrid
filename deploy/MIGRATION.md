# Migration / public HTTPS deployment

Lenovo is the current development coordinator. The application is location-independent: state is under `GRID_DATA_DIR`, and host/port/config/secrets are environment-overridable.

## Move to a VPS
1. Stop the Lenovo coordinator cleanly.
2. Run `python scripts/backup_grid.py` and copy the resulting SQLite backup to the new host.
3. In `deploy/`, run `Prepare-Deployment.ps1 -Domain enigma.example.org`. It creates ignored `server.production.json` and `.env`, including a random registration code.
4. Point DNS for the hostname to the VPS and make TCP 80/443 (and optionally UDP 443 for HTTP/3) reachable by Caddy.
5. Restore the DB into the `grid_data` volume or start with a clean DB.
6. Run Docker Compose from `deploy/`. Only Caddy publishes ports; the coordinator remains private inside the container network.

Caddy obtains/renews the public certificate and proxies HTTPS traffic to the coordinator. The worker refuses public plaintext HTTP URLs.

## Scale-out later
SQLite is appropriate for the current single-coordinator stage. Before high concurrency, move the storage implementation to PostgreSQL and add coordinator failover while preserving the HTTP lease protocol.

## Secrets
`config/server.json`, `deploy/server.production.json`, `deploy/.env`, databases, logs and built worker bundles are ignored by Git. Rotate registration codes and affected device/dashboard tokens after any suspected exposure.
