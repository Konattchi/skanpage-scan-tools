# Skanpage Scan Tools — v0.1.0

**Unofficial community extension of [KDE Skanpage](https://invent.kde.org/utilities/skanpage), built against the stable release 26.08.2.** Not affiliated with or endorsed by KDE or Brother.

Adds two optional image-processing capabilities to an otherwise unmodified scanner backend:

- **Descreen:** smooth printed halftone dots in scanned artwork, magazines and photographs. An adjustable 0–100 slider starts at **70%**, with a stronger maximum than our first prototype. Automatic processing is **off by default**. You can choose to retain source DPI or reduce to 300 DPI.
- **Repair Scan Stripe:** align two scans of the same document, one normally and ideally one fed upside down, and replace a manually selected horizontal band. Includes local registration to compensate for small sheet-feeder distortions. The result is a new page; originals are not overwritten.

**No auto-crop feature is added.** If your device supports it, use the scanner's existing *Auto Document Size* option shown by Skanpage/SANE. The project does not contain a Brother driver.

## Current status

Experimental first public version. Developed and primarily tested on a Brother DS-740D with `brscan5`, KDE Plasma 6, CachyOS and scans from 300 to 1200 DPI. The stripe repair is not guaranteed on arbitrary documents or layouts, and can fail on repetitive or feature-poor images. Always inspect the output at 100% before saving. The stripe band defaults to `0.895:0.915` (the prototype test image); **change it for other documents**. Only a horizontal band across the image width is supported, not arbitrary scratches. At high strength descreening softens fine print and text; use lower strength when preserving text matters.

The source upgrade chain is based on the same Skanpage 26.08.2 modifications previously built and tested by the project developer. The clean-install pipeline and Plasma application-ID adjustment still require independent verification on other systems.

## Installation (Arch Linux / CachyOS)

Prerequisites: a working SANE scanner, KDE/Qt 6 Skanpage build dependencies, Python 3, OpenCV + NumPy, Pillow, Git, Ninja, CMake, and a C++ compiler. On Arch-based distributions, the minimum build-tool command is:

```sh
sudo pacman -S --needed git base-devel cmake ninja extra-cmake-modules python-opencv python-numpy python-pillow
```

KDE build dependencies required by upstream include KSaneCore6/`ksanecore`, `kquickimageeditor`, KDE Frameworks 6, Qt 6, Tesseract and Leptonica. They are commonly installed already with system Skanpage, but if CMake reports a missing package, install the corresponding `-dev`/distro package before retrying. **The expected KSaneCore version is 26.08.x.** Do not force Skanpage `master` to build against stable libraries.

Download this repository or clone it, then from its root run:

```sh
bash install.sh
```

The installer obtains official Skanpage **v26.08.2** source, applies our source changes, compiles it, installs to **`~/.local/opt/skanpage-scan-tools/`**, installs the helper scripts under **`~/.local/share/skanpage-card-tools/`**, and creates a KDE menu entry in **`~/.local/share/applications/`**. It never overwrites `/usr/bin/skanpage`, system libraries or `brscan5` and does **not** require sudo. Compile jobs can be reduced with `SKANPAGE_SCAN_TOOLS_JOBS=2 bash install.sh`.

If the build fails, the installer stops **before installing**. Intermediate source and logs remain in a uniquely named directory under `~/.cache/` for debugging. A partial custom prefix might remain after a later installation error; the stock program is unaffected.

### Launch from KDE and pin it

Open the **Application Launcher** (Start menu), search for **Skanpage Scan Tools**, right-click it and choose **Add to Favorites** (or **Pin to Task Manager**, depending on your Plasma layout). The custom `.desktop` file has a distinct ID and the build sets its corresponding Qt Wayland desktop-file name, to distinguish it from stock Skanpage.

You can also use `~/.local/opt/skanpage-scan-tools/bin/skanpage` directly.

**Already running an older custom build?** Make a menu entry for it **without recompiling anything**:

```sh
bash add_launcher.sh "$HOME/.local/opt/skanpage-cards/bin/skanpage"
```

That makes the launcher point to the existing executable, rather than the new release. If you later install the public build, `bash install.sh` updates the launcher to point to the new executable. The older executable may share an application ID with stock Skanpage, so task-manager grouping may differ; menu Favorites still work.

### Usage

1. Configure the scanner normally, including its own **Auto Document Size** feature when supported.
2. For a document needing stripe repair, turn **automatic Descreen off**, and scan the material twice (normal and rotated 180°). Use Skanpage's **Repair Scan Stripe…** button, choose the other scan as the reference and set the damaged band.
3. Inspect the repaired page. Select it, adjust Descreen strength (start at 70%), and press **Descreen**. The original/repair pages stay available for comparison.
4. For ordinary printed artwork, **Descreen new scans** may be enabled to automatically process incoming scans. Adjust strength and output resolution in the Scanner Options panel.

The image filters run in Python subprocesses. The slider settings currently reset when the program restarts. The repair action does not automatically detect damaged bands.

## Updating and uninstalling

This release is pinned to KDE Skanpage 26.08.2; installing a newer upstream stable version requires adapting and testing the patch. Run `bash uninstall.sh` to remove the custom install and desktop entry. Python helpers are intentionally left in place in case you use an older modified Skanpage build.

## Licensing and attribution

- The original KDE Skanpage application is **copyright its respective KDE contributors** and uses its upstream license files and per-file SPDX identifiers. This repository does **not** redistribute the complete KDE source; the installer fetches the tagged official source. Upstream sources and existing notices remain intact. See [KDE Skanpage](https://invent.kde.org/utilities/skanpage).
- The patch scripts, integration additions and Python processing helpers distributed in this repository are offered under **GPL-3.0-only**; see `LICENSE`. This is compatible with Skanpage's GNU GPL license alternatives. Other files fetched from KDE can have additional per-file SPDX licenses, which remain in force.
- Brother's proprietary scanner software is not included or required by the image-processing algorithms. The scanner must already be operational through a supported SANE backend.
- No third-party board-game artwork, proprietary device drivers or copied commercial card scans are included.

## Contributing / KDE upstream

Please report issues and include the scanning resolution, object type, Linux distribution, SANE backend, whether two scans were rotated, and the exact visible error. Avoid uploading confidential scanned documents. This repository is not a KDE upstream merge request; if broad community testing is positive, the general-purpose Descreen feature could be proposed through [KDE Invent](https://invent.kde.org/utilities/skanpage/-/merge_requests).

The code is a community-maintained, unofficial modification; please do not report issues caused by these patches to the KDE Skanpage upstream tracker without first isolating them in the stock application.
