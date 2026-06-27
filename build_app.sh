#!/usr/bin/env bash
# Build the macOS .app bundle. The terminal analog of build_exe.ps1 on Windows.
#
# Run it with the project environment active and dependencies installed:
#     python3.11 -m venv .venv && source .venv/bin/activate
#     pip install -r requirements.txt
#     ./build_app.sh
set -euo pipefail

# Run from the repo root (this script's directory) regardless of where it is called from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

python -m PyInstaller --noconfirm --clean OnesaUCECompanion.spec

echo ""
echo "Built app bundle:"
echo "  $SCRIPT_DIR/dist/OnesaUCECompanion.app"
