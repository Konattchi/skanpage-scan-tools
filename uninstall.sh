#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Uninstall the default user-local custom build without changing the KDE system app.
set -euo pipefail
PREFIX="${SKANPAGE_SCAN_TOOLS_PREFIX:-$HOME/.local/opt/skanpage-scan-tools}"
LAUNCHER="${XDG_DATA_HOME:-$HOME/.local/share}/applications/skanpage-scan-tools.desktop"
if [[ -d "$PREFIX" ]]; then
  rm -rf -- "$PREFIX"
  echo "Deleted custom prefix $PREFIX"
fi
if [[ -f "$LAUNCHER" ]]; then
  rm -f -- "$LAUNCHER"
  echo "Removed KDE launcher $LAUNCHER"
fi
# Do not delete shared Python helpers: an older custom build might still use them.
if command -v kbuildsycoca6 >/dev/null; then kbuildsycoca6 --noincremental || true; fi
printf 'Custom application removed. Stock KDE Skanpage is unchanged.\n'
