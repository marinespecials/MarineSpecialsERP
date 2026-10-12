"""Suppliers: names, ΑΦΜ, recognition keywords, payment terms."""
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QDialog, QFormLayout, QLineEdit, QPlainTextEdit, QSpinBox, QDialogButtonBox,
    QMessageBox, QFileDialog)

from .common import money


class NumItem(QTableWidgetItem):
    """Sorts by the number, shows formatted text."""

    def __init__(self, value, text):
        super().__init__(text)
        self.value = value
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        return self.value < getattr(other, "value", 0)


class SupplierDialog(QDialog):
    def __init__(self, parent, s=None):
        super().__init__(parent)
        self.setWindowTitle("Supplier" if s else "New supplier")
        self.setMinimumWidth(460)
        s = s or {"name": "", "vats": [], "keywords": [], "payment_terms_days": 0, "notes": ""}
        lay = QFormLayout(self)
        self.name = QLineEdit(s["name"])
        self.vats = QLineEdit(", ".join(s["vats"]))
        self.vats.setPlaceholderText("094123456, …")
        self.keywords = QPlainTextEdit("\n".join(s["keywords"]))
        self.keywords.setPlaceholderText("Text printed on their invoices, one per line\ne.g. ΙΣΧΥΣ")
        self.keywords.setMaximumHeight(110)
        self.terms = QSpinBox()
        self.terms.setRange(0, 365)
        self.terms.setSuffix(" days")
        self.terms.setValue(int(s["payment_terms_days"] or 0))
        self.notes = QLineEdit(s["notes"])
        lay.addRow("Name (used in file names)", self.name)
        lay.addRow("ΑΦΜ / VAT numbers", self.vats)
        lay.addRow("Recognise by text", self.keywords)
        lay.addRow("Payment terms", self.terms)
        lay.addRow("Notes", self.notes)
        hint = QLabel("ΑΦΜ is the most reliable way to recognise a supplier. Text matching ignores accents "
                      "and capitals and needs whole words.", objectName="muted", wordWrap=True)
        lay.addRow(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.check)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def check(self):
        bad = [v for v in self.vat_list() if not re.fullmatch(r"\d{9}", v)]
        if not self.name.text().strip():
            QMessageBox.warning(self, "Supplier", "Name is required.")
        elif bad:
            QMessageBox.warning(self, "Supplier", f"ΑΦΜ must be 9 digits: {', '.join(bad)}")
        else:
            self.accept()

    def vat_list(self):
        return [v.strip().upper().removeprefix("EL").removeprefix("GR") for v in re.split(r"[,\s;]+", self.vats.text()) if v.strip()]

    def values(self):
        return dict(name=self.name.text().strip(), vats=self.vat_list(),
                    keywords=[k.strip() for k in self.keywords.toPlainText().splitlines() if k.strip()],
                    payment_terms_days=self.terms.value(), notes=self.notes.text())


class SuppliersPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        head = QHBoxLayout()
        t = QLabel("Suppliers")
        t.setObjectName("pageTitle")
        head.addWidget(t)
        head.addStretch()
        for text, fn, primary in (("Import v1 rules…", self.import_rules, False), ("Delete", self.delete, False),
                                  ("Edit…", self.edit, False), ("+ New supplier", self.add, True)):
            b = QPushButton(text)
            if primary:
                b.setObjectName("primary")
            b.clicked.connect(fn)
            head.addWidget(b)
        root.addLayout(head)
        root.addWidget(QLabel("Suppliers are learned automatically when you approve invoices. "
                              "Set payment terms here to get due dates.", objectName="muted"))

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Name", "ΑΦΜ", "Recognised by text", "Terms", "Invoices", "Total spend"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(lambda _: self.edit())
        root.addWidget(self.table, 1)
        ctx.suppliers_changed.connect(self.reload)
        ctx.invoices_changed.connect(self.reload)
        self.reload()

    def reload(self):
        spend = {r["supplier_name"]: r for r in self.ctx.db.supplier_spend()}
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for s in self.ctx.suppliers():
            row = self.table.rowCount()
            self.table.insertRow(row)
            sp = spend.get(s["name"], {})
            vals = [s["name"], ", ".join(s["vats"]), ", ".join(s["keywords"]),
                    f"{s['payment_terms_days']} days" if s["payment_terms_days"] else "on receipt",
                    sp.get("n", 0), sp.get("spend") or 0]
            for c, v in enumerate(vals):
                if c == 4:
                    it = NumItem(v, str(v))
                elif c == 5:
                    it = NumItem(v, money(v) or "–")
                else:
                    it = QTableWidgetItem(str(v))
                it.setData(Qt.UserRole + 1, s["id"])
                self.table.setItem(row, c, it)
        self.table.setSortingEnabled(True)

    def selected_id(self):
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        return it.data(Qt.UserRole + 1) if it else None

    def add(self):
        d = SupplierDialog(self)
        if d.exec():
            v = d.values()
            if self.ctx.db.supplier_by_name(v["name"]):
                QMessageBox.warning(self, "Supplier", "A supplier with that name exists already.")
                return
            self.ctx.db.save_supplier(**v)
            self.ctx.suppliers_updated()

    def edit(self):
        sid = self.selected_id()
        if not sid:
            return
        d = SupplierDialog(self, self.ctx.db.supplier(sid))
        if d.exec():
            self.ctx.db.save_supplier(sid=sid, **d.values())
            self.ctx.suppliers_updated()
            self.ctx.invoices_changed.emit()

    def delete(self):
        sid = self.selected_id()
        if sid and QMessageBox.question(self, "Delete", "Delete this supplier? Filed invoices are kept.") == QMessageBox.Yes:
            self.ctx.db.delete_supplier(sid)
            self.ctx.suppliers_updated()

    def import_rules(self):
        path, _ = QFileDialog.getOpenFileName(self, "v1 supplier_rules.json", "", "JSON (*.json)")
        if path:
            try:
                n, _ = self.ctx.db.import_legacy(rules_path=path)
                self.ctx.suppliers_updated()
                QMessageBox.information(self, "Imported", f"{n} new suppliers imported.")
            except Exception as e:
                QMessageBox.warning(self, "Import failed", str(e))
