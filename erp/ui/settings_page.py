"""Settings: folders, company, email, myDATA, stock tracker, updates, data."""
import os
import re
import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QCheckBox, QComboBox, QSpinBox,
    QGroupBox, QFormLayout, QScrollArea, QFrame, QMessageBox, QFileDialog, QSizePolicy)

from .. import VERSION, mydata, stock, email_inbox, ocr, paths, filing
from . import common


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
        self.w = {}   # settings key -> widget

        # ---- filing
        g, f = self.group("Folders && filing")
        self.folder_row(f, "Inbox (input) folder", "input_folder")
        self.folder_row(f, "Archive (output) folder", "output_folder")
        layout = QComboBox()
        layout.addItem("Archive / Year / Supplier / file.pdf", "year_supplier")
        layout.addItem("Archive / file.pdf (flat, like v1)", "flat")
        self.w["folder_layout"] = layout
        f.addRow("Archive layout", layout)
        self.w["own_vat_numbers"] = QLineEdit(placeholderText="our ΑΦΜ - never mistaken for a supplier")
        f.addRow("Our company ΑΦΜ", self.w["own_vat_numbers"])
        self.w["default_terms_days"] = QSpinBox(maximum=365, suffix=" days", specialValueText="none (no due date)")
        f.addRow("Default payment terms", self.w["default_terms_days"])
        self.w["auto_file"] = QCheckBox("Automatically file invoices that are recognised with confidence "
                                        "(supplier known + number + date)")
        f.addRow("", self.w["auto_file"])
        self.w["label_url"] = QLineEdit()
        f.addRow("QR label link", self.w["label_url"])
        theme = QComboBox()
        for label, key in (("Follow Windows", "system"), ("Light", "light"), ("Dark", "dark")):
            theme.addItem(label, key)
        self.w["theme"] = theme
        f.addRow("Theme", theme)
        self.w["ocr_languages"] = QLineEdit()
        f.addRow("OCR languages", self.w["ocr_languages"])
        self.ocr_status = QLabel(objectName="muted", wordWrap=True)
        f.addRow("", self.ocr_status)

        # ---- email
        g, f = self.group("Email inbox (IMAP) — PDFs attached to new emails land in the inbox")
        self.w["imap_enabled"] = QCheckBox("Check email automatically")
        f.addRow("", self.w["imap_enabled"])
        self.w["imap_host"] = QLineEdit(placeholderText="imap.gmail.com")
        self.w["imap_port"] = QSpinBox(maximum=65535)
        self.w["imap_user"] = QLineEdit(placeholderText="invoices@yourcompany.gr")
        self.imap_password = QLineEdit(echoMode=QLineEdit.Password, placeholderText="app password (stored in Windows Credential Manager)")
        self.w["imap_folder"] = QLineEdit()
        self.w["imap_interval_min"] = QSpinBox(minimum=1, maximum=1440, suffix=" min")
        self.w["imap_mark_read"] = QCheckBox("Mark checked emails as read")
        for label, key in (("Server", "imap_host"), ("Port", "imap_port"), ("User", "imap_user")):
            f.addRow(label, self.w[key])
        f.addRow("Password", self.imap_password)
        f.addRow("Folder", self.w["imap_folder"])
        f.addRow("Check every", self.w["imap_interval_min"])
        f.addRow("", self.w["imap_mark_read"])
        f.addRow("", self.button("Test connection", self.test_email))
        f.addRow(QLabel("Gmail: use an App Password. Microsoft 365 blocks password IMAP - forward invoices to a "
                        "Gmail box instead.", objectName="muted", wordWrap=True))

        # ---- myDATA
        g, f = self.group("AADE myDATA — exact data for Greek invoices via ΜΑΡΚ")
        self.w["mydata_enabled"] = QCheckBox("Download received invoices from myDATA (every 6 hours)")
        f.addRow("", self.w["mydata_enabled"])
        self.w["mydata_user"] = QLineEdit(placeholderText="myDATA REST API username")
        self.mydata_key = QLineEdit(echoMode=QLineEdit.Password, placeholderText="subscription key (Κωδικός API)")
        self.w["mydata_test_env"] = QCheckBox("Use AADE test environment")
        f.addRow("User (aade-user-id)", self.w["mydata_user"])
        f.addRow("Subscription key", self.mydata_key)
        f.addRow("", self.w["mydata_test_env"])
        self.mydata_status = QLabel(objectName="muted")
        f.addRow("", self.mydata_status)
        f.addRow("", self.button("Sync now", self.sync_mydata))
        f.addRow(QLabel("Get credentials at mydata.aade.gr → «Εγγραφή στο myDATA REST API». "
                        "Read-only: the app only downloads invoices issued to you.", objectName="muted", wordWrap=True))

        # ---- stock
        g, f = self.group("Stock tracker — send received items to your Render app")
        self.w["stock_enabled"] = QCheckBox("Enable stock tracker sync")
        f.addRow("", self.w["stock_enabled"])
        self.w["stock_url"] = QLineEdit(placeholderText="https://marine-specials-tracker.onrender.com/api/receipts")
        self.stock_key = QLineEdit(echoMode=QLineEdit.Password, placeholderText="API key (optional)")
        self.w["stock_auto_send"] = QCheckBox("Send items automatically when an invoice is filed")
        f.addRow("Endpoint URL", self.w["stock_url"])
        f.addRow("API key", self.stock_key)
        f.addRow("", self.w["stock_auto_send"])
        row = QHBoxLayout()
        row.addWidget(self.button("Test connection", self.test_stock))
        row.addWidget(self.button("Send pending now", self.flush_stock))
        row.addStretch()
        f.addRow("", row)
        f.addRow(QLabel("The tracker needs a POST endpoint - format is in README (\"Stock tracker\").",
                        objectName="muted", wordWrap=True))

        # ---- updates
        g, f = self.group("Updates")
        f.addRow("Installed version", QLabel(f"v{VERSION}"))
        self.w["update_check"] = QCheckBox("Check for updates when the app starts")
        f.addRow("", self.w["update_check"])
        b = self.button("Check for updates now", lambda: self.check_updates_requested.emit())
        f.addRow("", b)

        # ---- data
        g, f = self.group("Data")
        f.addRow("Database", QLabel(ctx.db.path, objectName="muted", textInteractionFlags=Qt.TextSelectableByMouse))
        row = QHBoxLayout()
        row.addWidget(self.button("Open data folder", lambda: filing.open_path(paths.data_dir())))
        row.addWidget(self.button("Back up database…", self.backup))
        row.addWidget(self.button("Import from v1.x…", self.import_v1))
        row.addStretch()
        f.addRow("", row)

        self.lay.addStretch()
        self.load()

    # ------------------------------------------------------------------ helpers
    def group(self, title):
        g = QGroupBox(title)
        f = QFormLayout(g)
        f.setLabelAlignment(Qt.AlignRight)
        self.lay.addWidget(g)
        return g, f

    def button(self, text, fn):
        b = QPushButton(text)
        b.clicked.connect(fn)
        b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        return b

    def folder_row(self, form, label, key):
        e = QLineEdit()
        self.w[key] = e
        row = QHBoxLayout()
        row.addWidget(e, 1)
        b = QPushButton("Browse…")
        b.clicked.connect(lambda: (d := QFileDialog.getExistingDirectory(self, label, e.text() or os.path.expanduser("~")))
                          and e.setText(d))
        row.addWidget(b)
        form.addRow(label, row)

    def load(self):
        s = self.ctx.settings
        for key, w in self.w.items():
            v = s.get(key)
            if isinstance(w, QCheckBox):
                w.setChecked(bool(v))
            elif isinstance(w, QSpinBox):
                w.setValue(int(v or 0))
            elif isinstance(w, QComboBox):
                w.setCurrentIndex(max(0, w.findData(v)))
            elif key == "own_vat_numbers":
                w.setText(", ".join(v or []))
            else:
                w.setText(str(v or ""))
        self.imap_password.setText(self.ctx.secret("imap_password"))
        self.mydata_key.setText(self.ctx.secret("mydata_key"))
        self.stock_key.setText(self.ctx.secret("stock_api_key"))
        self.mydata_status.setText(f"{self.ctx.db.mydata_count()} myDATA documents cached"
                                   + (f" · last sync {s.get('mydata_last_sync')}" if s.get("mydata_last_sync") else ""))
        probs = ocr.problems()
        self.ocr_status.setText("✔ OCR ready (" + (ocr.languages() or "") + ")" if not probs else "⚠ " + " ".join(probs))

    def values(self):
        out = {}
        for key, w in self.w.items():
            if isinstance(w, QCheckBox):
                out[key] = w.isChecked()
            elif isinstance(w, QSpinBox):
                out[key] = w.value()
            elif isinstance(w, QComboBox):
                out[key] = w.currentData()
            elif key == "own_vat_numbers":
                out[key] = re.findall(r"\d{9}", w.text())
            else:
                out[key] = w.text().strip()
        return out

    def save(self, quiet=False):
        old_theme = self.ctx.settings.get("theme")
        self.ctx.set_secret("imap_password", self.imap_password.text())
        self.ctx.set_secret("mydata_key", self.mydata_key.text().strip())
        self.ctx.set_secret("stock_api_key", self.stock_key.text().strip())
        self.ctx.save_settings(self.values())
        if self.ctx.settings.get("theme") != old_theme:
            self.theme_changed.emit(self.ctx.settings.get("theme"))
        if not quiet:
            self.ctx.status.emit("Settings saved")

    # ------------------------------------------------------------------ tests / actions
    def _report(self, title):
        return (lambda res: QMessageBox.information(self, title, res[1]) if res[0] else QMessageBox.warning(self, title, res[1]),
                lambda e: QMessageBox.warning(self, title, str(e)))

    def test_email(self):
        v = self.values()
        pw = self.imap_password.text()
        ok, err = self._report("Email")
        common.run_async(lambda: email_inbox.test(v["imap_host"], v["imap_port"], v["imap_user"], pw, v["imap_folder"]), ok, err)

    def test_stock(self):
        url, key = self.w["stock_url"].text().strip(), self.stock_key.text().strip()
        ok, err = self._report("Stock tracker")
        common.run_async(lambda: stock.test(url, key), ok, err)

    def flush_stock(self):
        self.save(quiet=True)
        url, key = self.ctx.settings.get("stock_url"), self.stock_key.text().strip()
        common.run_async(lambda: stock.flush(self.ctx.db, url, key),
                         lambda r: (self.ctx.invoices_changed.emit(),
                                    QMessageBox.information(self, "Stock tracker", f"Sent {r[0]}, failed {r[1]}\n{r[2]}")),
                         lambda e: QMessageBox.warning(self, "Stock tracker", str(e)))

    def sync_mydata(self, quiet=False):
        if not quiet:
            self.save(quiet=True)
        s = self.ctx.settings
        user, key = s.get("mydata_user"), self.ctx.secret("mydata_key")
        if not user or not key:
            if not quiet:
                QMessageBox.information(self, "myDATA", "Enter the myDATA user and subscription key first.")
            return
        self.mydata_status.setText("Syncing…")

        def done(n):
            self.ctx.db.set("mydata_last_sync", datetime.datetime.now().strftime("%d/%m/%Y %H:%M"))
            self.ctx.reload_settings()
            self.load()
            self.ctx.suppliers_changed.emit()   # re-check inbox against the new ΜΑΡΚ data
            self.ctx.status.emit(f"myDATA: {n} received invoices synced")

        def failed(e):
            self.load()
            self.ctx.status.emit(f"myDATA sync failed: {e}")
            if not quiet:
                QMessageBox.warning(self, "myDATA", str(e))

        common.run_async(lambda: mydata.sync(self.ctx.db, user, key, 120, s.get("mydata_test_env")), done, failed)

    def backup(self):
        name = f"MarineSpecialsERP_backup_{datetime.datetime.now():%Y%m%d_%H%M}.db"
        path, _ = QFileDialog.getSaveFileName(self, "Back up database", os.path.join(os.path.expanduser("~"), name),
                                              "Database (*.db)")
        if path:
            import sqlite3
            src = sqlite3.connect(self.ctx.db.path)
            dst = sqlite3.connect(path)
            src.backup(dst)
            dst.close()
            src.close()
            self.ctx.status.emit(f"Backup saved: {path}")

    def import_v1(self):
        folder = QFileDialog.getExistingDirectory(self, "Folder of the old app (with supplier_rules.json)")
        rules = os.path.join(folder, "supplier_rules.json") if folder else None
        ledger_folder = QFileDialog.getExistingDirectory(self, "Old archive folder (with invoice_ledger.csv) - Cancel to skip")
        ledger = os.path.join(ledger_folder, "invoice_ledger.csv") if ledger_folder else None
        try:
            s, i = self.ctx.db.import_legacy(rules, ledger)
            self.ctx.suppliers_updated()
            self.ctx.invoices_changed.emit()
            QMessageBox.information(self, "Imported", f"{s} suppliers and {i} invoices imported.")
        except Exception as e:
            QMessageBox.warning(self, "Import failed", str(e))
