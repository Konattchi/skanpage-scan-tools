# SPDX-License-Identifier: GPL-3.0-only
#!/usr/bin/env python3
"""Upgrade the already-working experimental Skanpage 26.08.2 v1 patch to v2.

Safe/idempotent guard: validates every source anchor before writing and keeps
copies of all 4 original files in .scan_tools_v2_backup.
"""
from pathlib import Path
import shutil
import sys


def once(text, old, new, name):
    matches = text.count(old)
    if matches != 1:
        raise RuntimeError(f'{name}: expected one match for {old[:70]!r}, got {matches}. No files modified.')
    return text.replace(old, new, 1)


def main(root):
    root = Path(root).expanduser().resolve()
    if not (root / 'CMakeLists.txt').is_file():
        raise RuntimeError(f'Not a Skanpage source directory: {root}')
    paths = [root / f for f in ('src/Skanpage.h', 'src/Skanpage.cpp',
                                'src/qml/DocumentPage.qml', 'src/qml/OptionsPanel.qml')]
    original = {p: p.read_text(encoding='utf-8') for p in paths}
    changed = original.copy()
    header, impl, document, options = paths

    if 'Q_PROPERTY(bool automaticCrop' in original[header]:
        raise RuntimeError('This source already looks upgraded to v2. Nothing changed.')
    if ('void Skanpage::applyCardTool(' not in original[impl] or
            'void Skanpage::signalErrorMessage(' not in original[impl] or
            'void Skanpage::imageReady(' not in original[impl] or
            'Auto Crop Card' not in original[document]):
        raise RuntimeError('Expected working v1-patched Skanpage source. No files modified.')

    properties = '''    Q_PROPERTY(bool automaticCrop READ automaticCrop WRITE setAutomaticCrop NOTIFY automaticCropChanged)
    Q_PROPERTY(bool automaticDescreen READ automaticDescreen WRITE setAutomaticDescreen NOTIFY automaticDescreenChanged)
    Q_PROPERTY(bool keepOriginalScans READ keepOriginalScans WRITE setKeepOriginalScans NOTIFY keepOriginalScansChanged)
'''
    changed[header] = once(changed[header],
        '    Q_PROPERTY(bool previewImageAvailable READ previewImageAvailable NOTIFY previewImageChanged)\n',
        '    Q_PROPERTY(bool previewImageAvailable READ previewImageAvailable NOTIFY previewImageChanged)\n'+properties,
        header.name)
    accessors = '''    bool automaticCrop() const;
    void setAutomaticCrop(bool enabled);
    bool automaticDescreen() const;
    void setAutomaticDescreen(bool enabled);
    bool keepOriginalScans() const;
    void setKeepOriginalScans(bool enabled);

'''
    changed[header] = once(changed[header],
        '    Q_INVOKABLE void previewScan();', accessors+'    Q_INVOKABLE void previewScan();', header.name)
    changed[header] = once(changed[header],
        '    void previewImageChanged(const QImage &preview);',
        '    void previewImageChanged(const QImage &preview);\n'
        '    void automaticCropChanged();\n'
        '    void automaticDescreenChanged();\n'
        '    void keepOriginalScansChanged();', header.name)
    changed[header] = once(changed[header],
        '    void signalErrorMessage(const QString &text);',
        '    void processIncomingImage(const QImage &image);\n'
        '    void signalErrorMessage(const QString &text);', header.name)

    state = '''    bool m_automaticCrop = false;
    bool m_automaticDescreen = false;
    bool m_keepOriginalScans = false;
    int m_pendingScanProcesses = 0;
'''
    changed[impl] = once(changed[impl], '    QUrl m_dumpOptionUrl;\n',
                         '    QUrl m_dumpOptionUrl;\n'+state, impl.name)

    method = r'''// Experimental scan-output processing.  This runs only for new scans, never
// previews or imported files. All options default OFF.
bool Skanpage::automaticCrop() const { return d->m_automaticCrop; }
void Skanpage::setAutomaticCrop(bool enabled)
{
    if (d->m_automaticCrop == enabled) return;
    d->m_automaticCrop = enabled;
    Q_EMIT automaticCropChanged();
}
bool Skanpage::automaticDescreen() const { return d->m_automaticDescreen; }
void Skanpage::setAutomaticDescreen(bool enabled)
{
    if (d->m_automaticDescreen == enabled) return;
    d->m_automaticDescreen = enabled;
    Q_EMIT automaticDescreenChanged();
}
bool Skanpage::keepOriginalScans() const { return d->m_keepOriginalScans; }
void Skanpage::setKeepOriginalScans(bool enabled)
{
    if (d->m_keepOriginalScans == enabled) return;
    d->m_keepOriginalScans = enabled;
    Q_EMIT keepOriginalScansChanged();
}

// A failed or uncertain filter never discards scan data; add the unprocessed
// image instead. With "keep originals" enabled both copies are available.
void Skanpage::processIncomingImage(const QImage &image)
{
    if (!d->m_automaticCrop && !d->m_automaticDescreen) {
        d->m_documentHandler.addImage(image);
        return;
    }
    const bool keepOriginal = d->m_keepOriginalScans;
    if (keepOriginal) {
        d->m_documentHandler.addImage(image);
    }
    const auto fallback = [this, &image, keepOriginal](const QString &message) {
        if (!keepOriginal) {
            d->m_documentHandler.addImage(image);
        }
        signalErrorMessage(message);
    };
    const QString python = QStandardPaths::findExecutable(QStringLiteral("python3"));
    const QString helperDir = QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation)
        + QStringLiteral("/skanpage-card-tools/");
    const QString scriptFile = helperDir + QStringLiteral("scan_pipeline.py");
    if (python.isEmpty() || !QFileInfo::exists(scriptFile)) {
        fallback(i18n("Scan processing scripts are missing. Saved the original scan instead."));
        return;
    }
    auto directory = std::make_shared<QTemporaryDir>();
    if (!directory->isValid()) {
        fallback(i18n("Could not create a scan processing directory. Saved original scan."));
        return;
    }
    const QString source = directory->filePath(QStringLiteral("scan.png"));
    const QString destination = directory->filePath(QStringLiteral("scan_processed.png"));
    if (!image.save(source, "PNG")) {
        fallback(i18n("Could not prepare scan for processing. Saved original scan."));
        return;
    }
    auto *process = new QProcess(this);
    process->setProgram(python);
    QStringList args{scriptFile, source, QStringLiteral("--output"), destination};
    if (d->m_automaticCrop) args << QStringLiteral("--crop");
    if (d->m_automaticDescreen) args << QStringLiteral("--descreen");
    process->setArguments(args);
    ++d->m_pendingScanProcesses;
    auto finished = std::make_shared<bool>(false);
    const auto complete = [this, process, directory, image, destination, keepOriginal, finished]
                          (bool success, const QString &details) {
        if (*finished) return;
        *finished = true;
        QImage processed;
        if (success) processed.load(destination);
        if (processed.isNull()) {
            if (!keepOriginal) d->m_documentHandler.addImage(image);
            signalErrorMessage(i18n("Scan processing failed; original scan was kept. %1", details));
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
                if (error == QProcess::FailedToStart) complete(false, QStringLiteral("Python failed to start"));
            });
    process->start();
}

'''
    changed[impl] = once(changed[impl],
        'void Skanpage::imageReady(const QImage &image)\n{',
        method+'void Skanpage::imageReady(const QImage &image)\n{', impl.name)
    # Replace the original model insertions ONLY inside imageReady, not elsewhere
    # (manual actions and scanned image import must remain unchanged).
    start = changed[impl].index('void Skanpage::imageReady(const QImage &image)\n{')
    end = changed[impl].index('void Skanpage::previewImageReady(', start)
    old_image_ready = changed[impl][start:end]
    if old_image_ready.count('d->m_documentHandler.addImage(') != 2:
        raise RuntimeError('Unexpected imageReady structure; no files modified.')
    new_image_ready = old_image_ready.replace('d->m_documentHandler.addImage(', 'processIncomingImage(')
    changed[impl] = changed[impl][:start] + new_image_ready + changed[impl][end:]
    changed[impl] = once(changed[impl],
        'if (d->m_documentHandler.isReady() && !d->m_scanInProgress) {',
        'if (d->m_documentHandler.isReady() && !d->m_scanInProgress && d->m_pendingScanProcesses == 0) {',
        impl.name)
    changed[impl] = once(changed[impl],
        'QStringLiteral("card_autocrop.py")', 'QStringLiteral("scan_autocrop.py")', impl.name)

    changed[document] = once(changed[document], 'i18n("Auto Crop Card")',
                             'i18n("Auto Crop")', document.name)
    changed[document] = once(changed[document], 'i18n("Descreen Card")',
                             'i18n("Descreen")', document.name)

    controls = r'''    // These are application-side output operations, not hardware scan options.
    GroupBox {
        title: i18n("Scan output")
        Layout.fillWidth: true
        visible: !optionPanel.editMode
        enabled: skanpage.applicationState === Skanpage.ReadyForScan
        ColumnLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing
            Label {
                text: i18n("Output scan area:")
                Layout.fillWidth: true
            }
            ComboBox {
                Layout.fillWidth: true
                model: [i18n("Scanner selected area"), i18n("Automatic (detect object)")]
                currentIndex: skanpage.automaticCrop ? 1 : 0
                onActivated: function(index) { skanpage.automaticCrop = (index === 1) }
            }
            CheckBox {
                text: i18n("Descreen")
                checked: skanpage.automaticDescreen
                onToggled: skanpage.automaticDescreen = checked
            }
            CheckBox {
                text: i18n("Keep original scans")
                checked: skanpage.keepOriginalScans
                onToggled: skanpage.keepOriginalScans = checked
            }
        }
    }

'''
    changed[options] = once(changed[options],
        '    ScrollView {\n        id: optionsList',
        controls+'    ScrollView {\n        id: optionsList', options.name)

    # Validate all files in memory first; only then create backup and write.
    backup = root / '.scan_tools_v2_backup'
    if backup.exists():
        raise RuntimeError(f'Backup directory already exists ({backup}); refusing to overwrite it.')
    backup.mkdir()
    for p in paths:
        shutil.copy2(p, backup / p.name)
    for p in paths:
        p.write_text(changed[p], encoding='utf-8')
        print('Updated:', p.relative_to(root))
    print('Backup saved in:', backup)
    print('Ready: cmake --build build -j 4')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python3 upgrade_to_v2.py PATH_TO_EXISTING_V1_SKANPAGE_SOURCE')
    main(sys.argv[1])
