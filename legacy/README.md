# Preserved legacy deployment sources

These are the necessary safety updates to existing local maiocha tools. Original entrypoints and all content remain in their existing workspace directories.

`install-manifest.json` records each destination and its original SHA-256. `../safety/Install-LegacySafety.ps1` checks preimages, backs up changed tools under the workspace `.local/`, and installs these sources in place. Unknown local changes are rejected. `-VerifyOnly` checks byte equality without writing.

The source of truth for these safety updates is this directory; installed files are deployment copies, not an independent implementation. Shared boundaries live in `safety/HostingSafety.ps1` and policy in `config/hosting-scopes.json`. Never copy credentials, private manifests, approval records, photos, or `.env` here.

The original eight-case state-machine regression script is retained unchanged as a test fixture under `safety/tests/fixtures/`.
