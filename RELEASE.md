# Release procedure

Windows update ZIPs are checked against the project's Ed25519-signed manifest.
GitHub artifact attestations provide build provenance only for the exact bytes
built and attested by that workflow. Android APKs use their existing Android
signing certificate and require an increasing version code for in-place updates.
Source CI, local package tests and GitHub build attestations are distinct evidence.

## Coordinated 0.5.0 candidate

Keep one versioned candidate per platform. Freeze the source tree, review the
public export and run source CI from that revision. Build the candidate
packages with the required Android signature, record their SHA-256 digests,
then test those exact package bytes in
isolated and real-device checks. For Android, verify the official application ID,
original signing certificate, increasing version code, saved identity and pending
receipts before and after an in-place installation. For Windows, verify the
installer, frozen worker, update and rollback paths with the candidate ZIP and
Setup EXE. Record the tested hashes and any untested hardware in release notes.

If a candidate passes, publish those same bytes. Do not rebuild merely to call
it final: a changed APK, ZIP or EXE is a new candidate and needs the relevant
checks again. Create and sign the Windows update manifest only after the final
ZIP hash is fixed; the manifest binds that ZIP's name, size, version, repository
and SHA-256. Publish the exact signed manifest and signature with the tested ZIP.
The Setup EXE and Android APK need their own published SHA-256 values; the
Windows update manifest does not cover them.

There are two honest provenance paths:

- If the candidate comes from the pinned GitHub release-candidate workflow,
  verify its artifact attestation, test the downloaded bytes and publish those
  same bytes. The workflow's current attestations cover its Windows ZIP and
  Setup EXE, not a separately built local package or Android APK.
- If the candidate was built locally and tested on devices, publish its digest
  and exact test results, plus the Ed25519-signed Windows update manifest and
  Android APK signature where applicable. Do not claim that source CI or an
  attestation on a different build proves provenance of those local binaries.

Do not label a package published, attested, installed or hardware-qualified
until that particular fact is independently checked. Leave coordinator policy,
administration, private configuration, databases and monitoring outside the
public source export.

## Historical first release

The repository, public endpoint and registration were established in earlier
releases. Their initial setup is complete and is not a step in a normal update.
Follow the current package, manifest, privacy and production checks above and
below for each new release; preserve the existing coordinator and volunteer
identities.

## Normal update release
1. Run source CI from the intended commit. If using the GitHub-built package,
   also run the release-candidate workflow and verify the attestation of the
   exact downloaded ZIP. A locally built ZIP has no such workflow provenance.
2. Test the exact candidate ZIP and installer to be published; record hashes.
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

The 0.5.0 source candidate includes this retention logic; historical 0.4.4
packages do not. Publishing source or rebuilding a package does not update
installed clients. Verify the exact 0.5.0 package before attributing this
behavior to a volunteer installation.

After a new runtime passes its health check, the updater may remove recognized old download packages from the private `updates/<version>` cache. It retains the activated version, the previously running version when known, the newest older cached package, and newer or pending/staged versions. An existing rollback backup or unreadable pending metadata prevents cleanup. Unknown files, incomplete downloads, symbolic links and reparse points are preserved. Identity files and installation files are outside this cleanup.

This is conservative storage housekeeping, not an update-policy change. It does not rotate worker logs, promise a fixed cache size when recovery artifacts remain, or remove the only recovery package after a failed update. `tests/test_update_package_retention.py` checks synthetic files only.

## Key handling
The private Ed25519 release key must remain outside the repository. Normal signing decrypts it only in memory from the protected local vault; no plaintext PEM is written during normal signing.

Never put the private key, decrypted PEM, protected key blob, device/dashboard tokens, state databases, private IP addresses, or coordinator backups in GitHub, CI secrets, releases, issues, chat, or the public project directory.

## Windows code signing
The current Setup is not Authenticode-signed. If the project later obtains a trusted code-signing certificate, sign the final immutable EXE after the reproducible build and before publishing its final SHA-256. Do not replace the project's Ed25519 update-signature system with Authenticode; they protect different parts of the release chain.
