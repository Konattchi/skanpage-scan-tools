#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Create a distinct, user-local KDE application menu entry for Skanpage Scan Tools."""
import argparse
from pathlib import Path
import os
import shutil
import subprocess

DESKTOP_NAME = 'skanpage-scan-tools.desktop'


def write_launcher(binary: Path, target_dir: Path) -> Path:
    binary = binary.expanduser().resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError(f'Executable not found: {binary}')
    # Desktop entries quote an Exec argument with double quotes when necessary.
    escaped = str(binary).replace('\\', '\\\\').replace('"', '\\"')
    content = f"""[Desktop Entry]
Type=Application
Version=1.0
Name=Skanpage Scan Tools
GenericName=Document Scanner
Comment=Unofficial Skanpage with adjustable descreening and two-scan stripe repair
Exec="{escaped}"
Icon=skanpage
Terminal=false
StartupNotify=true
Categories=Graphics;Scanning;Qt;KDE;
Keywords=Scanner;Scan;Descreen;Stripe;Repair;Skanpage;
"""
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / DESKTOP_NAME
    path.write_text(content, encoding='utf-8')
    path.chmod(0o644)
    # Make Plasma refresh its application menu if the program is available.
    sycoca = shutil.which('kbuildsycoca6')
    if sycoca:
        subprocess.run([sycoca, '--noincremental'], check=False)
    return path


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('binary', type=Path, help='Full path to the compiled skanpage executable')
    args = cli.parse_args()
    data_home = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    path = write_launcher(args.binary, data_home / 'applications')
    print(f'Installed application entry: {path}')
    print('In Plasma Application Launcher, search "Skanpage Scan Tools" and Add to Favorites.')

if __name__ == '__main__':
    main()
