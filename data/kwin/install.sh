#!/bin/bash
# Install the input-remapper KWin script locally for the current user.
#
# This script is designed for Plasma 6 / KWin Wayland.
#
# Usage:
#   bash data/kwin/install.sh
#
# This copies the script to ~/.local/share/kwin/scripts/ so that
# KWin can discover it.
#
# To enable:
#   System Settings → Window Management → KWin Scripts
#   → find "input-remapper Window Daemon Client" and check the box
#
# You may need to log out and back in (or restart the Plasma session)
# for the script to load. On Wayland there is no safe way to hot-reload
# KWin scripts from the command line without restarting the compositor.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")/inputremapper-windowd" && pwd)"
DEST_DIR="${HOME}/.local/share/kwin/scripts/inputremapper-windowd"

echo "Installing KWin script from ${SRC_DIR} to ${DEST_DIR}"

mkdir -p "${DEST_DIR}/contents/code"

cp "${SRC_DIR}/metadata.json" "${DEST_DIR}/"
cp "${SRC_DIR}/contents/code/main.js" "${DEST_DIR}/contents/code/"

echo "Installation complete."
echo "To enable: System Settings → Window Management → KWin Scripts"
echo "and check \"input-remapper Window Daemon Client\"."
echo "After enabling, log out and back in to restart the Plasma session."
