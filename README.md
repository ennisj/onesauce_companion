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

- Windows x64 if running the binary (recommended - much easier)
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


## Run From Python Source (Optional - For Advanced Users)

From the repo root:

```powershell
python -m pip install -e .
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

From the repo root:

```powershell
.\build_exe.ps1
```

Build output:

```text
dist\OnesaUCECompanion\OnesaUCECompanion.exe
```

Keep the full `dist\OnesaUCECompanion` folder together when distributing the EXE.


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
