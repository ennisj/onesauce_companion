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
- a searchable Games browser built from the installed OnesaUCE catalog
- a Game Details screen for viewing story and media assets for installed games

## Main Screens

### Settings

Configure:

- OnesaUCE target folder 
- BitLCD target folder (Optional)
- Archive.org credentials
- download cache location and retention policy
- parallel download count
- whether saved downloads should automatically resume on startup

The OnesaUCE target folder can be on a local hard drive on your Windows machine, or you can set it to the drive letter of your OnesaUCE drive.
The BitLCD target folder can be on a local hard drive on your windows machine, or you can set it to the drive letter of your BitLCD thumb drive.

### Base Components

Install or update the required core OnesaUCE packages.

### System Packs

Browse and download optional system packs.

### BitLCD Marquees

Browse and install BitLCD marquee packs to a BitLCD target folder.

### Optional Components

Install optional items such as themes and jukebox add-ons.

### Queue

Review the current download/install queue, pause processing, and manage queue order.

### Games

Browse indexed games from installed content, filter and sort the catalog, and inspect media/details for a specific title.


## Requirements

- Windows is the primary target environment for the current release
- Python 3.11 or newer when running from source
- Archive.org credentials for downloads that require authentication
- A valid OnesaUCE target folder for installs and scans

## Run From Source

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

## Current Notes

- Archive.org is the only download source currently enabled in the app.
- The app can resume saved queue entries on later launches if download auto-resume is enabled.
- Some version checks rely on embedded version files, while others use folder naming or updater state depending on how that content is distributed.
- The app still reads legacy settings and cache locations from older OnesaUCE Updater installs when present.

## Project Status

Current version: `v0.1` (RC1)

This release is focused on the first usable desktop workflow for managing OnesaUCE content. Additional download sources and broader install workflows can be added later as the project evolves.
