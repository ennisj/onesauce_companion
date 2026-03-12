# onesauce_companion

A companion application designed to work with OnesaUCE for the AtGames Legends series of devices.

## Status

v0.1 Initial Release

## Run

```bash
python -m pip install -e .
onesauce-companion
```

You can also launch from the repo root with:

```powershell
.\run.ps1
```

or:

```bat
run.bat
```

## Build Windows EXE

From the repo root:

```powershell
.\build_exe.ps1
```

Build output:

```text
dist\OnesaUCECompanion\OnesaUCECompanion.exe
```

## Notes

- Archive.org credentials are currently required for these downloads. Enter them in the app before installing.
- The installer compares against each component's embedded `Build v...` version when a version file exists.
- `ha8800_background` currently has no embedded version file in the sample archive, so its installed version is tracked in updater state metadata after install.
- The internal Python package is now `onesauce_companion`.
- The app now reads legacy settings/state/download-cache locations during the transition.

