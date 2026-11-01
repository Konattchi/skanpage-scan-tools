# SPDX-License-Identifier: GPL-3.0-only
#!/usr/bin/env python3
"""Upgrade the *existing v2-modified* Skanpage 26.08.2 source to v3.

No root privileges. Transactional: validate every source anchor before writes;
back up the four original source files first; never touch the KDE system copy.
"""

from pathlib import Path
import argparse
import shutil

FILES = ('src/Skanpage.h', 'src/Skanpage.cpp',
         'src/qml/DocumentPage.qml', 'src/qml/OptionsPanel.qml')


def once(s: str, old: str, new: str, filename: str) -> str:
    n = s.count(old)
    if n != 1:
        raise RuntimeError(f'{filename}: expected one match for {old[:75]!r}, found {n}. No changes written.')
    return s.replace(old, new, 1)


def between(s: str, start: str, end: str, new: str, filename: str) -> str:
    if s.count(start) != 1 or s.count(end) != 1:
        raise RuntimeError(f'{filename}: missing or ambiguous section boundaries; no changes written.')
    a = s.index(start)
    b = s.index(end, a + len(start))
    return s[:a] + new + s[b:]


AUTO_DESCREEN = r'''// Optional descreening of *new scans* (not preview scans or imports).
// Native SANE/driver Auto Document Size remains responsible for scan bounds.
bool Skanpage::automaticDescreen() const { return d->m_automaticDescreen; }
void Skanpage::setAutomaticDescreen(bool enabled)
{
    if (d->m_automaticDescreen == enabled) return;
    d->m_automaticDescreen = enabled;
    Q_EMIT automaticDescreenChanged();
}
int Skanpage::descreenStrength() const { return d->m_descreenStrength; }
void Skanpage::setDescreenStrength(int value)
{
    value = qBound(0, value, 100);
    if (d->m_descreenStrength == value) return;
    d->m_descreenStrength = value;
    Q_EMIT descreenStrengthChanged();
}
bool Skanpage::descreenReduceTo300() const { return d->m_descreenReduceTo300; }
void Skanpage::setDescreenReduceTo300(bool enabled)
{
    if (d->m_descreenReduceTo300 == enabled) return;
    d->m_descreenReduceTo300 = enabled;
    Q_EMIT descreenReduceTo300Changed();
}
bool Skanpage::keepOriginalScans() const { return d->m_keepOriginalScans; }
void Skanpage::setKeepOriginalScans(bool enabled)
{
    if (d->m_keepOriginalScans == enabled) return;
    d->m_keepOriginalScans = enabled;
    Q_EMIT keepOriginalScansChanged();
}

// No crop code in this path: when descreening is off, add scanned images
// directly. When enabled, append processed result only (or both if opted in).
// Failure always preserves at least the unprocessed original.
void Skanpage::processIncomingImage(const QImage &image)
{
    if (!d->m_automaticDescreen) {
        d->m_documentHandler.addImage(image);
        return;
    }
    const bool keepOriginal = d->m_keepOriginalScans;
    if (keepOriginal) d->m_documentHandler.addImage(image);
    const auto fallback = [this, &image, keepOriginal](const QString &message) {
        if (!keepOriginal) d->m_documentHandler.addImage(image);
        signalErrorMessage(message);
    };
    const QString python = QStandardPaths::findExecutable(QStringLiteral("python3"));
    const QString helperDir = QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation)
        + QStringLiteral("/skanpage-card-tools/");
    const QString scriptFile = helperDir + QStringLiteral("scan_descreen.py");
    if (python.isEmpty() || !QFileInfo::exists(scriptFile)) {
        fallback(i18n("Descreen helper is missing; original scan was kept."));
        return;
    }
    auto directory = std::make_shared<QTemporaryDir>();
    if (!directory->isValid()) {
        fallback(i18n("Could not create a temporary directory; original scan was kept."));
        return;
    }
    const QString source = directory->filePath(QStringLiteral("scan.png"));
    const QString destination = directory->filePath(QStringLiteral("scan_descreened.png"));
    if (!image.save(source, "PNG")) {
        fallback(i18n("Could not prepare scan for descreening; original scan was kept."));
        return;
    }
    auto *process = new QProcess(this);
    process->setProgram(python);
    QStringList args{scriptFile, source, QStringLiteral("--output"), destination,
                     QStringLiteral("--strength"), QString::number(d->m_descreenStrength),
                     QStringLiteral("--resolution"),
                     d->m_descreenReduceTo300 ? QStringLiteral("300") : QStringLiteral("keep")};
    const int sourceDpi = qRound(image.dotsPerMeterX() * 0.0254);
    if (sourceDpi >= 72 && sourceDpi <= 4800)
        args << QStringLiteral("--source-dpi") << QString::number(sourceDpi);
    process->setArguments(args);
    ++d->m_pendingScanProcesses;
    auto completed = std::make_shared<bool>(false);
    const auto complete = [this, process, directory, image, destination, keepOriginal, completed]
                          (bool success, const QString &details) {
        if (*completed) return;
        *completed = true;
        QImage processed;
        if (success) processed.load(destination);
        if (processed.isNull()) {
            if (!keepOriginal) d->m_documentHandler.addImage(image);
            signalErrorMessage(i18n("Descreening failed; original scan was kept. %1", details));
        } else {
            d->m_documentHandler.addImage(processed);
        }
        --d->m_pendingScanProcesses;
        checkFinish();
        process->deleteLater();
    };
    connect(process, QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished), this,
            [process, complete](int code, QProcess::ExitStatus status) {
                complete(code == 0 && status == QProcess::NormalExit,
                         QString::fromLocal8Bit(process->readAllStandardError()).right(650));
            });
    connect(process, &QProcess::errorOccurred, this,
            [complete](QProcess::ProcessError error) {
                if (error == QProcess::FailedToStart)
                    complete(false, QStringLiteral("Python failed to start"));
            });
    process->start();
}

'''

