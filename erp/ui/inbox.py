"""Inbox: incoming PDFs -> check -> approve & file."""
import os
import re
import shutil

from PySide6.QtCore import Qt, QTimer, QFileSystemWatcher, QPointF, QEvent
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem, QSplitter,
    QLineEdit, QComboBox, QFormLayout, QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QFileDialog, QMessageBox, QScrollArea, QFrame, QCompleter)

from .. import extract, workflow, pdf, email_inbox, parser, stock
from . import common
from .common import DateField, money, restyle, GREEN, ORANGE, RED, ACCENT

ICON = {"reading": "⏳", "ready": "✅", "check": "⚠️", "dup": "⧉", "error": "❌"}


class InboxPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.raw = {}        # path -> (mtime, raw text/ocr result)  (slow part, cached)
        self.results = {}    # path -> analysis dict
        self.errors = {}     # path -> error text
        self.pending = set()
        self.retries = {}
        self.current = None
        self.setAcceptDrops(True)

        self.doc = QPdfDocument(self)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _: self._debounce.start())
        self._debounce = QTimer(self, singleShot=True, interval=1200, timeout=self.rescan)

        self._build()
        ctx.settings_changed.connect(self.on_settings_changed)
        ctx.suppliers_changed.connect(self.reinterpret_all)
        self._folder = None
        self.on_settings_changed()

    # ================================================================ UI
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)

        top = QHBoxLayout()
        title = QLabel("Inbox")
        title.setObjectName("pageTitle")
        top.addWidget(title)
        top.addSpacing(16)
        self.btn_in = QPushButton("📁 Input folder…")
        self.btn_in.clicked.connect(lambda: self.pick_folder("input_folder"))
        self.btn_out = QPushButton("📂 Archive folder…")
        self.btn_out.clicked.connect(lambda: self.pick_folder("output_folder"))
        top.addWidget(self.btn_in)
        top.addWidget(self.btn_out)
        top.addStretch()
        self.btn_email = QPushButton("✉ Check email")
        self.btn_email.clicked.connect(lambda: self.check_email(silent=False))
        self.btn_split = QPushButton("✂ Split multi-page")
        self.btn_split.clicked.connect(self.split_pdfs)
        self.btn_all = QPushButton("⚡ File all ready")
        self.btn_all.setObjectName("primary")
        self.btn_all.clicked.connect(self.file_all_ready)
        for b in (self.btn_email, self.btn_split, self.btn_all):
            top.addWidget(b)
        root.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        # ---- queue
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 8, 0, 0)
        self.search = QLineEdit(placeholderText="🔍 Search…")
        self.search.textChanged.connect(self.apply_filter)
        ll.addWidget(self.search)
        self.queue = QListWidget(objectName="queue")
        self.queue.currentItemChanged.connect(self.on_select)
        ll.addWidget(self.queue, 1)
        self.counts = QLabel("", objectName="muted")
        ll.addWidget(self.counts)
        self.empty_hint = QLabel("Choose an input folder, or drag PDFs here.", objectName="muted",
                                 alignment=Qt.AlignCenter, wordWrap=True)
        ll.addWidget(self.empty_hint)
        split.addWidget(left)

        # ---- viewer
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 8, 0, 0)
        vbar = QHBoxLayout()
        self.page_label = QLabel("", objectName="muted")
        vbar.addWidget(self.page_label)
        vbar.addStretch()
        for text, fn in (("−", lambda: self.zoom(1 / 1.2)), ("Fit width", self.fit_width), ("+", lambda: self.zoom(1.2))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            vbar.addWidget(b)
        ml.addLayout(vbar)
        self.view = QPdfView()
        self.view.setDocument(self.doc)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.view.viewport().installEventFilter(self)
        ml.addWidget(self.view, 1)
        split.addWidget(mid)

        # ---- form
        form_host = QScrollArea()
        form_host.setWidgetResizable(True)
        form_host.setFrameShape(QFrame.NoFrame)
        fw = QWidget()
        fl = QVBoxLayout(fw)
        fl.setContentsMargins(8, 8, 4, 0)
        self.banner = QLabel("Select a PDF", objectName="banner", wordWrap=True)
        fl.addWidget(self.banner)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.f_supplier = QComboBox(editable=True)
        self.f_supplier.setInsertPolicy(QComboBox.NoInsert)
        self.f_supplier.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.f_supplier.completer().setFilterMode(Qt.MatchContains)
        self.f_vat = QLineEdit(placeholderText="9 digits")
        self.f_invoice = QLineEdit()
        self.f_date = DateField()
        self.f_total = QLineEdit(placeholderText="0,00")
        self.f_due = DateField()
        self.f_mark = QLineEdit(placeholderText="15 digits (Greek e-invoices)")
        form.addRow("Supplier", self.f_supplier)
        form.addRow("ΑΦΜ / VAT", self.f_vat)
        form.addRow("Invoice #", self.f_invoice)
        form.addRow("Date", self.f_date)
        form.addRow("Total €", self.f_total)
        form.addRow("Due date", self.f_due)
        form.addRow("ΜΑΡΚ", self.f_mark)
        fl.addLayout(form)
        for w in (self.f_vat, self.f_invoice, self.f_total, self.f_mark):
            w.returnPressed.connect(self.approve)
        self.f_supplier.lineEdit().returnPressed.connect(self.approve)

        items_bar = QHBoxLayout()
        items_bar.addWidget(QLabel("Line items"))
        items_bar.addStretch()
        add = QPushButton("+")
        add.clicked.connect(lambda: self.items.insertRow(self.items.rowCount()))
        rem = QPushButton("−")
        rem.clicked.connect(lambda: self.items.removeRow(self.items.currentRow()))
        items_bar.addWidget(add)
        items_bar.addWidget(rem)
        fl.addLayout(items_bar)
        self.items = QTableWidget(0, 5)
        self.items.setHorizontalHeaderLabels(["Description", "Qty", "Unit", "Price", "Amount"])
        hh = self.items.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, w in ((1, 50), (2, 46), (3, 70), (4, 78)):
            hh.setSectionResizeMode(c, QHeaderView.Fixed)
            self.items.setColumnWidth(c, w)
        self.items.verticalHeader().hide()
        self.items.setMinimumHeight(140)
        fl.addWidget(self.items)

        self.chk_remember = QCheckBox("Remember this supplier for next time")
        self.chk_stock = QCheckBox("Send items to stock tracker")
        fl.addWidget(self.chk_remember)
        fl.addWidget(self.chk_stock)

        self.btn_approve = QPushButton("✔  Approve && File   (Enter)", objectName="approve")
        self.btn_approve.clicked.connect(self.approve)
        fl.addWidget(self.btn_approve)
        skip = QPushButton("Skip →")
        skip.clicked.connect(self.select_next)
        fl.addWidget(skip)
        fl.addStretch()
        form_host.setWidget(fw)
        split.addWidget(form_host)
        split.setSizes([260, 700, 420])

        QShortcut(QKeySequence("Ctrl+Return"), self, self.approve)
        QShortcut(QKeySequence("Ctrl+F"), self, self.search.setFocus)
        self.set_form_enabled(False)

    def eventFilter(self, obj, ev):
        if obj is self.view.viewport() and ev.type() == QEvent.Wheel and ev.modifiers() & Qt.ControlModifier:
            self.zoom(1.15 if ev.angleDelta().y() > 0 else 1 / 1.15)
            return True
        return super().eventFilter(obj, ev)

    def zoom(self, factor):
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(max(0.2, min(5.0, self.view.zoomFactor() * factor)))

    def fit_width(self):
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

    # ================================================================ folders
    @property
    def input_folder(self):
        return self.ctx.settings.get("input_folder") or ""

    @property
    def output_folder(self):
        return self.ctx.settings.get("output_folder") or ""

    def pick_folder(self, key):
        start = self.ctx.settings.get(key) or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Choose folder", start)
        if folder:
            self.ctx.save_settings({key: folder})

    def on_settings_changed(self):
        self.btn_in.setText(f"📁 In: {os.path.basename(self.input_folder) or 'choose…'}")
        self.btn_in.setToolTip(self.input_folder)
        self.btn_out.setText(f"📂 Archive: {os.path.basename(self.output_folder) or 'choose…'}")
        self.btn_out.setToolTip(self.output_folder)
        self.chk_stock.setVisible(bool(self.ctx.settings.get("stock_enabled")))
        if self.input_folder != self._folder:
            self._folder = self.input_folder
            for p in self.watcher.directories():
                self.watcher.removePath(p)
            if self._folder and os.path.isdir(self._folder):
                self.watcher.addPath(self._folder)
            self.raw.clear()
            self.results.clear()
            self.errors.clear()
            self.rescan()

    # ================================================================ queue
    def rescan(self):
        folder = self.input_folder
        files = []
        if folder and os.path.isdir(folder):
            files = sorted((os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".pdf")),
                           key=lambda p: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", os.path.basename(p))])
        present = set(files)
        for d in (self.raw, self.results, self.errors):
            for p in [p for p in d if p not in present]:
                d.pop(p, None)

        self.queue.blockSignals(True)
        self.queue.clear()
        for p in files:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, p)
            self.queue.addItem(it)
            self.update_item(it)
        self.queue.blockSignals(False)
        self.apply_filter()
        self.empty_hint.setVisible(not files)

        for p in files:
            mt = self._mtime(p)
            if p not in self.pending and (p not in self.raw or self.raw[p][0] != mt) and p not in self.errors:
                self.schedule(p)

        # keep the selection
        if self.current in present:
            self.select_path(self.current, reload=False)
        elif self.current:
            self.current = None
            self.clear_form()
            self.select_next()
        self.update_counts()

    @staticmethod
    def _mtime(p):
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0

    def item_for(self, path):
        for i in range(self.queue.count()):
            it = self.queue.item(i)
            if it.data(Qt.UserRole) == path:
                return it
        return None

    def state_of(self, path):
        if path in self.errors:
            return "error"
        r = self.results.get(path)
        if r is None:
            return "reading"
        if r.get("duplicate"):
            return "dup"
        return "ready" if r["confident"] else "check"

    def update_item(self, it):
        p = it.data(Qt.UserRole)
        st = self.state_of(p)
        r = self.results.get(p)
        sub = {"reading": "reading…", "error": self.errors.get(p, "")[:60]}.get(st)
        if sub is None and r:
            sub = " · ".join(x for x in (r["supplier"][:22], r["invoice"], money(r["total"])) if x)
            if st == "dup":
                sub = "already filed: " + sub
        it.setText(f"{ICON[st]}  {os.path.basename(p)}\n       {sub}")
        it.setToolTip(os.path.basename(p))

    def update_counts(self):
        states = [self.state_of(self.queue.item(i).data(Qt.UserRole)) for i in range(self.queue.count())]
        ready = states.count("ready")
        self.btn_all.setText(f"⚡ File all ready ({ready})")
        self.btn_all.setEnabled(ready > 0 and bool(self.output_folder))
        self.counts.setText(f"{len(states)} PDFs · {ready} ready · {states.count('check')} to check · "
                            f"{states.count('dup')} duplicates · {states.count('reading')} reading")

    def apply_filter(self):
        term = parser.normalize(self.search.text())
        for i in range(self.queue.count()):
            it = self.queue.item(i)
            p = it.data(Qt.UserRole)
            r = self.results.get(p) or {}
            hay = parser.normalize(" ".join([os.path.basename(p), r.get("supplier", ""), r.get("invoice", "")]))
            it.setHidden(bool(term) and term not in hay)

    # ================================================================ analysis
    def schedule(self, path, priority=False):
        if path in self.pending:
            return
        self.pending.add(path)
        lang = self.ctx.settings.get("ocr_languages", "ell+eng")
        mt = self._mtime(path)

        def done(raw):
            self.pending.discard(path)
            self.retries.pop(path, None)
            self.raw[path] = (mt, raw)
            self.errors.pop(path, None)
            self.interpret(path)

        def failed(e):
            self.pending.discard(path)
            n = self.retries.get(path, 0)
            if isinstance(e, pdf.PdfError) and n < 5 and os.path.exists(path):
                self.retries[path] = n + 1           # probably still being copied / downloaded
                QTimer.singleShot(2000, lambda: self.schedule(path))
                return
            self.errors[path] = str(e)
            it = self.item_for(path)
            if it:
                self.update_item(it)
            if path == self.current:
                self.set_banner(f"Can't read this PDF: {e}", RED)
            self.update_counts()

        common.run_async(lambda: extract.read(path, lang), done, failed, pool=common.analysis_pool)

    def interpret(self, path):
        if path not in self.raw:
            return
        try:
            r = extract.interpret(self.raw[path][1], self.ctx.db, self.ctx.settings, self.ctx.suppliers())
        except Exception as e:
            self.errors[path] = str(e)
            return
        r["duplicate"] = None
        if r["invoice"] and r["supplier"]:
            r["duplicate"] = self.ctx.db.find_duplicate(r["supplier"], r["invoice"], r["mark"], r["supplier_vat"])
        self.results[path] = r
        it = self.item_for(path)
        if it:
            self.update_item(it)
        self.update_counts()
        if path == self.current:
            self.populate(r)
        elif self.ctx.settings.get("auto_file") and r["confident"] and not r["duplicate"] and self.output_folder:
            self.file_one(path, r, mode="auto", quiet=True)

    def reinterpret_all(self):
        for p in list(self.raw):
            self.interpret(p)

    # ================================================================ selection / form
    def on_select(self, cur, _prev=None):
        if cur is None:
            return
        self.select_path(cur.data(Qt.UserRole))

    def select_path(self, path, reload=True):
        if reload or self.current != path:
            self.current = path
            self.doc.close()
            self.doc.load(path)
            self.page_label.setText(f"{os.path.basename(path)} · {self.doc.pageCount()} page(s)")
            self.fit_width()
            self.view.pageNavigator().jump(0, QPointF(), self.view.zoomFactor())
        it = self.item_for(path)
        if it and self.queue.currentItem() is not it:
            self.queue.blockSignals(True)
            self.queue.setCurrentItem(it)
            self.queue.blockSignals(False)
        if path in self.results:
            if reload:
                self.populate(self.results[path])
        elif path in self.errors:
            self.clear_form()
            self.set_banner(f"Can't read this PDF: {self.errors[path]}", RED)
        else:
            self.clear_form()
            self.set_banner("Reading… (scanned pages take a few seconds)", ACCENT)
            self.schedule(path, priority=True)

    def select_next(self):
        row = self.queue.currentRow()
        for i in list(range(row + 1, self.queue.count())) + list(range(0, max(row, 0))):
            it = self.queue.item(i)
            if not it.isHidden():
                self.queue.setCurrentItem(it)
                return
        self.current = None
        self.doc.close()
        self.clear_form()
        self.set_banner("All done 🎉  Nothing left in the inbox.", GREEN)

    def set_banner(self, text, color):
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        self.banner.setText(text)
        self.banner.setStyleSheet(f"background: rgba({r},{g},{b},30); color: {color}; border: 1px solid rgba({r},{g},{b},110);")

    def set_form_enabled(self, on):
        for w in (self.f_supplier, self.f_vat, self.f_invoice, self.f_date, self.f_total, self.f_due,
                  self.f_mark, self.items, self.btn_approve, self.chk_remember, self.chk_stock):
            w.setEnabled(on)

    def clear_form(self):
        self.f_supplier.clear()
        for w in (self.f_vat, self.f_invoice, self.f_total, self.f_mark):
            w.clear()
            w.setProperty("state", "")
            restyle(w)
        self.f_date.set_iso("")
        self.f_due.set_iso("")
        self.items.setRowCount(0)
        self.chk_remember.hide()
        self.set_form_enabled(False)

    def _state(self, w, ok):
        w.setProperty("state", "ok" if ok else "warn")
        restyle(w)

    def populate(self, r):
        self.clear_form()
        self.set_form_enabled(True)
        names = [s["name"] for s in self.ctx.suppliers()]
        self.f_supplier.addItems(names)
        self.f_supplier.setEditText(r["supplier"])
        self._state(self.f_supplier, bool(r["supplier_id"]))
        self.f_vat.setText(r["supplier_vat"])
        self.f_invoice.setText(r["invoice"])
        self._state(self.f_invoice, bool(r["invoice"]))
        self.f_date.set_iso(r["date"])
        self.f_total.setText(f"{r['total']:.2f}".replace(".", ",") if r["total"] is not None else "")
        self._state(self.f_total, r["total"] is not None)
        self.f_due.set_iso(r.get("due_date", ""))
        self.f_mark.setText(r["mark"])
        self.set_items(r["items"])

        sup = next((s for s in self.ctx.suppliers() if s["id"] == r["supplier_id"]), None)
        vat_new = r["supplier_vat"] and r["supplier_vat"] not in self.ctx.own_vats and (not sup or r["supplier_vat"] not in sup["vats"])
        self.chk_remember.setVisible(not sup or bool(vat_new))
        self.chk_remember.setChecked(True)
        self.chk_remember.setText(f"Remember ΑΦΜ {r['supplier_vat']} for this supplier" if vat_new
                                  else "Remember this supplier for next time")
        self.chk_stock.setChecked(bool(r["items"]) and bool(self.ctx.settings.get("stock_auto_send", True)))

        how = {"text": "📄 Read from the PDF's text — exact", "ocr": "🔍 Scanned page read with OCR — please check",
               "none": "⚠ Scanned page but OCR isn't available"}[r["source"]]
        if r.get("duplicate"):
            d = r["duplicate"]
            self.set_banner(f"⧉ Already filed: {d['supplier_name']} #{d['invoice_no']} ({d['invoice_date']}). "
                            "Approving will ask before filing it twice.", RED)
        elif r["mydata"]:
            self.set_banner(f"✔ Verified with myDATA (ΜΑΡΚ {r['mark']}) — supplier, number, date and amounts are exact", GREEN)
        elif r["confident"]:
            self.set_banner(f"{how}\nSupplier recognised by {r['matched_by']}", GREEN if r["source"] == "text" else ORANGE)
        else:
            missing = [n for n, ok in (("supplier", r["supplier_id"]), ("invoice #", r["invoice"]), ("date", r["date"])) if not ok]
            self.set_banner(f"{how}\nCheck: {', '.join(missing)}", ORANGE)
        (self.f_invoice if r["supplier_id"] else self.f_supplier).setFocus()

    def set_items(self, items):
        self.items.setRowCount(0)
        for it in items:
            row = self.items.rowCount()
            self.items.insertRow(row)
            vals = [it["description"], f"{it['qty']:g}", it.get("unit", ""), f"{it['unit_price']:.2f}", f"{it['amount']:.2f}"]
            for c, v in enumerate(vals):
                self.items.setItem(row, c, QTableWidgetItem(v))

    def get_items(self):
        out = []
        for r in range(self.items.rowCount()):
            cell = lambda c: (self.items.item(r, c).text().strip() if self.items.item(r, c) else "")
            if not cell(0):
                continue
            out.append({"description": cell(0), "qty": parser.parse_money(cell(1)) or 1.0, "unit": cell(2),
                        "unit_price": parser.parse_money(cell(3)) or 0.0, "amount": parser.parse_money(cell(4)) or 0.0})
        return out

    def form_values(self):
        r = self.results.get(self.current) or {}
        return {
            "supplier": self.f_supplier.currentText().strip(),
            "supplier_vat": re.sub(r"\D", "", self.f_vat.text()),
            "invoice": self.f_invoice.text().strip(),
            "date": self.f_date.iso(),
            "total": parser.parse_money(self.f_total.text()),
            "due_date": self.f_due.iso(),
            "mark": re.sub(r"\D", "", self.f_mark.text()),
            "items": self.get_items(),
            "qr_url": r.get("qr_url", ""), "net": r.get("net"), "vat_amount": r.get("vat_amount"),
            "source": r.get("source", ""),
        }

    # ================================================================ filing
    def check_ready(self):
        if not self.output_folder:
            QMessageBox.information(self, "Archive folder", "Choose the archive (output) folder first.")
            self.pick_folder("output_folder")
            return bool(self.output_folder)
        return True

    def approve(self):
        if not self.current or not self.btn_approve.isEnabled() or not self.check_ready():
            return
        f = self.form_values()
        if not f["supplier"] or not f["invoice"]:
            QMessageBox.warning(self, "Missing data", "Supplier and invoice number are required.")
            return
        r = self.results.get(self.current) or {}
        keyword = r.get("supplier") if not r.get("supplier_id") and r.get("supplier") != f["supplier"] else ""
        self.file_one(self.current, f, mode="manual", remember=self.chk_remember.isVisible() and self.chk_remember.isChecked(),
                      keyword=keyword, stock=self.chk_stock.isVisible() and self.chk_stock.isChecked())

    def file_one(self, path, f, mode="manual", remember=False, keyword="", stock=None, quiet=False, allow_dup=False):
        if path == self.current:
            self.doc.close()   # Windows can't move a file the viewer has open
        try:
            iid, dest, changed = workflow.approve(self.ctx.db, self.ctx.settings, path, f, mode, remember, keyword,
                                                  allow_duplicate=allow_dup, send_to_stock=stock)
        except workflow.DuplicateInvoice as e:
            if quiet:
                return False
            ans = QMessageBox.question(self, "Possible duplicate",
                                       f"{f['supplier']} invoice {f['invoice']} is already in the ledger "
                                       f"({e.existing.get('invoice_date', '')}).\n\nFile it anyway?")
            if ans == QMessageBox.Yes:
                return self.file_one(path, f, mode, remember, keyword, stock, quiet, allow_dup=True)
            if path == self.current:
                self.doc.load(path)
            return False
        except Exception as e:
            if path == self.current:
                self.doc.load(path)
            if not quiet:
                QMessageBox.warning(self, "Couldn't file invoice", str(e))
            return False

        self.ctx.status.emit(f"✔ Filed {os.path.basename(dest)}" + ("  (auto)" if mode == "auto" else ""))
        self.refresh_duplicates(exclude=path)
        self.ctx.invoices_changed.emit()
        if changed:
            self.ctx.suppliers_updated()
        if self.ctx.settings.get("stock_enabled"):
            self.flush_stock()
        was_current = path == self.current
        it = self.item_for(path)
        row = 0
        if it:
            row = self.queue.row(it)
            self.queue.blockSignals(True)
            self.queue.takeItem(row)
            self.queue.blockSignals(False)
        for d in (self.raw, self.results, self.errors):
            d.pop(path, None)
        if was_current:
            self.current = None
            if self.queue.count():
                nxt = self.queue.item(min(row, self.queue.count() - 1))
                self.select_path(nxt.data(Qt.UserRole))
            else:
                self.select_next()
        self.update_counts()
        return True

    def refresh_duplicates(self, exclude=None):
        """After filing, copies of the same invoice still in the inbox become duplicates."""
        for p, r in self.results.items():
            if p == exclude or not (r["invoice"] and r["supplier"]):
                continue
            dup = self.ctx.db.find_duplicate(r["supplier"], r["invoice"], r["mark"], r["supplier_vat"])
            if bool(dup) != bool(r.get("duplicate")):
                r["duplicate"] = dup
                it = self.item_for(p)
                if it:
                    self.update_item(it)
                if p == self.current:
                    self.populate(r)

    def file_all_ready(self):
        if not self.check_ready():
            return
        ready = [p for p, r in self.results.items() if r["confident"] and not r.get("duplicate")]
        if not ready:
            return
        if QMessageBox.question(self, "File all ready",
                                f"File {len(ready)} invoices that were recognised with confidence?") != QMessageBox.Yes:
            return
        ok = dups = 0
        for p in ready:
            r = self.results.get(p)
            if r is None:
                continue
            if r.get("duplicate"):          # became a duplicate of one filed a moment ago
                dups += 1
                continue
            ok += bool(self.file_one(p, r, mode="bulk", quiet=True))
        msg = f"Filed {ok} invoice(s)."
        if dups:
            msg += f"\n{dups} skipped - same invoice was already filed (marked ⧉ in the inbox)."
        left = self.queue.count()
        if left:
            msg += f"\n{left} left in the inbox need a quick check."
        QMessageBox.information(self, "Done", msg)

    def flush_stock(self):
        url = self.ctx.settings.get("stock_url")
        if not url:
            return
        key = self.ctx.secret("stock_api_key")
        common.run_async(lambda: stock.flush(self.ctx.db, url, key),
                         lambda res: (self.ctx.invoices_changed.emit(),
                                      res[1] and self.ctx.status.emit(f"Stock tracker: {res[1]} not sent yet ({res[2][:80]})")))

    # ================================================================ tools
    def split_pdfs(self):
        folder = self.input_folder
        if not folder:
            return
        if QMessageBox.question(self, "Split PDFs",
                                "Split every multi-page PDF in the inbox into single pages?\n\n"
                                "Originals are moved to '_split_originals' (nothing is deleted).") != QMessageBox.Yes:
            return
        self.doc.close()

        def job():
            done, errors = 0, []
            originals = os.path.join(folder, "_split_originals")
            for f in os.listdir(folder):
                p = os.path.join(folder, f)
                if not f.lower().endswith(".pdf") or re.search(r"_page_\d+\.pdf$", f, re.I):
                    continue
                try:
                    if pdf.page_count(p) < 2:
                        continue
                    pdf.split(p, folder)
                    os.makedirs(originals, exist_ok=True)
                    from ..filing import unique_path
                    shutil.move(p, unique_path(os.path.join(originals, f)))
                    done += 1
                except Exception as e:
                    errors.append(f"{f}: {e}")
            return done, errors

        def finished(res):
            self.rescan()
            self.ctx.status.emit(f"Split {res[0]} PDFs")
            if res[1]:
                QMessageBox.warning(self, "Some files couldn't be split", "\n".join(res[1][:15]))

        common.run_async(job, finished, lambda e: QMessageBox.warning(self, "Split failed", str(e)),
                         pool=common.analysis_pool)

    def check_email(self, silent=True):
        s = self.ctx.settings
        if not s.get("imap_enabled") or not s.get("imap_host"):
            if not silent:
                QMessageBox.information(self, "Email", "Set up the email inbox in Settings first.")
            return
        if not self.input_folder:
            return
        pw = self.ctx.secret("imap_password")
        self.btn_email.setEnabled(False)

        def done(saved):
            self.btn_email.setEnabled(True)
            self.ctx.status.emit(f"✉ {len(saved)} new PDF(s) from email" if saved else "✉ No new invoices in email")
            if saved:
                self.rescan()

        def failed(e):
            self.btn_email.setEnabled(True)
            self.ctx.status.emit(f"✉ Email check failed: {e}")
            if not silent:
                QMessageBox.warning(self, "Email", str(e))

        common.run_async(lambda: email_inbox.fetch_pdfs(s["imap_host"], s.get("imap_port", 993), s["imap_user"], pw,
                                                        s.get("imap_folder", "INBOX"), self.input_folder,
                                                        s.get("imap_mark_read", True)), done, failed)

    # ================================================================ drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        if not self.input_folder:
            QMessageBox.information(self, "Input folder", "Choose the input folder first.")
            return
        from ..filing import unique_path
        n = 0
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p.lower().endswith(".pdf") and os.path.isfile(p):
                shutil.copy2(p, unique_path(os.path.join(self.input_folder, os.path.basename(p))))
                n += 1
        self.ctx.status.emit(f"Added {n} PDF(s) to the inbox")
        self.rescan()
