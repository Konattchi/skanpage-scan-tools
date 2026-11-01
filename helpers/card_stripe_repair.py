# SPDX-License-Identifier: GPL-3.0-only
#!/usr/bin/env python3
"""Repair one horizontal scan stripe using a second image and local registration.

Experimental: verifies alignment before replacing damaged rows.

Run (after cropping both sides with card_autocrop.py):
    python card_stripe_repair.py "test3-0001_cropped.png" "test3-0000_cropped.png" --rotate-reference

For this specific Flamethrower scan the default band covers the damaged quote.
Adjust it with --band 0.895:0.915 (fractions of card height) or --band 1820:1870 (pixels).

Needs: python-opencv, python-numpy, python-pillow (all in Arch/CachyOS repos).
This is an experimental tool; always compare the output against both originals.
"""

import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def parse_band(value: str, height: int) -> tuple[int, int]:
    try:
        start, end = (float(v.strip()) for v in value.split(":"))
    except (ValueError, AttributeError) as err:
        raise ValueError("Use --band START:END, for example 0.895:0.915 or 1820:1870") from err
    if 0 <= start < end <= 1:
        start, end = round(start * height), round(end * height)
    else:
        start, end = round(start), round(end)
    if not 0 <= start < end <= height:
        raise ValueError(f"Band must fit within image height (0-{height} pixels)")
    return start, end


def sift_align(base: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, int, float]:
    h, w = base.shape[:2]
    # Use small images for feature matching at all resolutions.
    scale = min(1.0, 1400.0 / max(h, w))
    size = (round(w * scale), round(h * scale))
    small_base = cv2.resize(base, size, interpolation=cv2.INTER_AREA)
    small_ref = cv2.resize(reference, size, interpolation=cv2.INTER_AREA)
    gray_base = cv2.cvtColor(small_base, cv2.COLOR_BGR2GRAY)
    gray_ref = cv2.cvtColor(small_ref, cv2.COLOR_BGR2GRAY)

    detector = cv2.SIFT_create(nfeatures=4500)
    key_base, des_base = detector.detectAndCompute(gray_base, None)
    key_ref, des_ref = detector.detectAndCompute(gray_ref, None)
    if des_base is None or des_ref is None:
        raise RuntimeError("Not enough image detail to align the two scans")

    pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(des_ref, des_base, k=2)
    good = [a for pair in pairs if len(pair) == 2 for a, b in [pair] if a.distance < 0.75 * b.distance]
    if len(good) < 25:
        raise RuntimeError(f"Could not match scans reliably ({len(good)} good points)")

    src_pts = np.float32([key_ref[m.queryIdx].pt for m in good])
    dst_pts = np.float32([key_base[m.trainIdx].pt for m in good])
    matrix, mask = cv2.estimateAffinePartial2D(
        src_pts, dst_pts, method=cv2.RANSAC,
        ransacReprojThreshold=3.0, maxIters=7000, confidence=0.999,
    )
    if matrix is None or mask is None:
        raise RuntimeError("Alignment failed")
    inliers = int(np.count_nonzero(mask))
    if inliers < 25 or inliers / len(good) < 0.35:
        raise RuntimeError(f"Unreliable alignment ({inliers}/{len(good)} matches agree)")

    # Rotation and scale are independent of the downsampling; translation is not.
    matrix[:, 2] /= scale
    warped = cv2.warpAffine(
        reference, matrix, (w, h), flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0),
    )
    return warped, inliers, inliers / len(good)


