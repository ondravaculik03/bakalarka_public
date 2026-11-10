Build & release

Step by step, with the signing key and troubleshooting: RELEASE_AND_SIGNING_KEY_TUTORIAL.md

1. Bump __version__ in src/__init__.py.
2. Run: python scripts/build.py
   This builds the exes directly with version+arch in the name, e.g. agent-cli-2.0.12-amd64.exe (install/update scripts match by prefix only, so this is just for clarity).
3. Run: python scripts/sign_release.py (asks for the key's passphrase)
   This writes dist/release-manifest.json (the version and each exe's SHA-256) and its signature dist/release-manifest.json.sig.
4. Create a GitHub release on ondravaculik03/bakalarka_public with a tag matching the version (e.g. 2.0.12), upload all three exes AND release-manifest.json + release-manifest.json.sig as assets.
5. Fresh install: run scripts/install.ps1 as admin, it pulls agent-service and agent-cli from the latest release, installs to Program Files\Mastiff, sets up scheduled tasks.
6. Already-installed agents self-update by checking the latest release tag against __version__ and downloading all three exes via updater.py.

From 2.0.27 on, agents refuse a release without a valid signature, a manifest version that doesn't match the tag, or an exe that doesn't match the manifest.
The signing key is created once with python scripts/create_release_signing_key.py (it prints the RELEASE_PUBLIC_KEY line for src/updater.py).
Keep the key file (%USERPROFILE%\.mastiff\release_signing_key.pem) and its passphrase backed up: a lost key means reinstalling every machine.

CLI usage

agent-cli status - show current config
agent-cli set <key> <value> - key is server_url or auth_token (applies at the agent's next run)
agent-cli check-update [--auto] - check for new version
agent-cli update - update to latest version
agent-cli --version - show version
