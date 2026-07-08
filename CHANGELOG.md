# v0.4.0

**Cabinet Link: install to the cabinet over your network**

Companion can now pair directly with a cabinet running One Saucier (v0.1.0 or later) and install components on it over the local network — no more shuttling the drive back and forth for updates.

* feat: New Cabinet Link section in Settings: discover the cabinet on your LAN (or enter its IP), pair with a PIN shown on the cabinet screen, and unlink at any time. The link token is stored in the system keyring.
* feat: The Downloads screen gains Local and Cabinet column groups. The Cabinet columns show each component's installed version and status on the paired cabinet (Up-to-Date / Update Available / Not Installed), or "Not Connected" when no cabinet is paired.
* feat: Transfer to Cabinet: a new per-row action sends a downloaded component to the cabinet, which verifies (MD5) and installs it through its own pipeline. Live progress shows in both column groups — "Sending to Cabinet" locally and "Receiving" then "Installing on Cabinet" on the cabinet side — with lifecycle entries in the Download Log.
* feat: Companion keeps cabinet status current automatically: it polls the exact component after a transfer completes and refreshes the full snapshot periodically while the Downloads screen is visible.
* feat: Companion now works without the OnesaUCE drive attached. Downloads (and cabinet transfers) only require a valid Downloads folder; if the install folder is unset or points at an unplugged drive, downloads complete without installing, the Install action is disabled, and the affected columns read "No Folder".
* feat: Auto-update for the packaged app. When a newer release is available, the sidebar note becomes "Update to vX.Y.Z — click to install": Companion downloads the release, then restarts to apply it (Windows). On macOS it downloads and opens the DMG to finish the drag-install. From-source installs keep the link to the releases page.
* feat: Settings reorganized: the install targets and Downloads folder now live together under "Local Folders" ("OnesaUCE Drive or Install Folder", "BitLCD Drive or Install Folder"), with Cabinet Link directly below.
* feat: Downloads screen layout refresh: Size moved next to Component, the Download/Install actions moved inline into the Downloaded/Installed columns, and shortened "Not downloaded"/"Not installed" to "N/A".
* fix: The Downloaded column no longer intermittently shows N/A for components that are present in the downloads cache (the cached version index was being cleared on every settings save).
* fix: Retention cleanup no longer errors at startup when the Downloads folder points at an unavailable drive.
* chore: One more fruit on the sidebar. Waka waka.

# v0.3.2

**Robustness, Performance, and macOS Support**

* fix: Companion now recovers from a corrupt settings.json or state.json instead of failing to launch. The corrupt settings file is set aside as settings.json.corrupt, defaults are loaded, and the stored Archive.org password is kept.
* fix: Clearing the Archive.org password in Settings now removes the stored password from the system keyring.
* fix: Downloads are validated against their expected size; a download that ends early now resumes on retry instead of being treated as complete.
* fix: Reading OnesaUCE settings no longer silently rewrites settings.conf. The required firstCollection=Main repair still happens, but it is now reported in the status bar and log.
* feat: Check available disk space before downloading and before installing, with a clear message showing how much space is needed.
* feat: Show a status bar warning when archive.org cannot be reached during catalog refresh, instead of silently showing older data.
* feat: Support Windows long paths during installs, so deep ROM and media folder trees extract correctly without the system-wide long-path setting.
* feat: macOS support. Companion now runs on Apple Silicon Macs (macOS 13 Ventura or later) and can be packaged as a native `.app`, distributed in a drag-to-Applications DMG alongside the Windows build. The README adds macOS install steps, first-launch Gatekeeper guidance, and build-from-source instructions.
* perf: Validate archive entries without resolving every path on disk, reducing per-file overhead when preparing and extracting large packs.
* perf: Cache archive version inspection so downloads-cache maintenance no longer re-opens every cached zip for every component.
* chore: Rename the OnesaUCE-section "Settings" navigation button to "OnesaUCE Settings" to distinguish it from Companion Settings.
* chore: Add ruff and mypy configuration and a GitHub Actions CI workflow (lint plus tests on Windows); fix all findings.
* chore: Add a packaged-app build workflow (GitHub Actions) that builds Windows and macOS downloads on demand or when a version tag is pushed, and drafts a GitHub Release with both attached for review before publishing.
* chore: Add a `requirements.txt` for from-source installs and a `build_app.sh` macOS build script (the counterpart to `build_exe.ps1`), keeping the dependency list defined once in `pyproject.toml`.
* chore: Continue extracting controllers from the main window (Downloads, Themes) and move the detail screens, media helpers, and background-worker lifecycle into dedicated modules.

