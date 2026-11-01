#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Apply the proven v1 -> v2 -> v3 source transformations to a clean v26.08.2 checkout.

The intermediate stages are intentional: this reproduces the code previously
compiled and tested in Skanpage 26.08.2 rather than targeting unreleased KDE code.
If any step fails, restore the exact original source files.
"""

from pathlib import Path
import argparse
import shutil
import subprocess
import sys
from patch_v1 import main as patch_v1
from patch_v2 import main as patch_v2
from patch_v3 import upgrade as patch_v3

FILES = ["src/Skanpage.h", "src/Skanpage.cpp", "src/qml/DocumentPage.qml",
         "src/qml/OptionsPanel.qml", "src/main.cpp"]


def once(contents: str, original: str, replacement: str, file: str) -> str:
    count = contents.count(original)
    if count != 1:
        raise RuntimeError(f"{file}: expected exactly one source anchor, found {count}")
    return contents.replace(original, replacement, 1)


def patch(root: Path) -> None:
    root = root.expanduser().resolve()
    if not (root / "CMakeLists.txt").is_file():
        raise RuntimeError("Not a Skanpage source checkout")
    cmake = (root / "CMakeLists.txt").read_text()
    if not all(x in cmake for x in ('RELEASE_SERVICE_VERSION_MAJOR "26"',
                                     'RELEASE_SERVICE_VERSION_MINOR "08"',
                                     'RELEASE_SERVICE_VERSION_MICRO "2"')):
        raise RuntimeError("Only Skanpage release 26.08.2 is supported")
    files = {name: (root / name).read_bytes() for name in FILES}
    backup_dirs = [root / '.scan_tools_v2_backup', root / '.scan_tools_v3_backup']
    if any(p.exists() for p in backup_dirs):
        raise RuntimeError("Previously modified source detected; start from a fresh clone")

    try:
        patch_v1(root)
        cpp = root / 'src/Skanpage.cpp'
        content = cpp.read_text(encoding='utf-8')
        content = once(content, '#include "moc_Skanpage.cpp"',
            'void Skanpage::signalErrorMessage(const QString &text)\n'
            '{\n'
            '    showUserMessage(SkanpageUtils::ErrorMessage, text);\n'
            '}\n\n'
            '#include "moc_Skanpage.cpp"', 'Skanpage.cpp')
        if content.count('#include "moc_Skanpage.cpp"') != 1:
            raise RuntimeError('Invalid moc_Skanpage.cpp include after patch')
        cpp.write_text(content, encoding='utf-8')
        patch_v2(root)
        patch_v3(root)
        if (root / 'src/Skanpage.cpp').read_text(encoding='utf-8').count('#include "moc_Skanpage.cpp"') != 1:
            raise RuntimeError('Missing or malformed moc_Skanpage.cpp include after v3 patch')

        # Distinct Wayland desktop app-ID for an independent Plasma launcher.
        main = root / 'src/main.cpp'
        content = main.read_text(encoding='utf-8')
        content = once(content,
            '    KAboutData::setApplicationData(aboutData);\n',
            '    KAboutData::setApplicationData(aboutData);\n'
            '    QGuiApplication::setDesktopFileName(QStringLiteral("skanpage-scan-tools"));\n',
            'main.cpp')
        main.write_text(content, encoding='utf-8')
    except Exception:
        for name, data in files.items():
            (root / name).write_bytes(data)
        for b in backup_dirs:
            if b.exists(): shutil.rmtree(b)
        raise
    else:
        for b in backup_dirs:
            if b.exists(): shutil.rmtree(b)
        print('SUCCESS: Skanpage 26.08.2 patched; Descreen defaults to 70%.')
        print('Changes:', ', '.join(FILES))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('source', type=Path)
    args = cli.parse_args()
    patch(args.source)

if __name__ == '__main__':
    main()