CONTROLS = r'''    // Image processing is application-side. "Auto Document Size" is the
    // Brother/SANE option displayed separately by the normal scanner panel.
    GroupBox {
        title: i18n("Descreen")
        Layout.fillWidth: true
        visible: !optionPanel.editMode
        enabled: skanpage.applicationState === Skanpage.ReadyForScan
        ColumnLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing
            CheckBox {
                text: i18n("Descreen new scans")
                checked: skanpage.automaticDescreen
                onToggled: skanpage.automaticDescreen = checked
            }
            Label {
                text: i18n("Strength: %1%", skanpage.descreenStrength)
                Layout.fillWidth: true
            }
            Slider {
                id: descreenStrengthSlider
                Layout.fillWidth: true
                from: 0
                to: 100
                stepSize: 5
                value: skanpage.descreenStrength
                onMoved: skanpage.descreenStrength = Math.round(value)
            }
            Label {
                text: i18n("Output resolution:")
                Layout.fillWidth: true
            }
            ComboBox {
                Layout.fillWidth: true
                model: [i18n("Keep original DPI"), i18n("300 DPI (reduce if higher)")]
                currentIndex: skanpage.descreenReduceTo300 ? 1 : 0
                onActivated: function(index) { skanpage.descreenReduceTo300 = (index === 1) }
            }
            CheckBox {
                text: i18n("Also keep unprocessed scans")
                checked: skanpage.keepOriginalScans
                onToggled: skanpage.keepOriginalScans = checked
            }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: i18n("Use the Brother Auto Document Size option for cropping. Disable automatic Descreen when making two scans for stripe repair.")
            }
        }
    }

'''


