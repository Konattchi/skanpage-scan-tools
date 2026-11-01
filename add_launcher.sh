#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Optionally point this at an EXISTING v3 custom build so you can pin it now.
BINARY="${1:-$HOME/.local/opt/skanpage-scan-tools/bin/skanpage}"
python3 "$ROOT/scripts/install_desktop.py" "$BINARY"
