# Releasing the agent with a signed manifest

Installed agents update themselves from the latest GitHub release of
`ondravaculik03/bakalarka_public`. From 2.0.27 on they only accept a release you signed: the
release carries `release-manifest.json` (the version and the SHA-256 of each exe) and
`release-manifest.json.sig` (its signature, made with your private key). The agent checks the
signature with the public key built into `src/updater.py`, then the version, then every exe, and
only then installs. Anything wrong = nothing runs, and the agent log says why.

Two keys, don't mix them up:
- **private key**: `%USERPROFILE%\.mastiff\release_signing_key.pem`, protected by a passphrase. Only
  on your computer (plus a backup). Never in the repo, never on the server.
- **public key**: the `RELEASE_PUBLIC_KEY` line in `src/updater.py`. Not secret, it's committed.

All commands run in PowerShell from the `agent_windows` folder.

## Once: create the key

Do this before the first signed release (2.0.27), and never again unless the key is lost or stolen.

### 1. Create the key

```powershell
python scripts/create_release_signing_key.py
```

Type a passphrase twice. The script writes the private key and prints a line like:

```
RELEASE_PUBLIC_KEY = "<your key, 44 characters ending with =>"
```

It refuses to overwrite a key that already exists.

### 2. Put the public key into the agent

In `src/updater.py`, replace the line `RELEASE_PUBLIC_KEY = "PASTE_FROM_create_release_signing_key.py"`
with the printed line.

`sign_release.py` refuses to sign while this line is the placeholder or another key's.

### 3. Back up the key

Save the passphrase in your password manager and copy `release_signing_key.pem` to a second place
(USB stick, password manager attachment). The file is encrypted with the passphrase, so the copy is
safe on its own.

### 4. Commit

Commit `src/updater.py` with the key line. The `.pem` file is outside the repo, so it can't be
committed by accident.

## Every release

### 1. Raise the version

In `src/__init__.py` raise `__version__` (e.g. `2.0.27` -> `2.0.28`). Agents only update to a
higher version.

### 2. Build

```powershell
python scripts/build.py
```

`dist/` now has the three exes, e.g. `agent-service-2.0.28-amd64.exe`.

### 3. Sign

```powershell
python scripts/sign_release.py
```

Type the passphrase. `dist/` now also has `release-manifest.json` and `release-manifest.json.sig`.
Don't change any file in `dist/` after this - a changed exe no longer matches the manifest.

### 4. Publish the GitHub release

On GitHub: **Releases -> Draft a new release**.
- Tag: the version, e.g. `2.0.28` (must match the manifest exactly).
- Upload **5 files**: the three exes, `release-manifest.json` and `release-manifest.json.sig`.
- **Publish release** - not a draft and not a pre-release, agents only look at the latest published
  release.

### 5. Check one machine

The agent checks for updates every time it runs (at start-up and every hour). To check right away,
on the machine as admin:

```powershell
schtasks /run /tn MonitoringAgentHourly
```

Then look at `C:\ProgramData\Mastiff\agent_info.log`:
- `New exe files downloaded to: C:\Program Files\Mastiff\update` - the update passed the checks.
- after a minute `agent-cli --version` shows the new version.
- `Update refused: ...` - see Troubleshooting.

## The first signed release (2.0.27)

Machines on 2.0.26 don't check signatures yet, so they install 2.0.27 the old way, one last time.
From 2.0.27 on every update is checked. Do the "Once" part first, then a normal release, and check
one machine (step 5) - that's the first time the new update folder and the new updater run for real.

## Troubleshooting

| In the agent log | Cause | What to do |
|---|---|---|
| `The release has no release-manifest.json.sig.` (or `.json`) | the manifest files weren't uploaded | edit the release, upload both files |
| `Update refused: the release signature is not valid.` | the manifest was signed with another key, changed after signing, or `RELEASE_PUBLIC_KEY` is wrong / still the placeholder | sign again with the right key and re-upload; check the key line in `src/updater.py` |
| `Update refused: the signed version ... doesn't match the release ...` | the tag isn't the version you built and signed | fix the tag, or rebuild and re-sign with the right `__version__` |
| `Update refused: agent-cli.exe doesn't match the signed manifest.` | an exe was rebuilt or replaced after signing | run `sign_release.py` again and re-upload all 5 files |
| `Update failed: ...` | download error, no network, or the agent can't write to `Program Files\Mastiff` | usually fixes itself at the next run; a manual `agent-cli update` must run as admin |

`sign_release.py` itself stops when an exe of the current version is missing in `dist/` (build
first), when the passphrase is wrong, or when the key doesn't match `RELEASE_PUBLIC_KEY` in
`src/updater.py` (fix the line, build again, sign again).

## If the key is lost or stolen

- **Lost** (no file or no passphrase): agents can't be updated any more. Create a new key, put its
  line into `src/updater.py`, release, and reinstall the agent on every machine with
  `scripts/install.ps1`.
- **Stolen** (someone has the file and the passphrase): they can publish updates that agents accept.
  Same steps as lost, as fast as possible, and check who has access to the GitHub repo.

## Proving it works (optional, e.g. for the thesis)

On a lab machine already on the signed version: make a test release with a higher tag and upload a
wrong `release-manifest.json.sig` (e.g. the one from an older release). Run step 5 - the log must
say `Update refused: the release signature is not valid.` and the version must stay the same.
**Delete the test release right after** - while it's the latest release, every agent refuses it and
none of them gets real updates.

## Limit

The first install (`scripts/install.ps1`) is not checked: the script itself comes from GitHub, so it
trusts GitHub and HTTPS. The signature protects every update after it.
