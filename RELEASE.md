# Release procedure

Release updates use two independent trust layers: GitHub build provenance and the project Ed25519 release signature.

## Normal release
1. Run CI and the `Build release candidate` workflow from the intended commit.
2. Download `enigma-volunteer-windows.zip` and verify its GitHub artifact attestation.
3. Create the signed metadata locally with `scripts/create_update_manifest.py`, specifying the final `OWNER/REPOSITORY`, semantic version and release notes.
4. Move only `update-manifest.json` to the Surface signing machine.
5. On Surface, sign the exact manifest bytes with the private Ed25519 key. The private key never leaves Surface and is never uploaded to GitHub or Lenovo.
6. Copy only `update-manifest.sig` back and verify it using the embedded public key before publication.
7. Create the GitHub Release and upload exactly three update assets: `enigma-volunteer-windows.zip`, `update-manifest.json`, and `update-manifest.sig`.
8. After the release is fully visible, set `github_repo` in the Lenovo server config. Existing clients learn the repo from `/api/public/config`; the repo location itself is not trusted for code execution because the manifest signature remains mandatory.

## Mandatory security release
Set `mandatory=true` in the signed manifest. If old clients must stop receiving work, publish and verify the release first, then raise `min_worker_version` on the coordinator.

An old worker then receives no new lease and immediately checks for an update. Accepting downloads the signed update in the background; installation occurs between leases. Refusing a mandatory update finishes current work and closes safely.

Never raise `min_worker_version` before the signed release assets are publicly available.

## Key handling
The release-signing private key is stored only on the Surface under the user's protected signing directory. A compromise of GitHub or the Lenovo coordinator does not by itself provide signing authority.

Do not copy the private key into the repository, a release, cloud CI secrets, chat, email, or the Lenovo server.
