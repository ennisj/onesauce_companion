# OnesaUCE Companion

OnesaUCE Companion is a desktop utility for installing, updating, and managing OnesaUCE content for AtGames Legends Ultimate and related setups.

The goal of the app is to make OnesaUCE easier to work with for non-technical users. Instead of manually downloading large archives, comparing versions, and extracting files to the correct drive structure, the app provides a guided interface for common OnesaUCE maintenance tasks.

## What It Does

OnesaUCE Companion currently supports:

- installing and updating required base components
- browsing and downloading optional system packs
- browsing and downloading BitLCD marquee packs
- browsing and downloading optional components such as themes and video packs
- queueing multiple component downloads in a specific order
- resumable downloads and configurable download retention
- automatic version detection for many installed components
- backup support for changed files during installs
- Browse Collections and Games from the catalog, and view details and related media from each.


## Requirements

- Windows x64, or an Apple Silicon Mac (M1 or newer) running macOS 13 Ventura or later, if running the binary (recommended - much easier)
- Python 3.11 or newer when running from source
- Archive.org credentials for downloads 
- A valid OnesaUCE target folder for installs and updates
- (Optional)  A valid BitLCD target folder for installs and updates

Note:  These requirements are for Companion only, separate from the requirements of OnesaUCE regarding which Legends products it will run on with what firmwares.

## Run from Windows Executable

* Download the latest OnesaUCECompanion.zip file from the Releases page
* Unzip the zip file into a folder of your choice on your PC.
* Launch the OnesaUCECompanion.exe executable

Notes:   
* The .onesauce_companion folder is expected to be found in the same folder as the OnesaUCECompanion.exe, and is required for Companion to run. 
* Therefore it's recommended you not unzip this anywhere under your Program Files or other system protected folders.

When launched for the first time, you will need to configure a few things in settings so that companion knows where to find your OnesaUCE drive and how to login to the Internet Archive.     If you don't have an Internet Archive account, companion will provide a link to a sign up page.    Internet Archive accounts are completely free.

For more details on setting up Companion and what it can do, refer to the [Documentation](DOCUMENTATION.md)


## Run on macOS

macOS builds require an **Apple Silicon Mac (M1 or newer)** running **macOS 13 (Ventura) or later**. Intel Macs are not supported.

* Download the latest `OnesaUCECompanion-macos-arm64.dmg` from the Releases page.
* Open the DMG and drag **OnesaUCECompanion** onto the **Applications** shortcut in the same window.
* Launch it from Applications (see the first-launch note below).

Because the app is not signed with a paid Apple certificate, macOS will show a security warning the **first time** you open it. This is expected, and you only need to do this once.

**On macOS 15 Sequoia and newer:**

* Double-click the app. When macOS says it can't be opened because Apple cannot verify it, click **Done** (do *not* click "Move to Trash").
* Open the **Apple menu → System Settings → Privacy & Security**.
* Scroll to the **Security** section, find the line saying *OnesaUCECompanion was blocked*, and click **Open Anyway**.
* Confirm with Touch ID or your password, then click **Open Anyway** once more. The app launches and won't ask again.

**On macOS 13 Ventura / 14 Sonoma**, you can use the quicker method instead: right-click (or Control-click) the app and choose **Open**, then **Open** again.

**If you see "the app is damaged and can't be opened",** that is the download-quarantine flag. Open the **Terminal** app, paste the line below, press Return, then open the app normally:

```bash
xattr -dr com.apple.quarantine /Applications/OnesaUCECompanion.app
```

(If you placed the app somewhere other than Applications, adjust the path.)


## Run From Python Source (Optional - For Advanced Users)

From the repo root:

```powershell
python -m pip install -r requirements.txt
onesauce-companion
```

You can also launch directly from the repo root with:

```powershell
.\run.ps1
```

or:

```bat
run.bat
```

Note:   This is a Python application, and will potentially work on non-Windows platforms, but this has not been tested and is not yet officially supported.

## Build Windows EXE

Requires Python 3.11 or 3.12. From the repo root, install the dependencies, then run the build script:

```powershell
python -m pip install -r requirements.txt
.\build_exe.ps1
```

Build output:

```text
dist\OnesaUCECompanion\OnesaUCECompanion.exe
```

Keep the full `dist\OnesaUCECompanion` folder together when distributing the EXE.

`build_exe.ps1` is a thin wrapper that runs PyInstaller against `OnesaUCECompanion.spec`; it assumes the dependencies above are already installed. Its macOS counterpart is `build_app.sh` (see [Build on macOS](#build-on-macos-from-source)).


## Build on macOS (from source)

Building the app yourself on your own Mac is the cleanest way to get a copy that macOS will not block. An app you compile locally is never tagged with the download "quarantine" flag, and PyInstaller ad-hoc signs it automatically, so it launches without any Gatekeeper prompt — no need for the steps in [Run on macOS](#run-on-macos).

Requirements: an Apple Silicon Mac (M1 or newer) on macOS 13 Ventura or later, plus the Xcode Command Line Tools (these provide `git` and `codesign`):

```bash
xcode-select --install
```

Install Python 3.11 or 3.12 (from python.org or `brew install python@3.11`), then from the repo root:

```bash
python3.11 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt
./build_app.sh
```

Build output:

```text
dist/OnesaUCECompanion.app
```

Drag `OnesaUCECompanion.app` to your Applications folder and launch it.

Notes:
* `requirements.txt` includes `pillow`, which PyInstaller uses to convert the icon to the `.icns` format macOS bundles require. For a higher-resolution icon, pre-generate `assets/onesauce_icon.icns` using the `sips`/`iconutil` commands in `.github/workflows/build.yml` before building.
* This only avoids Gatekeeper on the machine that built it. If you copy the `.app` to another Mac over the internet, that download is re-quarantined and the [Run on macOS](#run-on-macos) steps apply again.
* If you only want to run the app and not produce a bundle, [Run From Python Source](#run-from-python-source-optional---for-advanced-users) is simpler and also avoids Gatekeeper entirely.


## Licensing And Notices

This project is released under the GNU Affero General Public License v3.0.

See:
- [LICENSE](LICENSE)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [licenses/](licenses)

When publishing a binary release, make sure the release points to the corresponding public source tag or commit in this repository:
- https://github.com/ennisj/onesauce_companion


## Project Status

Current version: `v0.3.2`

[Changelog](CHANGELOG.md)