def locally_align_band(base: np.ndarray, warped: np.ndarray,
                       band: tuple[int, int], max_shift: float | None = None
                       ) -> np.ndarray:
    """Return a corrected *band only*, using a smoothly varying alignment field.

    A sheet feeder can stretch/compress a document as it moves. We therefore
    measure 2D translations in multiple undamaged blocks ABOVE and BELOW the
    defect, then interpolate those measurements across the missing rows.
    No measurements are taken from the damaged band itself.
    """
    h, w = base.shape[:2]
    lo, hi = band
    # Keep anchors close, but exclude the defective rows and their edges.
    gap = max(5, round(h * 0.006))
    radius = max(65, round(h * 0.075))
    anchor_ranges = [
        (max(0, lo - radius), lo - gap),
        (hi + gap, min(h, hi + radius)),
    ]
    if any(y1 - y0 < max(42, round(h * 0.014)) for y0, y1 in anchor_ranges):
        raise RuntimeError('Repair band is too close to an edge for two-sided alignment verification; no output written')

    # Downsize ONLY the alignment-analysis images, not the output.
    # This keeps 1200 DPI memory/cost manageable and scales pixel thresholds.
    sample_scale = min(1.0, 1700.0 / max(w, h))
    aw, ah = round(w * sample_scale), round(h * sample_scale)
    gray_base = cv2.resize(cv2.cvtColor(base, cv2.COLOR_BGR2GRAY), (aw, ah), interpolation=cv2.INTER_AREA)
    gray_ref = cv2.resize(cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY), (aw, ah), interpolation=cv2.INTER_AREA)
    gray_base = cv2.GaussianBlur(gray_base, (5, 5), 0.9)
    gray_ref = cv2.GaussianBlur(gray_ref, (5, 5), 0.9)

    # Seven overlapping, laterally distributed measurement patches per side.
    # Overlap allows genuine smooth feed distortions but rejects unstable tiles.
    cols = 7
    centers = np.linspace(0.12, 0.88, cols)
    halfwidth = 0.12
    max_allowed = (max_shift if max_shift is not None
                   else min(48.0, max(8.0, w * 0.013)))
    if max_allowed <= 0:
        raise RuntimeError('Maximum local shift must be positive')

    measured = []
    for side, (yb0, yb1) in enumerate(anchor_ranges):
        row = []
        sy0, sy1 = round(yb0 * sample_scale), round(yb1 * sample_scale)
        for cx in centers:
            sx0 = round(max(0.0, cx-halfwidth) * aw)
            sx1 = round(min(1.0, cx+halfwidth) * aw)
            target = gray_base[sy0:sy1, sx0:sx1]
            source = gray_ref[sy0:sy1, sx0:sx1]
            if min(target.shape) < 38:
                raise RuntimeError('Not enough image detail around the stripe for local alignment')
            if float(np.std(target)) < 5.0:
                raise RuntimeError('Low-detail region prevents safe local alignment; no output written')
            warp = np.eye(2, 3, dtype=np.float32)
            try:
                cc, warp = cv2.findTransformECC(
                    target, source, warp, cv2.MOTION_TRANSLATION,
                    (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 160, 1e-5),
                    None, 5,
                )
            except cv2.error as exc:
                raise RuntimeError(f'Local alignment failed at {"above" if side == 0 else "below"} block {len(row)+1}; no repaired output') from exc
            dx, dy = map(float, warp[:, 2])
            dx /= sample_scale
            dy /= sample_scale
            if not np.isfinite(dx+dy) or max(abs(dx), abs(dy)) > max_allowed:
                raise RuntimeError(f'Local shift ({dx:+.1f}, {dy:+.1f}) exceeded {max_allowed:.1f}px at block {len(row)+1}; no output')
            if cc < 0.88:
                raise RuntimeError(f'Unreliable local match ({cc:.3f}) in block {len(row)+1}; no output')
            # A warped patch should not become substantially less similar.
            fixed = cv2.warpAffine(source, warp, (source.shape[1], source.shape[0]),
                                  flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                  borderMode=cv2.BORDER_REPLICATE)
            # Exclude a margin where the shift would sample outside this crop.
            pad = max(8, round(max(abs(dx), abs(dy)) * sample_scale) + 4)
            if pad*2 >= min(source.shape):
                raise RuntimeError('Alignment check patch too small')
            raw_error = float(np.mean(cv2.absdiff(target[pad:-pad,pad:-pad],source[pad:-pad,pad:-pad])))
            fixed_error = float(np.mean(cv2.absdiff(target[pad:-pad,pad:-pad],fixed[pad:-pad,pad:-pad])))
            if fixed_error > max(raw_error * 1.06, raw_error + 1.0):
                raise RuntimeError(f'Local match became worse at block {len(row)+1} ({raw_error:.1f}->{fixed_error:.1f}); no output')
            row.append((dx,dy,cc,raw_error,fixed_error))
        measured.append(np.array(row, dtype=np.float64))

    above, below = measured
    # Guard against wildly different adjacent shifts, often produced by
    # accidental matching on repetitive lettering or large blank regions.
    for name, arr in [('above', above), ('below', below)]:
        diffs = np.abs(np.diff(arr[:, :2], axis=0))
        jump_limit = max(3.0, w * 0.004)
        if np.any(diffs > jump_limit):
            raise RuntimeError(f'Local shifts are inconsistent across the {name} edge; no output')

    print(f'Local alignment: above median ({np.median(above[:,0]):+.2f}, {np.median(above[:,1]):+.2f})px; '
          f'below median ({np.median(below[:,0]):+.2f}, {np.median(below[:,1]):+.2f})px')
    print(f'Anchor image similarities: {np.min(above[:,2]):.3f} to {np.max(above[:,2]):.3f} above, '
          f'{np.min(below[:,2]):.3f} to {np.max(below[:,2]):.3f} below')

    # A smooth 2D displacement field; interpolation between x tiles and the
    # two scan-feed positions. Only create the output rows, NOT another full
    # resolution image, for performance and memory safety.
    xx = np.arange(w, dtype=np.float32)
    xcenters = centers * w
    dx_above = np.interp(xx, xcenters, above[:,0]).astype(np.float32)
    dy_above = np.interp(xx, xcenters, above[:,1]).astype(np.float32)
    dx_below = np.interp(xx, xcenters, below[:,0]).astype(np.float32)
    dy_below = np.interp(xx, xcenters, below[:,1]).astype(np.float32)
    # y positions of the measurements are the center of each valid region.
    yc_top = sum(anchor_ranges[0]) / 2
    yc_bot = sum(anchor_ranges[1]) / 2
    ys = np.arange(lo, hi, dtype=np.float32)
    t = np.clip((ys - yc_top) / (yc_bot-yc_top), 0, 1)[:, None]
    xmap = (xx[None,:] + (1-t)*dx_above[None,:] + t*dx_below[None,:]).astype(np.float32)
    ymap = (ys[:,None] + (1-t)*dy_above[None,:] + t*dy_below[None,:]).astype(np.float32)

    # Mask any locations outside the registered donor image.  Otherwise the
    # missing border may silently turn black in the finished document.
    valid = (xmap >= 0) & (xmap <= w-1) & (ymap >= 0) & (ymap <= h-1)
    if np.count_nonzero(~valid) > 0.01 * valid.size:
        raise RuntimeError('Too much of replacement band lies outside the aligned reference; no output')
    out = cv2.remap(warped, xmap, ymap, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    if not np.all(valid):
        out[~valid] = base[lo:hi][~valid]
    return out

def make_comparison(before: np.ndarray, after: np.ndarray,
                    reference: np.ndarray, band: tuple[int, int], destination: Path):
    h, w = before.shape[:2]
    lo, hi = band
    y0, y1 = max(0, lo - round(h * .065)), min(h, hi + round(h * .065))
    x0, x1 = round(w * .05), round(w * .95)
    panels = [before[y0:y1, x0:x1], after[y0:y1, x0:x1], reference[y0:y1, x0:x1]]
    titles = ["ORIGINAL (STRIPE)", "REPAIRED", "ROTATED SCAN ALIGNED"]
    scale = min(1.0, 950 / (x1-x0))
    labeled = []
    for panel, title in zip(panels, titles):
        panel = cv2.resize(panel, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        top = np.full((38, panel.shape[1], 3), (35,35,35), np.uint8)
        cv2.putText(top, title, (10, 25), cv2.FONT_HERSHEY_SIMPLEX,
                    .65, (255,255,255), 1, cv2.LINE_AA)
        labeled.extend([top, panel])
    cv2.imwrite(str(destination), np.vstack(labeled), [cv2.IMWRITE_PNG_COMPRESSION, 4])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("normal", help="Upright scan containing the damaged stripe")
    p.add_argument("reference", help="Second scan of the same object (preferably opposite feed orientation)")
    p.add_argument("--rotate-reference", action="store_true", help="Rotate the reference scan 180 degrees")
    p.add_argument("--band", default="0.895:0.915", help="Damaged row range, fractional height or pixels")
    p.add_argument("--feather", type=int, default=None, help="Fade width at stripe edges, in pixels (default scales with image width)")
    p.add_argument("--max-local-shift", type=float, default=None, help="Override local shift safety limit in full-image pixels")
    p.add_argument("--output", help="Output path (default: NORMAL_repaired.png)")
    args = p.parse_args()
    normal_path = Path(args.normal)
    reference_path = Path(args.reference)
    out = Path(args.output) if args.output else normal_path.with_name(normal_path.stem+"_repaired.png")
    base = cv2.imread(str(normal_path), cv2.IMREAD_COLOR)
    ref = cv2.imread(str(reference_path), cv2.IMREAD_COLOR)
    if base is None or ref is None:
        p.error("Could not read one of the images. Check filenames and paths.")
    if args.rotate_reference:
        ref = cv2.rotate(ref, cv2.ROTATE_180)
    h, w = base.shape[:2]
    band = parse_band(args.band, h)
    print(f"Upright scan: {w} x {h}; replacing rows {band[0]}-{band[1]}")
    aligned, matches, ratio = sift_align(base, ref)
    print(f"Alignment: {matches} agreeing feature matches ({ratio:.0%})")
    repaired_band = locally_align_band(base, aligned, band, max_shift=args.max_local_shift)

    lo, hi = band
    feather = args.feather if args.feather is not None else round(8 * w / 1450)
    f = max(0, min(feather, (hi-lo)//3))
    alpha = np.ones(hi-lo, dtype=np.float32)
    if f:
        alpha[:f] = np.linspace(0, 1, f, endpoint=False)
        alpha[-f:] = np.linspace(1, 0, f, endpoint=False)
    a = alpha[:, None, None]
    result = base.copy()
    # Only pixels within this band are modified. Everything else stays bit-identical.
    result[lo:hi] = np.clip(
        base[lo:hi].astype(np.float32)*(1-a) + repaired_band.astype(np.float32)*a,
        0, 255,
    ).astype(np.uint8)

    original_info = Image.open(normal_path).info
    save_opts = {"compress_level": 4}
    if original_info.get("dpi"):
        save_opts["dpi"] = original_info["dpi"]
    Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB)).save(out, **save_opts)
    preview = out.with_name(out.stem+"_comparison.png")
    make_comparison(base, result, aligned, band, preview)
    print("Saved repaired image:", out)
    print("Saved before/after close-up:", preview)
    print("Please inspect the text at 100% zoom for double edges or a visible seam.")


if __name__ == "__main__":
    main()
