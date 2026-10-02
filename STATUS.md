# Status — 2026-10-02

## Local release candidate
- Coordinator v0.3 remains bound to `127.0.0.1:8765` on Lenovo.
- Windows client version: `0.3.0`.
- Global campaign `p1030680-global-v1` remains `prepared`, not activated.
- No GitHub remote exists and nothing has been published.
- Public bootstrap hostname is embedded in `worker/release_config.json`; no private coordinator IP is shipped.

## Product state
- Branded Windows Setup, tray application, worker and updater are built as standalone executables.
- First-run onboarding no longer asks volunteers for a server URL.
- CPU/GPU percentages, pause/resume, safe stop, autostart, update checks, global/personal stats and hardware detection are exposed in the tray UI.
- Public dashboard has been redesigned for responsive production use and contains no analytics or third-party frontend dependencies.
- MIT license, privacy policy, security policy, contributor guide and GitHub templates are present.
- Legacy PowerShell volunteer installer/uninstaller has been removed.

## Validation completed
- Source compile and JavaScript syntax checks: PASS.
- Consensus and quarantine suites: PASS.
- Security suite: PASS.
- HTTP integration suite: PASS.
- Public-surface exposure test: PASS.
- Frozen real solver validation: PASS (`done=1`, `submissions=2`, `credits=2`).
- Installer lifecycle: PASS, including payload hash equality, registry/autostart, purge uninstall, install-directory removal and temporary helper cleanup.
- Signed frozen update: PASS.
- Deliberately broken update rollback: PASS (`rollback_rc=4`).
- `pip-audit`: no known dependency vulnerabilities.
- Bandit: 0 medium / 0 high findings.
- Microsoft Defender: no threats detected in Setup or runtime directory.
- Repository secret/private-address scan: no credentials, private user paths or real Tailscale device IPs detected.

## Final local artifact hashes
- Update ZIP: 121,971,445 bytes; SHA-256 `C3C359E2C9252401163E7E5379E2A7964EDBA2ECA4C9DA50302188AC7CE091DE`.
- Setup EXE: 132,311,135 bytes; SHA-256 `B610B60C52C08E6A4E41CFBB43A628E3CF7A484C8C5AB8983F7CBB38C68762DE`.

## External launch gate
Tailscale itself reports that Funnel is not enabled for the tailnet and requires account approval. The coordinator remains non-public until that action is completed. After approval, Funnel should proxy only the loopback coordinator on port 8765 and the public surface must be rechecked before registration is opened.

## Known release caveat
`EnigmaGridSetup.exe` is currently `NotSigned` under Windows Authenticode because the project has no paid code-signing certificate. Early downloads may trigger a SmartScreen/Unknown Publisher warning. GitHub artifact attestation, published SHA-256 hashes and the project's Ed25519-signed update chain remain available as integrity/provenance controls.
