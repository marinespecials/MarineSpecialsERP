"""Ledger: every filed invoice, payments, search, export."""
import os
import datetime

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QDate
from PySide6.QtGui import QColor, QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QComboBox, QTableView, QHeaderView,
    QAbstractItemView, QMenu, QMessageBox, QFileDialog, QDialog, QFormLayout, QDialogButtonBox, QPlainTextEdit)

from .. import export, filing, stock, parser
from . import common
from .common import Card, money, DateField, GREEN, ORANGE, RED, BLUE

COLUMNS = [("Date", "invoice_date"), ("Supplier", "supplier_name"), ("Invoice #", "invoice_no"),
           ("Total", "total"), ("Due", "due_date"), ("Status", "status"), ("Paid on", "paid_date"),
           ("ΜΑΡΚ", "mark"), ("Stock", "stock_status"), ("Read by", "read_by")]
STATUS_COLOR = {"paid": GREEN, "overdue": RED, "unpaid": ORANGE}
STATUS_TEXT = {"paid": "Paid", "overdue": "Overdue", "unpaid": "Unpaid"}


def fmt_date(iso):
    try:
        return datetime.date.fromisoformat(iso).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return iso or ""


class LedgerModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.rows = []

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section][0]
        return None

    def data(self, index, role=Qt.DisplayRole):
        r = self.rows[index.row()]
        key = COLUMNS[index.column()][1]
        v = r.get(key)
        if role == Qt.DisplayRole:
            if key == "total":
                return money(v)
            if key in ("invoice_date", "due_date", "paid_date"):
                return fmt_date(v)
            if key == "status":
                return STATUS_TEXT[v]
            if key == "stock_status":
                return {"sent": "✔ sent", "pending": "⏳", "failed": "✖ failed"}.get(v, "")
            if key == "read_by":
                return {"text": "PDF text", "ocr": "OCR", "": ""}.get(v, v) + (" · ΜΑΡΚ" if r.get("mark") else "")
            return v
        if role == Qt.UserRole:          # sort key
            if key == "total":
                return float(v or 0)
            return str(v or "")
        if role == Qt.ForegroundRole and key == "status":
            return QColor(STATUS_COLOR[v])
        if role == Qt.ForegroundRole and key == "due_date" and r["status"] == "overdue":
            return QColor(RED)
        if role == Qt.TextAlignmentRole and key == "total":
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ToolTipRole:
            return r.get("file_path") if key != "stock_status" else (r.get("stock_error") or None)
        return None


class Filter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.text = ""
        self.status = "all"
        self.supplier = ""
        self.year = ""
        self.setSortRole(Qt.UserRole)

    def filterAcceptsRow(self, row, parent):
        r = self.sourceModel().rows[row]
        if self.status != "all" and (r["status"] != self.status and not (self.status == "unpaid" and r["status"] == "overdue")):
            return False
        if self.supplier and r["supplier_name"] != self.supplier:
            return False
        if self.year and not (r["invoice_date"] or "").startswith(self.year):
            return False
        if self.text:
            hay = parser.normalize(" ".join(str(r.get(k) or "") for k in ("supplier_name", "invoice_no", "mark",
                                                                            "supplier_vat", "payment_notes", "total")))
            return all(t in hay for t in self.text.split())
        return True


class EditDialog(QDialog):
    def __init__(self, parent, inv):
        super().__init__(parent)
        self.setWindowTitle(f"Invoice {inv['invoice_no']}")
        lay = QFormLayout(self)
        self.supplier = QLineEdit(inv["supplier_name"])
        self.vat = QLineEdit(inv["supplier_vat"])
        self.number = QLineEdit(inv["invoice_no"])
        self.date = DateField()
        self.date.set_iso(inv["invoice_date"])
        self.total = QLineEdit("" if inv["total"] is None else f"{inv['total']:.2f}".replace(".", ","))
        self.due = DateField()
        self.due.set_iso(inv["due_date"])
        self.paid = DateField()
        self.paid.set_iso(inv["paid_date"])
        self.mark = QLineEdit(inv["mark"])
        self.notes = QPlainTextEdit(inv["payment_notes"])
        self.notes.setMaximumHeight(70)
        for label, w in (("Supplier", self.supplier), ("ΑΦΜ", self.vat), ("Invoice #", self.number), ("Date", self.date),
                         ("Total €", self.total), ("Due", self.due), ("Paid on", self.paid), ("ΜΑΡΚ", self.mark),
                         ("Notes", self.notes)):
            lay.addRow(label, w)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def values(self):
        return {"supplier_name": self.supplier.text().strip(), "supplier_vat": self.vat.text().strip(),
                "invoice_no": self.number.text().strip(), "invoice_date": self.date.iso(),
                "total": parser.parse_money(self.total.text()), "due_date": self.due.iso(),
                "paid_date": self.paid.iso(), "mark": self.mark.text().strip(),
                "payment_notes": self.notes.toPlainText()}


