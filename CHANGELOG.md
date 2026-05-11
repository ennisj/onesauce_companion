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
