# Release procedure

Release updates use two independent trust layers: GitHub build provenance and the project Ed25519 release signature.

## Normal release
1. Run CI and the Build release candidate workflow from the intended commit.
2. Download enigma-volunteer-windows.zip and verify its GitHub artifact attestation.
3. Create update-manifest.json locally with scripts/create_update_manifest.py, specifying the final OWNER/REPOSITORY, semantic version and release notes.
4. Sign the exact manifest on Lenovo with scripts/sign_update_manifest_dpapi.py. The signer decrypts the private key only in memory from the ACL-restricted DPAPI blob.
5. Verify update-manifest.sig using the public key embedded in the worker before publication.
6. Create the GitHub Release and upload exactly three update assets: enigma-volunteer-windows.zip, update-manifest.json, and update-manifest.sig.
7. After the release is fully visible, set github_repo in the Lenovo server config. Clients learn it through /api/public/config.

## Mandatory security release
Set mandatory=true in the signed manifest. If old clients must stop receiving work, publish and verify the release first, then raise min_worker_version on the coordinator.

An old worker then receives no new lease and immediately checks for an update. Accepting downloads the signed update in the background; installation occurs between leases. Refusing a mandatory update finishes current work and closes safely.

Never raise min_worker_version before the signed release assets are publicly available.

## Key handling
The private Ed25519 release key is stored outside the repository in an ACL-restricted DPAPI CurrentUser blob on Lenovo. Signing decrypts it in memory; no plaintext PEM is written during normal signing.

This protects against accidental repository/CI disclosure and offline theft of the blob. It does not provide full separation from a compromise that already executes as the Lenovo signing user. Before a large public rollout, prefer a separate signing identity or offline/removable signing device if practical.

Never put the private key, decrypted PEM, or DPAPI blob in GitHub, CI secrets, releases, chat, email, or the public project directory.