class PayDialog(QDialog):
    def __init__(self, parent, count, total):
        super().__init__(parent)
        self.setWindowTitle("Mark as paid")
        lay = QFormLayout(self)
        lay.addRow(QLabel(f"{count} invoice(s), {money(total)}"))
        self.date = DateField()
        self.date.setDate(QDate.currentDate())
        self.notes = QLineEdit(placeholderText="e.g. bank transfer, ref…")
        lay.addRow("Paid on", self.date)
        lay.addRow("Note", self.notes)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)


class LedgerPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)

        head = QHBoxLayout()
        t = QLabel("Ledger")
        t.setObjectName("pageTitle")
        head.addWidget(t)
        head.addStretch()
        exp = QPushButton("📥 Export to Excel")
        exp.clicked.connect(self.export)
        head.addWidget(exp)
        root.addLayout(head)

        cards = QHBoxLayout()
        self.c_unpaid = Card("Unpaid", ORANGE)
        self.c_overdue = Card("Overdue", RED)
        self.c_month = Card("Spend this month", BLUE)
        self.c_year = Card("Spend this year", BLUE)
        for c in (self.c_unpaid, self.c_overdue, self.c_month, self.c_year):
            cards.addWidget(c)
        root.addLayout(cards)

        bar = QHBoxLayout()
        self.search = QLineEdit(placeholderText="🔍 Search supplier, invoice, ΜΑΡΚ, amount…")
        self.status = QComboBox()
        for label, key in (("All", "all"), ("Unpaid", "unpaid"), ("Overdue", "overdue"), ("Paid", "paid")):
            self.status.addItem(label, key)
        self.supplier = QComboBox()
        self.year = QComboBox()
        bar.addWidget(self.search, 2)
        bar.addWidget(QLabel("Status"))
        bar.addWidget(self.status)
        bar.addWidget(QLabel("Supplier"))
        bar.addWidget(self.supplier, 1)
        bar.addWidget(QLabel("Year"))
        bar.addWidget(self.year)
        root.addLayout(bar)

        self.model = LedgerModel()
        self.proxy = Filter()
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.DescendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.menu)
        self.table.doubleClicked.connect(lambda _: self.open_pdf())
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.summary = QLabel("", objectName="muted")
        actions.addWidget(self.summary)
        actions.addStretch()
        for text, fn, primary in (("Open PDF", self.open_pdf, False), ("Edit…", self.edit, False),
                                  ("Mark unpaid", self.mark_unpaid, False), ("✔ Mark paid…", self.mark_paid, True)):
            b = QPushButton(text)
            if primary:
                b.setObjectName("primary")
            b.clicked.connect(fn)
            actions.addWidget(b)
        root.addLayout(actions)

        self.search.textChanged.connect(self.apply_filter)
        self.status.currentIndexChanged.connect(self.apply_filter)
        self.supplier.currentIndexChanged.connect(self.apply_filter)
        self.year.currentIndexChanged.connect(self.apply_filter)
        ctx.invoices_changed.connect(self.reload)
        ctx.suppliers_changed.connect(self.reload)
        self.reload()

    # ------------------------------------------------------------------ data
    def reload(self):
        rows = self.ctx.db.invoices()
        self.model.set_rows(rows)
        for combo, values in ((self.supplier, sorted({r["supplier_name"] for r in rows}, key=str.lower)),
                              (self.year, sorted({(r["invoice_date"] or "")[:4] for r in rows if r["invoice_date"]}, reverse=True))):
            cur = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("All", "")
            for v in values:
                combo.addItem(v, v)
            i = combo.findData(cur)
            combo.setCurrentIndex(max(i, 0))
            combo.blockSignals(False)
        self.update_cards(rows)
        self.apply_filter()

    def update_cards(self, rows):
        today = datetime.date.today()
        month, year = today.strftime("%Y-%m"), str(today.year)
        unpaid = [r for r in rows if r["status"] != "paid"]
        overdue = [r for r in rows if r["status"] == "overdue"]
        tot = lambda rs: sum(r["total"] or 0 for r in rs)
        self.c_unpaid.set(money(tot(unpaid)) or "€ 0,00", f"{len(unpaid)} invoices")
        self.c_overdue.set(money(tot(overdue)) or "€ 0,00", f"{len(overdue)} invoices")
        m = [r for r in rows if (r["invoice_date"] or "").startswith(month)]
        y = [r for r in rows if (r["invoice_date"] or "").startswith(year)]
        self.c_month.set(money(tot(m)) or "€ 0,00", f"{len(m)} invoices")
        self.c_year.set(money(tot(y)) or "€ 0,00", f"{len(y)} invoices")

    def apply_filter(self):
        self.proxy.text = parser.normalize(self.search.text())
        self.proxy.status = self.status.currentData()
        self.proxy.supplier = self.supplier.currentData() or ""
        self.proxy.year = self.year.currentData() or ""
        self.proxy.invalidateFilter()
        shown = self.visible_rows()
        self.summary.setText(f"{len(shown)} invoices · total {money(sum(r['total'] or 0 for r in shown)) or '€ 0,00'}")

    def visible_rows(self):
        return [self.model.rows[self.proxy.mapToSource(self.proxy.index(i, 0)).row()] for i in range(self.proxy.rowCount())]

    def selected(self):
        rows = {self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()}
        return [self.model.rows[r] for r in sorted(rows)]

    # ------------------------------------------------------------------ actions
    def menu(self, pos):
        sel = self.selected()
        if not sel:
            return
        m = QMenu(self)
        for text, fn in (("Open PDF", self.open_pdf), ("Show in folder", self.open_folder), ("Edit…", self.edit),
                         ("Mark paid…", self.mark_paid), ("Mark unpaid", self.mark_unpaid),
                         ("Print warehouse label", self.reprint_label), ("Send to stock tracker", self.resend_stock),
                         ("Open e-invoice link (QR)", self.open_qr), (None, None),
                         ("Remove from ledger…", self.remove)):
            if text is None:
                m.addSeparator()
                continue
            a = QAction(text, m)
            a.triggered.connect(fn)
            m.addAction(a)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def open_pdf(self):
        for r in self.selected()[:5]:
            if os.path.exists(r["file_path"]):
                filing.open_path(r["file_path"])
            else:
                QMessageBox.warning(self, "File not found", f"The PDF has been moved or deleted:\n{r['file_path']}")

    def open_folder(self):
        for r in self.selected()[:1]:
            filing.open_path(os.path.dirname(r["file_path"]))

    def open_qr(self):
        import webbrowser
        for r in self.selected()[:3]:
            if r.get("qr_url"):
                webbrowser.open(r["qr_url"])

    def mark_paid(self):
        sel = [r for r in self.selected() if r["status"] != "paid"]
        if not sel:
            return
        d = PayDialog(self, len(sel), sum(r["total"] or 0 for r in sel))
        if d.exec():
            self.ctx.db.mark_paid([r["id"] for r in sel], d.date.iso() or datetime.date.today().isoformat(),
                                  d.notes.text() or None)
            self.ctx.invoices_changed.emit()

    def mark_unpaid(self):
        sel = self.selected()
        if sel:
            self.ctx.db.mark_paid([r["id"] for r in sel], "")
            self.ctx.invoices_changed.emit()

    def edit(self):
        sel = self.selected()
        if not sel:
            return
        d = EditDialog(self, sel[0])
        if d.exec():
            self.ctx.db.update_invoice(sel[0]["id"], **d.values())
            self.ctx.invoices_changed.emit()

    def remove(self):
        sel = self.selected()
        if sel and QMessageBox.question(self, "Remove", f"Remove {len(sel)} invoice(s) from the ledger?\n"
                                        "The PDF files stay where they are.") == QMessageBox.Yes:
            for r in sel:
                self.ctx.db.delete_invoice(r["id"])
            self.ctx.invoices_changed.emit()

    def reprint_label(self):
        out = self.ctx.settings.get("output_folder")
        for r in self.selected():
            p = filing.generate_label(r["supplier_name"], r["invoice_no"], r["invoice_date"], out,
                                      self.ctx.settings.get("label_url"))
        if self.selected():
            filing.open_path(p)

    def resend_stock(self):
        s = self.ctx.settings
        if not (s.get("stock_enabled") and s.get("stock_url")):
            QMessageBox.information(self, "Stock tracker", "Set up the stock tracker in Settings first.")
            return
        for r in self.selected():
            self.ctx.db.update_invoice(r["id"], stock_status="pending")
        key = self.ctx.secret("stock_api_key")
        common.run_async(lambda: stock.flush(self.ctx.db, s["stock_url"], key),
                         lambda res: (self.ctx.invoices_changed.emit(),
                                      self.ctx.status.emit(f"Stock tracker: {res[0]} sent, {res[1]} failed {res[2][:80]}")))

    def export(self):
        rows = self.visible_rows()
        if not rows:
            return
        name = f"Marine_Specials_Ledger_{datetime.datetime.now():%Y%m%d_%H%M}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Export", os.path.join(os.path.expanduser("~"), "Desktop", name),
                                              "Excel (*.xlsx)")
        if not path:
            return
        try:
            export.export_ledger(path, rows, self.ctx.db.monthly_spend(36), self.ctx.db.supplier_spend())
            self.ctx.status.emit(f"Exported {len(rows)} invoices")
            filing.open_path(path)
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))
