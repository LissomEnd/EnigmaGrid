# Release procedure

Release updates use two independent trust layers: GitHub build provenance and the project Ed25519 release signature.

## First public release
1. Create the GitHub repository from the final local commit.
2. Replace the repository placeholder in the live coordinator config with the final `OWNER/REPOSITORY`.
3. Run CI and the Windows release-candidate workflow from that exact commit.
4. Verify GitHub artifact attestations for both `EnigmaGridSetup.exe` and the Windows update ZIP.
5. Create and locally sign `update-manifest.json` for the exact update ZIP.
6. Publish a GitHub Release containing `EnigmaGridSetup.exe`, the Windows update ZIP, `update-manifest.json`, and `update-manifest.sig`.
7. Keep registration closed until the release assets and public HTTPS endpoint have both been independently verified.
8. Enable Tailscale Funnel only to the loopback coordinator on port 8765, re-run public-surface checks, then open public registration.

## Normal update release
1. Run CI and the release-candidate workflow from the intended commit.
2. Download the update ZIP and verify its GitHub artifact attestation.
3. Create `update-manifest.json` locally with `scripts/create_update_manifest.py`, specifying the final repository, semantic version and release notes.
4. Sign the exact manifest on the trusted signing machine with `scripts/sign_update_manifest_dpapi.py`.
5. Verify `update-manifest.sig` using the public key embedded in the worker.
6. Upload the update ZIP, manifest and signature to the GitHub Release.
7. Only after the release is fully visible may `min_worker_version` be raised for a mandatory update.

Mandatory updates are downloaded in the background and applied only between leases. Refusal finishes current work and closes safely. A failed post-update health check restores the previous frozen runtime automatically.

## Key handling
The private Ed25519 release key must remain outside the repository. Normal signing decrypts it only in memory from the protected local vault; no plaintext PEM is written during normal signing.

Never put the private key, decrypted PEM, protected key blob, device/dashboard tokens, state databases, private IP addresses, or coordinator backups in GitHub, CI secrets, releases, issues, chat, or the public project directory.

## Windows code signing
The current Setup is not Authenticode-signed. If the project later obtains a trusted code-signing certificate, sign the final immutable EXE after the reproducible build and before publishing its final SHA-256. Do not replace the project's Ed25519 update-signature system with Authenticode; they protect different parts of the release chain.
