# SPDX-License-Identifier: GPL-3.0-only
#!/usr/bin/env python3
# Apply opt-in card processing actions to a recent KDE Skanpage checkout.
# Usage: python3 patch_skanpage.py /path/to/skanpage
from pathlib import Path
import sys


def replace_once(text, old, new, filename):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{filename}: expected one matching insertion point, got {count}. "
                           "Source version may have changed; no files modified.")
    return text.replace(old, new, 1)


def main(source):
    source = Path(source).expanduser().resolve()
    header = source/'src/Skanpage.h'
    impl = source/'src/Skanpage.cpp'
    qml = source/'src/qml/DocumentPage.qml'
    paths = [header,impl,qml]
    inputs = {p:p.read_text(encoding='utf-8') for p in paths}
    if any('applyCardTool(' in s for s in inputs.values()):
        raise RuntimeError('This source checkout already appears to be patched; stopping.')
    changed = dict(inputs)

    changed[header] = replace_once(changed[header],
        '    Q_INVOKABLE void importFile(const QUrl &fileUrl);',
        '    Q_INVOKABLE void importFile(const QUrl &fileUrl);\n'
        '    Q_INVOKABLE void applyCardTool(int pageIndex, const QString &action, int referencePageIndex, bool rotateReference, const QString &band);',
        header.name)

    extra_headers = '''#include <QFileInfo>
#include <QProcess>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <memory>
'''
    changed[impl] = replace_once(changed[impl], '#include <QFile>\n', '#include <QFile>\n'+extra_headers, impl.name)

    processing_method = r'''// Experimental scan post-processing, using separate optional Python helpers.
// Originals remain in the document; results are appended as new pages.
void Skanpage::applyCardTool(int pageIndex, const QString &action, int referencePageIndex,
                             bool rotateReference, const QString &band)
{
    if (action != QStringLiteral("crop") && action != QStringLiteral("descreen")
        && action != QStringLiteral("repair")) {
        signalErrorMessage(i18n("Unknown card processing action."));
        return;
    }
    auto pageFile = [this](int i) -> QString {
        if (i < 0 || i >= d->m_documentHandler.rowCount()) {
            return {};
        }
        return d->m_documentHandler.data(d->m_documentHandler.index(i, 0), DocumentModel::ImageUrlRole)
            .toUrl().toLocalFile();
    };
    const QString sourceFile = pageFile(pageIndex);
    if (sourceFile.isEmpty() || !QFileInfo::exists(sourceFile)) {
        signalErrorMessage(i18n("The selected page has not finished saving yet."));
        return;
    }
    QString refFile;
    if (action == QStringLiteral("repair")) {
        refFile = pageFile(referencePageIndex);
        if (referencePageIndex == pageIndex || refFile.isEmpty() || !QFileInfo::exists(refFile)) {
            signalErrorMessage(i18n("Choose a different, saved page as the stripe repair reference."));
            return;
        }
        // Validate the band before starting a subprocess, without accepting extra arguments.
        const auto parts = band.split(QLatin1Char(':'));
        bool okA = false, okB = false;
        const double a = parts.value(0).toDouble(&okA);
        const double b = parts.value(1).toDouble(&okB);
        if (parts.size() != 2 || !okA || !okB || a < 0 || a >= b) {
            signalErrorMessage(i18n("Stripe rows must be START:END, such as 0.895:0.915."));
            return;
        }
    }
    const QString scriptName = action == QStringLiteral("crop") ? QStringLiteral("card_autocrop.py")
        : action == QStringLiteral("descreen") ? QStringLiteral("card_descreen.py")
        : QStringLiteral("card_stripe_repair.py");
    const QString helperDir = QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation)
        + QStringLiteral("/skanpage-card-tools/");
    const QString scriptFile = helperDir + scriptName;
    if (!QFileInfo(scriptFile).isFile()) {
        signalErrorMessage(i18n("Card helper script not installed: %1", scriptFile));
        return;
    }
    const QString python = QStandardPaths::findExecutable(QStringLiteral("python3"));
    if (python.isEmpty()) {
        signalErrorMessage(i18n("Python 3 was not found in PATH."));
        return;
    }

    auto workingDir = std::make_shared<QTemporaryDir>();
    if (!workingDir->isValid()) {
        signalErrorMessage(i18n("Could not create temporary processing directory."));
        return;
    }
    const QString mainFile = workingDir->filePath(QStringLiteral("main.png"));
    if (!QFile::copy(sourceFile, mainFile)) {
        signalErrorMessage(i18n("Could not copy the scanned page for processing."));
        return;
    }
    QStringList arguments{scriptFile, mainFile};
    if (action == QStringLiteral("repair")) {
        const QString refCopy = workingDir->filePath(QStringLiteral("reference.png"));
        if (!QFile::copy(refFile, refCopy)) {
            signalErrorMessage(i18n("Could not copy the reference page."));
            return;
        }
        arguments << refCopy << QStringLiteral("--band") << band;
        if (rotateReference) {
            arguments << QStringLiteral("--rotate-reference");
        }
    }
    const QString resultName = action == QStringLiteral("crop") ? QStringLiteral("main_cropped.png")
        : action == QStringLiteral("descreen") ? QStringLiteral("main_descreened.png")
        : QStringLiteral("main_repaired.png");
    const QString resultFile = workingDir->filePath(resultName);
    auto *process = new QProcess(this);
    process->setProgram(python);
    process->setArguments(arguments);
    connect(process, QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished), this,
            [this, process, workingDir, resultFile](int exitCode, QProcess::ExitStatus status) {
        if (exitCode != 0 || status != QProcess::NormalExit) {
            const QString details = QString::fromLocal8Bit(process->readAllStandardError()).right(650);
            signalErrorMessage(i18n("Card processing failed: %1", details));
        } else {
            QImage processed(resultFile);
            if (processed.isNull()) {
                signalErrorMessage(i18n("Card processing returned no readable PNG."));
            } else {
                d->m_documentHandler.addImage(processed);
                showUserMessage(SkanpageUtils::InformationMessage, i18n("Processed card added as a new page."));
            }
        }
        process->deleteLater();
    });
    connect(process, &QProcess::errorOccurred, this, [this, process](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) {
            signalErrorMessage(i18n("Could not start the Python card processing helper."));
            process->deleteLater();
        }
    });
    process->start();
}

'''
    changed[impl] = replace_once(changed[impl], 'void Skanpage::importFile(const QUrl &fileUrl)\n{',
                                  processing_method+'void Skanpage::importFile(const QUrl &fileUrl)\n{',impl.name)

    new_actions = r'''                ShortcutsAction {
                    icon.name: "transform-crop"
                    text: i18n("Auto Crop Card")
                    enabled: skanpage.documentModel.isReady
                    onTriggered: skanpage.applyCardTool(skanpage.documentModel.activePageIndex, "crop", -1, false, "")
                },

                ShortcutsAction {
                    icon.name: "image-x-generic"
                    text: i18n("Descreen Card")
                    enabled: skanpage.documentModel.isReady
                    onTriggered: skanpage.applyCardTool(skanpage.documentModel.activePageIndex, "descreen", -1, false, "")
                },

                ShortcutsAction {
                    icon.name: "document-edit"
                    text: i18n("Repair Scan Stripe…")
                    enabled: skanpage.documentModel.count >= 2 && skanpage.documentModel.isReady
                    onTriggered: stripeRepairDialog.open()
                },

'''
    changed[qml] = replace_once(changed[qml],
        '                ShortcutsAction {\n                    id: savePageAction\n',
        new_actions+'                ShortcutsAction {\n                    id: savePageAction\n',qml.name)

    dialog = r'''
    Dialog {
        id: stripeRepairDialog
        parent: Overlay.overlay
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        width: Math.min(440, parent.width - 24)
        modal: true
        title: i18n("Repair stripe using another scan")
        standardButtons: Dialog.Ok | Dialog.Cancel
        onOpened: {
            referencePageNumber.to = Math.max(1, skanpage.documentModel.count)
            referencePageNumber.value = Math.min(skanpage.documentModel.count,
                                                skanpage.documentModel.activePageIndex + 2)
        }
        onAccepted: skanpage.applyCardTool(skanpage.documentModel.activePageIndex, "repair",
                                          referencePageNumber.value - 1,
                                          rotateReference.checked, stripeBand.text.trim())
        contentItem: ColumnLayout {
            spacing: 8
            Label {
                text: i18n("First select the damaged page. Use a second scan of the same card as reference.")
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            Label { text: i18n("Reference page number:") }
            SpinBox {
                id: referencePageNumber
                from: 1
                to: Math.max(1, skanpage.documentModel.count)
                value: 2
            }
            CheckBox {
                id: rotateReference
                text: i18n("Reference was scanned upside down (rotate 180°)")
                checked: true
            }
            Label { text: i18n("Damaged stripe range (fractions of card height):") }
            TextField {
                id: stripeBand
                Layout.fillWidth: true
                text: "0.895:0.915"
                placeholderText: "0.895:0.915"
            }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: i18n("The default band is tuned to the Flamethrower test card. Inspect the result before saving.")
            }
        }
    }
'''
    # The source sometimes ends with extra blank lines.
    if not changed[qml].rstrip().endswith('}'):
        raise RuntimeError('Unexpected ending of DocumentPage.qml; no files modified.')
    changed[qml] = changed[qml].rstrip()[:-1] + '\n' + dialog + '\n}\n'

    # Validate every replacement before changing files; then save.
    for p in paths:
        p.write_text(changed[p],encoding='utf-8')
        print('Patched',p)
    print('Done. Review changes with: git diff')

if __name__=='__main__':
    if len(sys.argv)!=2:
        raise SystemExit('Usage: python3 patch_skanpage.py PATH_TO_SKANPAGE_SOURCE')
    main(sys.argv[1])
