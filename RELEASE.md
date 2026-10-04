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
   For a required update, set `--mandatory` or a `--min-supported` version above the affected clients. The signed manifest controls the required-update prompt; changing the coordinator minimum alone only blocks new leases.
4. Sign the exact manifest on the trusted signing machine with `scripts/sign_update_manifest_dpapi.py`.
5. Verify `update-manifest.sig` using the public key embedded in the worker.
6. Upload the update ZIP, manifest and signature to the GitHub Release.
7. Only after the release is fully visible may `min_worker_version` be raised for a mandatory update.

Mandatory updates are downloaded in the background and applied only between leases. Refusal finishes current work and closes safely. A failed post-update health check restores the previous frozen runtime automatically.

## Update validation

CI runs `tests/test_update_integrity.py` with an ephemeral key to reject altered signatures, payloads, sizes and repository identity, prevent downgrade prompts, and ensure a previously dismissed update is prompted again when its signed minimum makes it required.

On the signing workstation, `tests/test_frozen_update_prompts.py` exercises the actual old Windows executable and native update dialogs against the official next ZIP. It covers optional and required acceptance/refusal, unchanged contributor identity and exact post-update executable hashes. `ENIGMA_TEST_SIGNING_KEY_BLOB` selects the protected local signing key. Both official release directories must already be available as indicated in the test. `ENIGMA_TEST_UPDATE_BUSY=1` runs safe-boundary cases with active isolated jobs. The fixture proxy and certificate are scoped only to child processes; no system trust, public release or production identity is changed. Never publish its test manifests.

`tests/test_frozen_update_local.py` separately checks successful application and rollback after an intentionally inconsistent version/health check. Run these local tests before publishing a new package; they are not replaced by source-only CI.

For versioned test directories, set `ENIGMA_TEST_OLD_CANDIDATE` to the extracted previous release, `ENIGMA_TEST_CANDIDATE` to the extracted candidate, `ENIGMA_TEST_ASSET` to the candidate ZIP and `ENIGMA_TEST_TARGET_VERSION` to its version. This preserves earlier packages while testing the exact next release. The rollback test uses the candidate, asset and target-version settings; the prompt test also uses the previous release.

Run the frozen tests sequentially in a Windows user session without an active volunteer client. The worker intentionally holds a per-user singleton mutex, so concurrent fixtures interfere even with separate state directories. Do not stop a production client merely to make a fixture pass; use a separate test session if needed.

## Local package retention

This source change is prepared for a future consolidated release; the published 0.4.4 candidate does not include it.

After a new runtime passes its health check, the updater may remove recognized old download packages from the private `updates/<version>` cache. It retains the activated version, the previously running version when known, the newest older cached package, and newer or pending/staged versions. An existing rollback backup or unreadable pending metadata prevents cleanup. Unknown files, incomplete downloads, symbolic links and reparse points are preserved. Identity files and installation files are outside this cleanup.

This is conservative storage housekeeping, not an update-policy change. It does not rotate worker logs, promise a fixed cache size when recovery artifacts remain, or remove the only recovery package after a failed update. `tests/test_update_package_retention.py` checks synthetic files only.

## Key handling
The private Ed25519 release key must remain outside the repository. Normal signing decrypts it only in memory from the protected local vault; no plaintext PEM is written during normal signing.

Never put the private key, decrypted PEM, protected key blob, device/dashboard tokens, state databases, private IP addresses, or coordinator backups in GitHub, CI secrets, releases, issues, chat, or the public project directory.

## Windows code signing
The current Setup is not Authenticode-signed. If the project later obtains a trusted code-signing certificate, sign the final immutable EXE after the reproducible build and before publishing its final SHA-256. Do not replace the project's Ed25519 update-signature system with Authenticode; they protect different parts of the release chain.
