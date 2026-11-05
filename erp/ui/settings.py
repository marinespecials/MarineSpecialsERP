"""Settings: folders, naming, scanning, updates."""
import os
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QCheckBox, QComboBox,
                               QGroupBox, QFormLayout, QScrollArea, QFrame, QFileDialog, QMessageBox, QSizePolicy)

from .. import VERSION, drive, naming, ocr, paths
from . import common

EXAMPLE = {"vat": "094123456", "invoice": "4587", "date": "2026-09-03", "company": "Ισχύς Α.Ε.", "mark": "400001234567890"}


class SettingsPage(QWidget):
    check_updates_requested = Signal()
    theme_changed = Signal(str)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        head = QHBoxLayout()
        t = QLabel("Settings")
        t.setObjectName("pageTitle")
        head.addWidget(t)
        head.addStretch()
        save = QPushButton("💾 Save settings", objectName="primary")
        save.clicked.connect(self.save)
        head.addWidget(save)
        outer.addLayout(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        self.lay = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self.w = {}

        f = self.group("Folders")
        self.folder_row(f, "Inbox (scanner saves here)", "input_folder")
        self.folder_row(f, "Google Drive folder", "drive_folder", detect=True)
        f.addRow("", QLabel("Install <b>Google Drive for desktop</b> and pick a folder inside <i>G:\\My Drive</i> "
                            "(Το Drive μου). Files saved there upload to Drive automatically.",
                            objectName="muted", wordWrap=True))
        self.w["subfolder_template"] = QLineEdit(placeholderText="none - or e.g. {year}   {year}/{month}   {supplier}")
        f.addRow("Subfolders in Drive", self.w["subfolder_template"])
        after = QComboBox()
        after.addItem("Move the original scan to Inbox\\_done", "done")
        after.addItem("Leave the original in the inbox", "keep")
        self.w["after_send"] = after
        f.addRow("After sending", after)

        f = self.group("File names")
        self.w["name_template"] = QLineEdit()
        self.w["name_template"].textChanged.connect(self.update_example)
        f.addRow("Name pattern", self.w["name_template"])
        fmt = QComboBox()
        for label, v in (("2026-09-03", "%Y-%m-%d"), ("03-09-2026", "%d-%m-%Y"), ("03.09.2026", "%d.%m.%Y"), ("20260903", "%Y%m%d")):
            fmt.addItem(label, v)
        fmt.currentIndexChanged.connect(self.update_example)
        self.w["date_format"] = fmt
        f.addRow("Date format", fmt)
        self.example = QLabel(objectName="muted")
        f.addRow("Example", self.example)
        f.addRow("", QLabel("Fields: {supplier} {invoice} {date} {year} {month} {vat} {mark} {original} {n}. "
                            "Empty fields are skipped. When you correct a supplier name, the app remembers it "
                            "for that ΑΦΜ next time.", objectName="muted", wordWrap=True))
        self.w["own_vat_numbers"] = QLineEdit(placeholderText="our company ΑΦΜ - never used as the supplier")
        f.addRow("Our ΑΦΜ", self.w["own_vat_numbers"])
        self.names_label = QLabel(objectName="muted")
        clear = QPushButton("Forget learned names")
        clear.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        clear.clicked.connect(self.clear_names)
        row = QHBoxLayout()
        row.addWidget(self.names_label)
        row.addWidget(clear)
        row.addStretch()
        f.addRow("Learned suppliers", row)

        f = self.group("Scans")
        self.w["smart_split_on_open"] = QCheckBox("Smart split automatically when a PDF is opened")
        self.w["auto_rotate"] = QCheckBox("Straighten sideways / upside-down scanned pages")
        self.w["remove_blank"] = QCheckBox("Remove blank pages (empty backs of double-sided scans)")
        for k in ("smart_split_on_open", "auto_rotate", "remove_blank"):
            f.addRow("", self.w[k])
        self.w["ocr_languages"] = QLineEdit()
        f.addRow("OCR languages", self.w["ocr_languages"])
        self.ocr_status = QLabel(objectName="muted", wordWrap=True)
        f.addRow("", self.ocr_status)

        f = self.group("Appearance && updates")
        theme = QComboBox()
        for label, v in (("Follow Windows", "system"), ("Light", "light"), ("Dark", "dark")):
            theme.addItem(label, v)
        self.w["theme"] = theme
        f.addRow("Theme", theme)
        f.addRow("Version", QLabel(f"v{VERSION}"))
        self.w["update_check"] = QCheckBox("Check for updates when the app starts")
        f.addRow("", self.w["update_check"])
        b = QPushButton("Check for updates now")
        b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        b.clicked.connect(lambda: self.check_updates_requested.emit())
        f.addRow("", b)
        b2 = QPushButton("Open data folder")
        b2.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        b2.clicked.connect(lambda: common.open_path(paths.data_dir()))
        f.addRow("", b2)
        self.lay.addStretch()
        self.load()
        ctx.settings_changed.connect(self.load)

    def group(self, title):
        g = QGroupBox(title)
        f = QFormLayout(g)
        f.setLabelAlignment(Qt.AlignRight)
        self.lay.addWidget(g)
        return f

    def folder_row(self, form, label, key, detect=False):
        e = QLineEdit()
        self.w[key] = e
        row = QHBoxLayout()
        row.addWidget(e, 1)
        b = QPushButton("Browse…")
        b.clicked.connect(lambda: (d := QFileDialog.getExistingDirectory(self, label, e.text() or os.path.expanduser("~")))
                          and e.setText(os.path.normpath(d)))
        row.addWidget(b)
        if detect:
            d = QPushButton("Find Drive")
            d.clicked.connect(lambda: self.detect_drive(e))
            row.addWidget(d)
        form.addRow(label, row)

    def detect_drive(self, edit):
        found = drive.candidates()
        if not found:
            QMessageBox.information(self, "Google Drive", "Couldn't find Google Drive for desktop on this PC.\n\n"
                                    "Install it from google.com/drive/download, sign in, then try again - "
                                    "or choose any folder with Browse.")
            return
        base = found[0]
        sub = QFileDialog.getExistingDirectory(self, "Choose the Drive folder for invoices", base)
        edit.setText(os.path.normpath(sub or base))

    def load(self):
        s = self.ctx.settings
        for key, w in self.w.items():
            v = s.get(key)
            if isinstance(w, QCheckBox):
                w.setChecked(bool(v))
            elif isinstance(w, QComboBox):
                w.setCurrentIndex(max(0, w.findData(v)))
            elif key == "own_vat_numbers":
                w.setText(", ".join(v or []))
            else:
                w.setText(str(v or ""))
        n = len(self.ctx.store.names)
        self.names_label.setText(f"{n} supplier name(s) remembered")
        probs = ocr.problems()
        self.ocr_status.setText(("✔ OCR ready (" + (ocr.languages() or "") + ")") if not probs else "⚠ " + " ".join(probs))
        self.update_example()

    def values(self):
        out = {}
        for key, w in self.w.items():
            if isinstance(w, QCheckBox):
                out[key] = w.isChecked()
            elif isinstance(w, QComboBox):
                out[key] = w.currentData()
            elif key == "own_vat_numbers":
                out[key] = re.findall(r"\d{9}", w.text())
            else:
                out[key] = w.text().strip()
        out["name_template"] = out["name_template"] or naming.DEFAULT_TEMPLATE
        return out

    def update_example(self, *_):
        tpl = self.w["name_template"].text() or naming.DEFAULT_TEMPLATE
        fmt = self.w["date_format"].currentData() or "%Y-%m-%d"
        name = naming.suggest(EXAMPLE, {"094123456": "ΙΣΧΥΣ_ΑΕ"}, "Scan1.pdf", 1, tpl, fmt)
        self.example.setText(f"{name}.pdf")

    def clear_names(self):
        if QMessageBox.question(self, "Forget names", "Forget all supplier names the app has learned?") == QMessageBox.Yes:
            self.ctx.store.names.clear()
            self.ctx.store.save_names()
            self.load()

    def save(self):
        v = self.values()
        old_theme = self.ctx.settings.get("theme")
        if v.get("drive_folder") and not os.path.isdir(v["drive_folder"]):
            QMessageBox.warning(self, "Drive folder", "That Drive folder doesn't exist (is Google Drive running?).")
        self.ctx.save_settings(v)
        if v["theme"] != old_theme:
            self.theme_changed.emit(v["theme"])
        self.ctx.status.emit("Settings saved")
