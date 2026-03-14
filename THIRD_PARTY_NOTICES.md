# Third-Party Notices

OnesaUCE Companion includes or depends on third-party software. This document summarizes the primary third-party libraries used by the project and where to find their license terms.

## Project License

OnesaUCE Companion is distributed under the GNU Affero General Public License v3.0. See [LICENSE](LICENSE) and [licenses/AGPL-3.0.txt](licenses/AGPL-3.0.txt).

Source repository for released builds:
- https://github.com/ennisj/onesauce_companion

## Runtime Dependencies

### internetarchive
- Version: 5.8.0
- Purpose: Archive.org authentication and download integration
- License: AGPL-3.0
- Project: https://github.com/jjjake/internetarchive
- License text: [licenses/AGPL-3.0.txt](licenses/AGPL-3.0.txt)

### PySide6
- Version: 6.9.2
- Purpose: Desktop UI framework
- License: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only
- Project: https://pyside.org
- License text: [licenses/LGPL-3.0.txt](licenses/LGPL-3.0.txt)

### shiboken6 / PySide6_Essentials / PySide6_Addons
- Version: 6.9.2
- Purpose: Qt for Python runtime components bundled with PySide6
- License: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only
- Project: https://pyside.org
- License text: [licenses/LGPL-3.0.txt](licenses/LGPL-3.0.txt)

### requests
- Version: 2.32.3
- Purpose: HTTP client functionality used by the application and supporting libraries
- License: Apache-2.0
- Project: https://requests.readthedocs.io
- License text: [licenses/Apache-2.0.txt](licenses/Apache-2.0.txt)

### keyring
- Version: 25.7.0
- Purpose: OS credential storage for Archive.org password handling
- License: MIT
- Project: https://github.com/jaraco/keyring
- License text: [licenses/MIT.txt](licenses/MIT.txt)

## Build / Packaging Dependency

### PyInstaller
- Version: 6.16.0
- Purpose: Windows application packaging
- License: GPLv2-or-later with PyInstaller bootloader exception
- Project: https://pyinstaller.org
- License text: [licenses/PyInstaller-License.txt](licenses/PyInstaller-License.txt)

## Release Correspondence

Public binary releases should be tied to a corresponding public source tag or commit in the repository above. The recommended release process is:
- tag the source commit for the release
- build the Windows package from that tag
- publish the binary together with a link to the corresponding source tag

## Notes

This document is intended to help with release packaging and notice distribution. It is not legal advice.
