#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Build KDE Skanpage 26.08.2 from upstream, apply our patch, and install to HOME.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${SKANPAGE_SCAN_TOOLS_PREFIX:-$HOME/.local/opt/skanpage-scan-tools}"
APPDATA="${XDG_DATA_HOME:-$HOME/.local/share}/skanpage-card-tools"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}"
mkdir -p "$CACHE"
WORK="$(mktemp -d "$CACHE/skanpage-scan-tools-build-XXXXXXXX")"
JOBS="${SKANPAGE_SCAN_TOOLS_JOBS:-4}"
trap 'echo "Build workspace: $WORK"' EXIT

for exe in git cmake ninja python3 c++; do
    if ! command -v "$exe" >/dev/null; then
        echo "Missing required executable: $exe" >&2
        exit 1
    fi
done
python3 -c 'import cv2, numpy, PIL' || {
    echo 'Missing Python packages: install python-opencv, python-numpy, python-pillow on Arch.' >&2
    exit 1
}

printf '\n==> Fetching official Skanpage 26.08.2 source\n'
git clone --depth 1 --branch v26.08.2 https://invent.kde.org/utilities/skanpage.git "$WORK/src"

printf '\n==> Applying custom Descreen and Stripe Repair source changes\n'
python3 "$ROOT/scripts/apply_patches.py" "$WORK/src"

printf '\n==> Configuring and compiling (parallel jobs: %s)\n' "$JOBS"
cmake -S "$WORK/src" -B "$WORK/build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX"
cmake --build "$WORK/build" -j "$JOBS"

printf '\n==> Installing into %s\n' "$PREFIX"
cmake --install "$WORK/build"

printf '\n==> Installing the scan processing helpers\n'
mkdir -p "$APPDATA"
for script in scan_descreen.py card_stripe_repair.py; do
    if [[ -f "$APPDATA/$script" ]] && ! cmp -s "$ROOT/helpers/$script" "$APPDATA/$script"; then
        cp -p "$APPDATA/$script" "$APPDATA/$script.before-release-0.1.0"
    fi
    install -m 644 "$ROOT/helpers/$script" "$APPDATA/$script"
done

printf '\n==> Adding KDE Plasma application launcher\n'
python3 "$ROOT/scripts/install_desktop.py" "$PREFIX/bin/skanpage"

printf '\nInstallation completed successfully.\n'
printf 'Launch in Plasma: search for "Skanpage Scan Tools".\n'
printf 'Executable: %s/bin/skanpage\n' "$PREFIX"
