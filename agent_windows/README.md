Build & release

1. Bump __version__ in src/__init__.py.
2. Run: python scripts/build.py
   This builds the exes directly with version+arch in the name, e.g. agent-cli-2.0.12-amd64.exe (install/update scripts match by prefix only, so this is just for clarity).
3. Create a GitHub release on ondravaculik03/bakalarka_public with a tag matching the version (e.g. 2.0.12), upload all three exes as assets.
4. Fresh install: run scripts/install.ps1 as admin, it pulls agent-service and agent-cli from the latest release, installs to Program Files\Mastiff, sets up scheduled tasks.
5. Already-installed agents self-update by checking the latest release tag against __version__ and downloading all three exes via updater.py.

CLI usage

agent-cli status - show current config
agent-cli set <key> <value> - key is server_url, interval_seconds, log_level or auth_token (restart service after)
agent-cli check-update [--auto] - check for new version
agent-cli update - update to latest version
agent-cli --version - show version