def upgrade(root: Path, dry_run: bool = False):
    root = root.expanduser().resolve()
    if not (root / 'CMakeLists.txt').is_file():
        raise RuntimeError(f'Not a Skanpage source directory: {root}')
    paths = [root / f for f in FILES]
    originals = {p: p.read_text(encoding='utf-8') for p in paths}
    changed = originals.copy()
    header, cpp, document, options = paths

    if 'Q_PROPERTY(int descreenStrength' in originals[header]:
        raise RuntimeError('Already looks like v3; nothing changed.')
    if ('Q_PROPERTY(bool automaticCrop' not in originals[header]
        or 'void Skanpage::processIncomingImage(' not in originals[cpp]
        or 'void Skanpage::applyCardTool(' not in originals[cpp]
        or 'i18n("Auto Crop")' not in originals[document]
        or 'title: i18n("Scan output")' not in originals[options]):
        raise RuntimeError('Expected v2-modified Skanpage 26.08.2. No files changed.')

    # Header: remove crop; add two controls (strength + DPI choice).
    changed[header] = once(changed[header],
        '    Q_PROPERTY(bool automaticCrop READ automaticCrop WRITE setAutomaticCrop NOTIFY automaticCropChanged)\n',
        '', header.name)
    changed[header] = once(changed[header],
        '    Q_PROPERTY(bool automaticDescreen READ automaticDescreen WRITE setAutomaticDescreen NOTIFY automaticDescreenChanged)\n',
        '    Q_PROPERTY(bool automaticDescreen READ automaticDescreen WRITE setAutomaticDescreen NOTIFY automaticDescreenChanged)\n'
        '    Q_PROPERTY(int descreenStrength READ descreenStrength WRITE setDescreenStrength NOTIFY descreenStrengthChanged)\n'
        '    Q_PROPERTY(bool descreenReduceTo300 READ descreenReduceTo300 WRITE setDescreenReduceTo300 NOTIFY descreenReduceTo300Changed)\n',
        header.name)
    changed[header] = once(changed[header],
        '    bool automaticCrop() const;\n    void setAutomaticCrop(bool enabled);\n', '', header.name)
    changed[header] = once(changed[header],
        '    bool automaticDescreen() const;\n    void setAutomaticDescreen(bool enabled);\n',
        '    bool automaticDescreen() const;\n    void setAutomaticDescreen(bool enabled);\n'
        '    int descreenStrength() const;\n    void setDescreenStrength(int value);\n'
        '    bool descreenReduceTo300() const;\n    void setDescreenReduceTo300(bool enabled);\n',
        header.name)
    changed[header] = once(changed[header], '    void automaticCropChanged();\n', '', header.name)
    changed[header] = once(changed[header], '    void automaticDescreenChanged();\n',
        '    void automaticDescreenChanged();\n'
        '    void descreenStrengthChanged();\n'
        '    void descreenReduceTo300Changed();\n', header.name)

    changed[cpp] = once(changed[cpp],
        '    bool m_automaticCrop = false;\n', '', cpp.name)
    changed[cpp] = once(changed[cpp],
        '    bool m_automaticDescreen = false;\n',
        '    bool m_automaticDescreen = false;\n'
        '    int m_descreenStrength = 70;\n'
        '    bool m_descreenReduceTo300 = false;\n', cpp.name)
    changed[cpp] = between(changed[cpp],
        '// Experimental scan-output processing.',
        'void Skanpage::imageReady(const QImage &image)\n{',
        AUTO_DESCREEN, cpp.name)

    # Keep the existing repair procedure, but remove the obsolete manual
    # crop action and swap manual Descreen to the adjustable helper.
    changed[cpp] = once(changed[cpp],
        'if (action != QStringLiteral("crop") && action != QStringLiteral("descreen")\n'
        '        && action != QStringLiteral("repair")) {',
        'if (action != QStringLiteral("descreen") && action != QStringLiteral("repair")) {',
        cpp.name)
    changed[cpp] = once(changed[cpp],
        'const QString scriptName = action == QStringLiteral("crop") ? QStringLiteral("scan_autocrop.py")\n'
        '        : action == QStringLiteral("descreen") ? QStringLiteral("card_descreen.py")\n'
        '        : QStringLiteral("card_stripe_repair.py");',
        'const QString scriptName = action == QStringLiteral("descreen")\n'
        '        ? QStringLiteral("scan_descreen.py") : QStringLiteral("card_stripe_repair.py");',
        cpp.name)
    changed[cpp] = once(changed[cpp],
        '    QStringList arguments{scriptFile, mainFile};\n',
        '    QStringList arguments{scriptFile, mainFile};\n'
        '    if (action == QStringLiteral("descreen")) {\n'
        '        arguments << QStringLiteral("--strength") << QString::number(d->m_descreenStrength)\n'
        '                  << QStringLiteral("--resolution")\n'
        '                  << (d->m_descreenReduceTo300 ? QStringLiteral("300") : QStringLiteral("keep"));\n'
        '    }\n', cpp.name)
    changed[cpp] = once(changed[cpp],
        'const QString resultName = action == QStringLiteral("crop") ? QStringLiteral("main_cropped.png")\n'
        '        : action == QStringLiteral("descreen") ? QStringLiteral("main_descreened.png")\n'
        '        : QStringLiteral("main_repaired.png");',
        'const QString resultName = action == QStringLiteral("descreen")\n'
        '        ? QStringLiteral("main_descreened.png") : QStringLiteral("main_repaired.png");',
        cpp.name)

    # Toolbar: remove just the extra crop action, leave everything else alone.
    changed[document] = between(changed[document],
        '                ShortcutsAction {\n                    icon.name: "transform-crop"',
        '                ShortcutsAction {\n                    icon.name: "image-x-generic"',
        '', document.name)

    # OptionsPanel: remove both old crop output select and old fixed on/off
    # settings; add slider and resolution choice, leaving scanner options intact.
    changed[options] = between(changed[options],
        '    // These are application-side output operations, not hardware scan options.\n',
        '    ScrollView {\n        id: optionsList',
        CONTROLS, options.name)

    for f, content in changed.items():
        if content == originals[f]:
            raise RuntimeError(f'Expected to change {f}; refusing a no-op')
        if f == cpp and ('m_automaticCrop' in content or 'QStringLiteral("crop")' in content):
            raise RuntimeError('Unexpected crop code left in Skanpage.cpp')
    if dry_run:
        for f in paths:
            print('Would update:', f.relative_to(root))
        print('Dry run OK; no files written.')
        return
    backup = root / '.scan_tools_v3_backup'
    if backup.exists():
        raise RuntimeError(f'Backup already exists; refusing to overwrite: {backup}')
    backup.mkdir()
    for f in paths:
        shutil.copy2(f, backup / f.name)
    for f in paths:
        f.write_text(changed[f], encoding='utf-8')
        print('Updated:', f.relative_to(root))
    print('Backup:', backup)
    print('Next: cmake --build build -j 4')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path, help='Existing v2-patched Skanpage 26.08.2 checkout')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    upgrade(args.source, args.dry_run)


if __name__ == '__main__':
    main()