# v0.3.1

**Performance and Bugfix Release**

* feat: Add segmented download controls to Companion Settings for large Internet Archive downloads, including enable/disable, minimum archive size, and segments per archive.
* perf: Improve Internet Archive download throughput by supporting ranged segmented downloads for large archives, increasing download chunk size, reducing progress callback overhead, and avoiding per-chunk disk flushes.
* perf: Reuse Archive.org authentication and metadata across concurrent downloads, and scan the downloads cache once per queue run instead of once per component.
* fix: Give the Downloads screen Status column more room so active progress bars are not clipped.

# v0.3.0

**Feature Release**

* feat: New Downloader screen consolidates Base Components, System Packs, BitLCD Marquees, Optional Components, and the Queue into a single filterable hub with batch and per-component actions.   Separated the download and install actions so they are no longer forced to happen together.    Components can be re-downloaded to update the download cache.    Components can be re-installed.
* feat: Add "Auto-install components after download" setting.    This is enabled by default, keeping the current behavior of automatically installing updates as soon as they are downloaded.     Disabling it will require manual installation.
* feat: New Themes screen for previewing theme layouts. Enable this using the "Enable Themes Preview" checkbox in Settings.   Note:  This is still in preview and will have bugs.   It will not give a 100% accurate representation of the theme, but it is reasonably close.
* feat: Game Details and Collection Details now render as integrated screens with a Back button, replacing the previous separate dialog windows.
* feat: Logs screen adds a "Reverse Order" checkbox (default on) to display newest log entries first.    For log files over 2MB, they will be partially loaded with an added button to load the entire file.
* perf: Catalog refresh, installed-component scan, remote-size lookup, theme catalog scan, and log loading all run on background threads. The UI no longer freezes during these operations.
* perf: Lazy-build screens on first navigation. Companion launches noticeably faster, especially on slower systems.
* perf: Optimize the log syntax highlighter to eliminate catastrophic regex backtracking; Companion logs in particular open significantly faster.
* chore: Progress bar at the bottom of the screen reports background activity (catalog refresh, theme scan, log loading, etc.).

# v0.2.2
** Bugfix Release**

* fix:  Correct detection of Daphne System Pack version
* fix:  Correct detection of Simple Blue Optional Theme Component
* fix:  Use download cache when available
* fix:  Corrected game counts and filtering for multi-system collections 
* feat:  Add downloaded column to Install screens to show downloaded version
* feat:  Update UI to improve useable space
* chore:  Add firmware version warning to OnesaUCE settings screen.
* chore:  Refactor main window class

# v0.2.1

**Bugfix Release**

* fix: Remove the OnesaUCE Starting Collection setting from Companion.
* fix: Automatically force OnesaUCE `firstCollection` to `Main`.    This setting actually represents the top level collection, not the starting collection.

# v.0.2.0

**Feature Release**

* feat: Add Collections screen for browsing collections and their related media.
* feat: Add Logs screen for viewing the Companion log file and the log files from OnesaUCE
* feat: Add Settings screen for adjusting various settings in OnesaUCE, including the ability to enable or disable Autostart

# v0.1.2

**Bugfix Release**

* fix: Correct detection of the latest appdata component version
* fix: Improve detection of Optional Components
* feat: Add check if a newer version of Companion is available

# v0.1.1

Bugfix Release

fix: Correct detection of the latest Arcade System Pack version

# v0.1.0

**Initial Public Release**
