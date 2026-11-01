# SPDX-License-Identifier: GPL-3.0-only
#!/usr/bin/env python3
"""Adjustable descreen for printed scan material; compatible with Skanpage Scan Tools v3.

Strength 0-100. Recalibrated in v3.1 so 75 approximates the old maximum
(100 at 600 DPI) and 100 gives substantially stronger smoothing.

This is a spatial smoothing/descreen filter, not a frequency-domain
halftone reconstruction algorithm. Always process a raw/repaired scan,
not an already-descreened copy. Input files are never overwritten.
"""

import argparse
from pathlib import Path
from PIL import Image, ImageFilter

# Blur radius is expressed at a 600-DPI reference resolution. This
# makes filter strength more consistent across 300, 600, and 1200 DPI.
# The mapping gives finer control at gentle settings and more range at
# high settings. 75% ~= v3's former 100% (1.77px at 600 DPI).
STRENGTH_CURVE = ((0, 0.0), (25, 0.4), (50, 1.0), (75, 1.8), (100, 3.0))


def radius_at_600dpi(strength: int) -> float:
    if not 0 <= strength <= 100:
        raise ValueError('strength must be between 0 and 100')
    for (low_s, low_r), (high_s, high_r) in zip(STRENGTH_CURVE, STRENGTH_CURVE[1:]):
        if strength <= high_s:
            t = (strength - low_s) / (high_s - low_s)
            return low_r + t * (high_r - low_r)
    return STRENGTH_CURVE[-1][1]


def descreen(src: Path, dest: Path, strength: int = 70,
             resolution: str = 'keep', source_dpi: int | None = None) -> tuple[int, int]:
    if not 0 <= strength <= 100:
        raise ValueError('strength must be between 0 and 100')
    if resolution not in ('keep', '300'):
        raise ValueError('resolution must be keep or 300')
    if src.resolve() == dest.resolve():
        raise ValueError('Refusing to overwrite the input scan')

    with Image.open(src) as original:
        dpi = original.info.get('dpi', (0, 0))
        detected_dpi = float(dpi[0]) if dpi else 0.0
        if source_dpi is not None and 72 <= source_dpi <= 4800:
            detected_dpi = float(source_dpi)
        img = original.convert('RGB')

    credible_dpi = 72 <= detected_dpi <= 4800
    if not credible_dpi:
        detected_dpi = 0.0

    # Use physical scanning resolution when available. Limit the factor
    # to 0.5..2.0 to keep extreme/erroneous DPI metadata from causing
    # unexpectedly destructive smoothing. Missing DPI uses the old
    # 600-DPI-reference pixel scale (no guess about output dimensions).
    dpi_scale = max(0.5, min(2.0, detected_dpi / 600.0)) if credible_dpi else 1.0
    blur = radius_at_600dpi(strength) * dpi_scale

    if strength > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur))
        if strength >= 75:
            img = img.filter(ImageFilter.MedianFilter(size=3))

    result_dpi = detected_dpi
    if resolution == '300' and credible_dpi and detected_dpi > 300:
        scale = 300.0 / detected_dpi
        if strength == 0:
            # Resizing requires antialiasing even with smoothing disabled.
            img = img.filter(ImageFilter.GaussianBlur(radius=0.45))
        new_size = (max(1, round(img.width * scale)),
                    max(1, round(img.height * scale)))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        result_dpi = 300.0
    elif resolution == '300' and not credible_dpi:
        print('Warning: DPI missing; kept dimensions rather than guessing scaling.')

    # High-strength mode deliberately reduces post-sharpening: sharpening
    # can bring halftone dots back, defeating the purpose of descreening.
    # Gentle / medium settings retain the original edge-recovery behavior.
    if strength > 0:
        unsharp_percent = 60 if strength <= 75 else round(60 - (strength - 75) * 1.6)
        if unsharp_percent > 0:
            img = img.filter(ImageFilter.UnsharpMask(radius=max(0.55, 0.85 * dpi_scale),
                                                    percent=unsharp_percent,
                                                    threshold=3))

    dest.parent.mkdir(parents=True, exist_ok=True)
    options = {'optimize': True}
    if result_dpi:
        options['dpi'] = (result_dpi, result_dpi)
    img.save(dest, format='PNG', **options)
    print(f'Saved {dest}: {img.width}x{img.height}, '
          f'DPI {result_dpi:.1f} (0 = unknown), '
          f'strength {strength}, blur radius {blur:.2f}px, '
          f'sharpen {unsharp_percent if strength else 0}%')
    return img.size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('-o', '--output', type=Path)
    parser.add_argument('--strength', type=int, default=70,
                        help='0–100, new stronger curve; default 70')
    parser.add_argument('--resolution', choices=['keep', '300'], default='keep')
    parser.add_argument('--source-dpi', type=int, default=None,
                        help='Trusted scan DPI if PNG metadata is absent')
    args = parser.parse_args()
    output = args.output or args.input.with_name(args.input.stem + '_descreened.png')
    try:
        descreen(args.input, output, args.strength, args.resolution, args.source_dpi)
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
