#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Offline smoke tests for the release scripts and image helpers (no scanner needed)."""
from pathlib import Path
import tempfile
import sys
import shutil

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'helpers'))
from scan_descreen import descreen
from install_desktop import write_launcher
from patch_v3 import upgrade
from apply_patches import once


def main():
    # Regression guard: the C++ moc include must always retain its closing quote.
    source = '#include "moc_Skanpage.cpp"\n'
    sample = once(source, '#include "moc_Skanpage.cpp"',
                  'void Skanpage::signalErrorMessage(const QString &text)\n' 
                  '{\n    showUserMessage(SkanpageUtils::ErrorMessage, text);\n}\n\n'
                  '#include "moc_Skanpage.cpp"', 'Skanpage.cpp')
    assert sample.count('#include "moc_Skanpage.cpp"') == 1
    print('PASS: valid C++ moc include')
    with tempfile.TemporaryDirectory(prefix='scan-tools-selftest-') as temp:
        root = Path(temp)
        original = root / 'original.png'
        img = Image.new('RGB', (220, 340), (220, 210, 190))
        draw = ImageDraw.Draw(img)
        draw.text((20, 40), 'PRINTED ARTWORK', fill=(20, 20, 20))
        for y in range(85, 290, 4):
            draw.line((10, y, 210, y), fill=(70, 70, 70))
        img.save(original, dpi=(600, 600))
        strong = root / 'strong.png'
        half = root / 'half.png'
        unchanged = root / 'unchanged.png'
        descreen(original, strong, 100, 'keep')
        descreen(original, half, 70, '300')
        descreen(original, unchanged, 0, 'keep')
        with Image.open(strong) as out:
            assert out.size == (220, 340)
            assert abs(out.info['dpi'][0] - 600) < 2
        with Image.open(half) as out:
            assert out.size == (110, 170)
            assert abs(out.info['dpi'][0] - 300) < 2
        with Image.open(unchanged) as out:
            assert out.tobytes() == img.tobytes()
        print('PASS: descreen 0%, 70%, 100%, output DPI and dimensions')

        # Launcher should point at a standalone executable, never /usr/bin/skanpage.
        test_binary = root / 'custom' / 'bin' / 'skanpage'
        test_binary.parent.mkdir(parents=True)
        test_binary.write_text('#!/bin/sh\nexit 0\n')
        test_binary.chmod(0o755)
        desktop = write_launcher(test_binary, root / 'applications')
        content = desktop.read_text()
        assert 'Name=Skanpage Scan Tools' in content
        assert f'Exec="{test_binary}"' in content
        assert 'Icon=skanpage' in content
        assert desktop.name == 'skanpage-scan-tools.desktop'
        print('PASS: isolated KDE menu launcher')

        fixture = ROOT / 'tests' / 'v2_fixture'
        if fixture.exists():
            checkout = root / 'mock_skanpage'
            shutil.copytree(fixture, checkout)
            originals = {str(p.relative_to(checkout)): p.read_bytes()
                         for p in checkout.rglob('*') if p.is_file()}
            upgrade(checkout, dry_run=True)
            assert all((checkout / p).read_bytes() == data for p, data in originals.items())
            upgrade(checkout)
            code = (checkout / 'src/Skanpage.cpp').read_text()
            assert 'int m_descreenStrength = 70;' in code
            assert 'm_automaticCrop' not in code
            print('PASS: version 3 source patch on representative fixture')
        else:
            print('SKIP: optional source fixture not distributed')
    print('ALL LOCAL TESTS PASSED (full compilation still needs KDE/Qt on Linux)')


if __name__ == '__main__':
    main()
