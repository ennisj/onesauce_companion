# onesauce_updater

Unofficial installer/updater for OnesaUCE.

## Status

This repository contains a first-pass PySide6 desktop application skeleton for:

- Selecting an OnesaUCE target folder or local working folder
- Detecting installed component versions
- Downloading required base components from Archive.org
- Backing up changed files before extraction
- Installing or updating the required base components

## Run

```bash
python -m pip install -e .
onesauce-updater
```

You can also launch from the repo root with:

```powershell
.\run.ps1
```

or:

```bat
run.bat
```

## Notes

- Archive.org credentials are currently required for these downloads. Enter them in the app before installing.
- The installer compares against each component's embedded `Build v...` version when a version file exists.
- `ha8800_background` currently has no embedded version file in the sample archive, so its installed version is tracked in updater state metadata after install.
