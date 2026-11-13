"""Split & Send: pick a PDF, cut it into documents, name them, send them to Drive."""
import os
import re
import shutil
import threading

from PIL import Image, ImageDraw, ImageQt
from PySide6.QtCore import Qt, QTimer, QFileSystemWatcher, QSize, Signal
from PySide6.QtGui import QPixmap, QIcon, QShortcut, QKeySequence, QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem, QSplitter, QLineEdit,
    QFileDialog, QMessageBox, QScrollArea, QFrame, QAbstractItemView, QMenu, QSlider, QDialog, QComboBox,
    QFormLayout, QCompleter, QDialogButtonBox)

from .. import pdf, analyze, naming, sender
from . import common
from .common import RED, DateField

DOC_COLORS = ["#1D7FA6", "#D68910", "#1E8449", "#8E44AD", "#C0392B", "#16A085", "#B7950B", "#2E4053"]


def natural_key(p):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", os.path.basename(p))]


class FileState:
    """Everything the user did to one PDF: cuts, rotations, removed pages, typed names."""

    def __init__(self, path, n_pages):
        self.path = path
        self.pages = [{"index": i, "rot": 0, "removed": False, "start": i == 0, "user_rot": False}
                      for i in range(n_pages)]
        self.infos = [None] * n_pages
        self.thumbs = [None] * n_pages
        self.edits = {}            # first page index of a document -> {"supplier"/"invoice"/"date"/"custom": typed}
        self.user_cut = False      # user changed the cuts -> don't overwrite with smart split
        self.smart_applied = False

    def documents(self):
        docs, cur = [], None
        for p in self.pages:
            if p["removed"]:
                continue
            if cur is None or p["start"]:
                cur = {"pages": []}
                docs.append(cur)
            cur["pages"].append(p)
        for n, d in enumerate(docs):
            d["key"] = d["pages"][0]["index"]
            d["color"] = DOC_COLORS[n % len(DOC_COLORS)]
            d["n"] = n + 1
        return docs

    def doc_of(self, index):
        for d in self.documents():
            if any(p["index"] == index for p in d["pages"]):
                return d
        return None


class NameFields(QWidget):
    """The v1 layout: Company / Invoice # / Date boxes that build the file name.
    "✎ Type full name" switches to one free-text box for anything else."""
    edited = Signal()
    submitted = Signal()

    def __init__(self, companies=()):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.form_host = QWidget()
        form = QFormLayout(self.form_host)
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(4)
        self.company = QComboBox(editable=True)
        self.company.setInsertPolicy(QComboBox.NoInsert)
        self.company.addItems(sorted(set(companies), key=str.lower))
        self.company.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.company.completer().setFilterMode(Qt.MatchContains)
        self.company.lineEdit().setPlaceholderText("company name")
        self.invoice = QLineEdit(placeholderText="invoice number")
        self.date = DateField()
        form.addRow("Company", self.company)
        form.addRow("Invoice #", self.invoice)
        form.addRow("Date", self.date)
        lay.addWidget(self.form_host)
        self.custom = QLineEdit(placeholderText="type the whole file name")
        self.custom.hide()
        lay.addWidget(self.custom)
        self.preview = QLabel(objectName="muted", wordWrap=True)
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.preview)
        row = QHBoxLayout()
        row.setSpacing(6)
        small = "QPushButton { padding: 2px 8px; font-size: 9pt; }"
        self.mode_btn = QPushButton("✎ Type full name")
        self.mode_btn.setStyleSheet(small)
        self.mode_btn.clicked.connect(self.toggle_mode)
        row.addWidget(self.mode_btn)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setToolTip("Back to what was read from the page")
        self.reset_btn.setStyleSheet(small)
        row.addWidget(self.reset_btn)
        row.addStretch()
        lay.addLayout(row)
        self.user = {}     # fields the user typed in
        self._last_name = ""
        self.company.lineEdit().textEdited.connect(lambda t: self._typed("supplier", t))
        self.company.activated.connect(lambda _: self._typed("supplier", self.company.currentText()))
        self.invoice.textEdited.connect(lambda t: self._typed("invoice", t))
        self.date.dateChanged.connect(lambda _: self._typed("date", self.date.iso()))
        self.custom.textEdited.connect(lambda t: self._typed("custom", t))
        for w in (self.company.lineEdit(), self.invoice, self.custom):
            w.returnPressed.connect(self.submitted.emit)

    def _typed(self, key, value):
        self.user[key] = value
        self.edited.emit()

    def toggle_mode(self):
        custom = not self.custom.isVisible()
        self.custom.setVisible(custom)
        self.form_host.setVisible(not custom)
        self.mode_btn.setText("▦ Use the boxes" if custom else "✎ Type full name")
        if custom:
            self.custom.setText(self._last_name)
            self.user["custom"] = self._last_name
            self.custom.setFocus()
        else:
            self.user.pop("custom", None)
        self.edited.emit()

    def fill(self, suggested, edits, name):
        """Show suggestions in every box the user hasn't typed in (and isn't typing in now)."""
        self.user = dict(edits)
        vals = {**suggested, **{k: v for k, v in edits.items() if k != "custom"}}
        for key, widget, setter in (("supplier", self.company.lineEdit(), lambda v: self.company.setEditText(v)),
                                    ("invoice", self.invoice, self.invoice.setText)):
            if not widget.hasFocus():
                widget.blockSignals(True)
                setter(vals.get(key, ""))
                widget.blockSignals(False)
        if not self.date.hasFocus():
            self.date.blockSignals(True)
            self.date.set_iso(vals.get("date", ""))
            self.date.blockSignals(False)
        is_custom = "custom" in edits
        if is_custom != self.custom.isVisible():
            self.custom.setVisible(is_custom)
            self.form_host.setVisible(not is_custom)
            self.mode_btn.setText("▦ Use the boxes" if is_custom else "✎ Type full name")
        if is_custom and not self.custom.hasFocus():
            self.custom.setText(edits["custom"])
        self._last_name = name
        self.preview.setText(f"📄 <b>{name}.pdf</b>" if name else "📄 —")
        self.reset_btn.setVisible(bool(edits))


class RenameDialog(QDialog):
    """F2 on a file in the list: rename it with the same Company / Invoice # / Date boxes."""

    def __init__(self, parent, path, fields, names, settings):
        super().__init__(parent)
        self.setWindowTitle("Rename")
        self.setMinimumWidth(460)
        self.path, self.fields, self.names, self.settings = path, fields, names, settings
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{os.path.basename(path)}</b>"))
        self.nf = NameFields(names.values())
        lay.addWidget(self.nf)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Rename")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.edits = {}
        # start from the current name if it already follows Company_Invoice_Date
        old = naming.parse_filename(path)
        if old:
            self.edits = old
        self.nf.edited.connect(self.update)
        self.nf.submitted.connect(self.accept)
        self.nf.reset_btn.clicked.connect(lambda: (self.edits.clear(), self.update(reset=True)))
        self.update(reset=True)

    def suggested(self):
        v = naming.values(self.fields, self.names, os.path.basename(self.path), 1, "%Y-%m-%d")
        return {"supplier": v["supplier"], "invoice": v["invoice"], "date": self.fields.get("date", "")}

    def name(self):
        return naming.build(self.fields, self.names, os.path.basename(self.path), 1,
                            self.settings.get("name_template"), self.settings.get("date_format", "%Y-%m-%d"), self.edits)

    def update(self, reset=False):
        if not reset:
            self.edits = dict(self.nf.user)
        self.nf.fill(self.suggested(), self.edits, self.name())


class PreviewDialog(QDialog):
    def __init__(self, parent, path, page, rot):
        super().__init__(parent)
        self.setWindowTitle(f"{os.path.basename(path)} · page {page + 1}")
        self.resize(820, 1000)
        lay = QVBoxLayout(self)
        area = QScrollArea()
        area.setWidgetResizable(True)
        lbl = QLabel(alignment=Qt.AlignCenter)
        img = pdf.render(path, page, 110, rotation=rot)
        lbl.setPixmap(QPixmap.fromImage(ImageQt.ImageQt(img.convert("RGB"))))
        area.setWidget(lbl)
        lay.addWidget(area)


class WorkPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.states = {}           # path -> FileState (kept while the app runs)
        self.current = None
        self._job = None           # cancel flag of the running analysis
        self.thumb_w = 150
        self.setAcceptDrops(True)

        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _: self._debounce.start())
        self._debounce = QTimer(self, singleShot=True, interval=1000, timeout=self.rescan)
        self._names_timer = QTimer(self, singleShot=True, interval=150, timeout=self.refresh_docs)
        self._build()
        ctx.settings_changed.connect(self.on_settings_changed)
        self._folder = None
        self.on_settings_changed()

    # ================================================================ layout
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        top = QHBoxLayout()
        t = QLabel("Split & Send")
        t.setObjectName("pageTitle")
        top.addWidget(t)
        top.addSpacing(16)
        self.btn_in = QPushButton()
        self.btn_in.clicked.connect(lambda: self.pick_folder("input_folder", "Inbox folder (scans arrive here)"))
        self.btn_drive = QPushButton()
        self.btn_drive.clicked.connect(lambda: self.pick_folder("drive_folder", "Google Drive folder"))
        top.addWidget(self.btn_in)
        top.addWidget(self.btn_drive)
        top.addStretch()
        add = QPushButton("+ Add PDFs…")
        add.clicked.connect(self.add_files)
        top.addWidget(add)
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
        self.queue.setContextMenuPolicy(Qt.CustomContextMenu)
        self.queue.customContextMenuRequested.connect(self.queue_menu)
        ll.addWidget(self.queue, 1)
        self.queue_info = QLabel("", objectName="muted", wordWrap=True)
        ll.addWidget(self.queue_info)
        split.addWidget(left)

        # ---- pages
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 8, 0, 0)
        bar = QHBoxLayout()
        self.btn_smart = QPushButton("✨ Smart split")
        self.btn_smart.setToolTip("Find where each document starts (page numbers, invoice no., ΜΑΡΚ, ΑΦΜ)")
        self.btn_smart.clicked.connect(lambda: self.apply_smart(force=True))
        self.btn_every = QPushButton("✂ Every page")
        self.btn_every.clicked.connect(self.cut_every)
        self.btn_one = QPushButton("▭ One document")
        self.btn_one.clicked.connect(self.cut_none)
        for b in (self.btn_smart, self.btn_every, self.btn_one):
            bar.addWidget(b)
        bar.addSpacing(12)
        for text, tip, fn in (("✂", "Start a new document at the selected page  (S)", self.toggle_cut),
                              ("↺", "Rotate left  (L)", lambda: self.rotate(-90)),
                              ("↻", "Rotate right  (R)", lambda: self.rotate(90)),
                              ("🗑", "Remove / restore page  (Delete)", self.toggle_remove)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedWidth(40)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        self.zoom = QSlider(Qt.Horizontal, minimum=90, maximum=300, value=self.thumb_w)
        self.zoom.setFixedWidth(110)
        self.zoom.valueChanged.connect(self.set_thumb_size)
        bar.addWidget(QLabel("🔍"))
        bar.addWidget(self.zoom)
        ml.addLayout(bar)
        self.status = QLabel("", objectName="muted")
        ml.addWidget(self.status)
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.IconMode)
        self.grid.setResizeMode(QListWidget.Adjust)
        self.grid.setMovement(QListWidget.Static)
        self.grid.setSpacing(10)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self.page_menu)
        self.grid.itemDoubleClicked.connect(self.preview)
        self.empty = QLabel("Choose an inbox folder, or drag PDFs here.", objectName="muted", alignment=Qt.AlignCenter)
        ml.addWidget(self.empty)
        ml.addWidget(self.grid, 1)
        split.addWidget(mid)

        # ---- documents
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 8, 0, 0)
        self.docs_title = QLabel("Documents", objectName="sectionTitle")
        rl.addWidget(self.docs_title)
        self.docs_area = QScrollArea()
        self.docs_area.setWidgetResizable(True)
        self.docs_area.setFrameShape(QFrame.NoFrame)
        self.docs_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.docs_host = QWidget()
        self.docs_lay = QVBoxLayout(self.docs_host)
        self.docs_lay.setContentsMargins(0, 0, 0, 0)
        self.docs_lay.addStretch()
        self.docs_area.setWidget(self.docs_host)
        rl.addWidget(self.docs_area, 1)
        self.dest_label = QLabel("", objectName="muted", wordWrap=True)
        rl.addWidget(self.dest_label)
        self.btn_send = QPushButton("☁  Send to Drive", objectName="approve")
        self.btn_send.clicked.connect(lambda: self.send(to_inbox=False))
        rl.addWidget(self.btn_send)
        self.btn_local = QPushButton("Save split files to the inbox instead")
        self.btn_local.clicked.connect(lambda: self.send(to_inbox=True))
        rl.addWidget(self.btn_local)
        split.addWidget(right)
        split.setSizes([220, 720, 420])

        QShortcut(QKeySequence("S"), self.grid, self.toggle_cut)
        QShortcut(QKeySequence("R"), self.grid, lambda: self.rotate(90))
        QShortcut(QKeySequence("L"), self.grid, lambda: self.rotate(-90))
        QShortcut(QKeySequence(Qt.Key_Delete), self.grid, self.toggle_remove)
        QShortcut(QKeySequence("F2"), self.queue, self.rename_file)
        QShortcut(QKeySequence("Ctrl+Return"), self, lambda: self.send(False))
        self.set_enabled(False)

    def set_enabled(self, on):
        for w in (self.btn_smart, self.btn_every, self.btn_one, self.btn_send, self.btn_local):
            w.setEnabled(on)

    # ================================================================ folders
    @property
    def inbox(self):
        return self.ctx.settings.get("input_folder") or ""

    def pick_folder(self, key, title):
        start = self.ctx.settings.get(key) or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, title, start)
        if folder:
            self.ctx.save_settings({key: folder})

    def on_settings_changed(self):
        s = self.ctx.settings
        self.btn_in.setText(f"📁 Inbox: {os.path.basename(self.inbox) or 'choose…'}")
        self.btn_in.setToolTip(self.inbox)
        drive = s.get("drive_folder") or ""
        self.btn_drive.setText(f"☁ Drive: {os.path.basename(drive) or 'choose…'}")
        self.btn_drive.setToolTip(drive)
        if self.inbox != self._folder:
            self._folder = self.inbox
            for p in self.watcher.directories():
                self.watcher.removePath(p)
            if self._folder and os.path.isdir(self._folder):
                self.watcher.addPath(self._folder)
            self.rescan()
        self.refresh_docs()

    # ================================================================ queue
    def rescan(self):
        files = []
        if self.inbox and os.path.isdir(self.inbox):
            files = sorted((os.path.join(self.inbox, f) for f in os.listdir(self.inbox)
                            if f.lower().endswith(".pdf") and os.path.isfile(os.path.join(self.inbox, f))),
                           key=natural_key)
        for p in [p for p in self.states if p not in files]:
            self.states.pop(p, None)
        self.queue.blockSignals(True)
        self.queue.clear()
        for p in files:
            it = QListWidgetItem(f"📄  {os.path.basename(p)}")
            it.setData(Qt.UserRole, p)
            it.setToolTip(p)
            self.queue.addItem(it)
            if p == self.current:
                self.queue.setCurrentItem(it)
        self.queue.blockSignals(False)
        self.apply_filter()
        self.queue_info.setText(f"{len(files)} PDF(s) waiting  ·  F2 = rename" if files else "")
        self.empty.setVisible(not files and not self.current)
        if self.current and self.current not in files:
            self.clear_current()
        if not self.current and files:
            self.queue.setCurrentRow(0)

    def apply_filter(self):
        term = self.search.text().lower()
        for i in range(self.queue.count()):
            it = self.queue.item(i)
            it.setHidden(bool(term) and term not in it.text().lower())

    def queue_menu(self, pos):
        it = self.queue.itemAt(pos)
        if not it:
            return
        m = QMenu(self)
        for text, fn in (("Rename…  (F2)", self.rename_file), ("Open in PDF viewer", self.open_external),
                         ("Show in folder", lambda: self.reveal(it.data(Qt.UserRole))),
                         ("Move to _done (skip)", self.skip_file)):
            a = QAction(text, m)
            a.triggered.connect(fn)
            m.addAction(a)
        m.exec(self.queue.viewport().mapToGlobal(pos))

    def selected_file(self):
        it = self.queue.currentItem()
        return it.data(Qt.UserRole) if it else None

    def rename_file(self):
        path = self.selected_file()
        if not path:
            return
        old = os.path.basename(path)
        st = self.states.get(path)
        fields = {}
        if st and st.documents():
            fields = self.doc_fields(st, st.documents()[0])
        dlg = RenameDialog(self, path, fields, self.ctx.store.names, self.ctx.settings)
        if not dlg.exec():
            return
        new = naming.safe_name(dlg.name())
        if dlg.edits.get("supplier") and naming.remember(fields, dlg.edits["supplier"], self.ctx.store.names,
                                                         set(self.ctx.settings.get("own_vat_numbers") or [])):
            self.ctx.store.save_names()
        if not new or new + ".pdf" == old:
            return
        target = os.path.join(os.path.dirname(path), new + ".pdf")
        if os.path.exists(target):
            QMessageBox.warning(self, "Rename", "A file with that name already exists.")
            return
        try:
            os.rename(path, target)
        except OSError as e:
            QMessageBox.warning(self, "Rename", f"Windows couldn't rename it:\n{e}")
            return
        if path in self.states:
            st = self.states.pop(path)
            st.path = target
            self.states[target] = st
        if self.current == path:
            self.current = target
        self.rescan()

    def open_external(self):
        p = self.selected_file()
        if p:
            common.open_path(p)

    def reveal(self, p):
        common.reveal(p)

    def skip_file(self):
        p = self.selected_file()
        if not p:
            return
        done = os.path.join(os.path.dirname(p), "_done")
        os.makedirs(done, exist_ok=True)
        shutil.move(p, naming.unique_path(os.path.join(done, os.path.basename(p))))
        self.rescan()

    # ================================================================ load a file
    def on_select(self, cur, _prev=None):
        if cur is not None:
            self.load(cur.data(Qt.UserRole))

    def clear_current(self):
        self.current = None
        self.grid.clear()
        self.refresh_docs()
        self.set_enabled(False)
        self.status.setText("")

    def load(self, path):
        if self._job:
            self._job.set()        # stop reading the previous file
        self.current = path
        self.empty.hide()
        self.grid.clear()
        st = self.states.get(path)
        if st is None:
            try:
                st = FileState(path, pdf.page_count(path))
            except Exception as e:
                self.status.setText(f"❌ Can't open this PDF: {e}")
                self.set_enabled(False)
                self.refresh_docs()
                return
            self.states[path] = st
        self.set_enabled(True)
        self.build_grid()
        self.refresh_docs()
        if any(t is None for t in st.thumbs):
            common.run_async(lambda: pdf.render_all(path, 40), lambda imgs: self.got_thumbs(path, imgs),
                             lambda e: self.status.setText(f"❌ {e}"), pool=common.analysis_pool)
        if any(i is None for i in st.infos):
            self.start_analysis(st)
        else:
            self.update_status(st)

    def got_thumbs(self, path, imgs):
        st = self.states.get(path)
        if not st:
            return
        st.thumbs = imgs
        if path == self.current:
            self.build_grid()

    def start_analysis(self, st):
        cancel = threading.Event()
        self._job = cancel
        s = dict(self.ctx.settings)
        path = st.path

        def job():
            for i in range(len(st.infos)):
                if cancel.is_set():
                    return
                if st.infos[i] is not None:
                    continue
                try:
                    info = analyze.analyze_page(path, i, s.get("ocr_languages", "ell+eng"),
                                                set(s.get("own_vat_numbers") or []), s.get("auto_rotate", True))
                except Exception as e:
                    info = {"index": i, "blank": False, "rotation": 0, "source": "error", "error": str(e)}
                common.on_main(lambda i=i, info=info: self.page_done(st, i, info))

        common.analysis_pool.start(job)
        self.update_status(st)

    def page_done(self, st, i, info):
        st.infos[i] = info
        page = st.pages[i]
        if info.get("rotation") and not page["user_rot"]:
            page["rot"] = info["rotation"]
        done = all(x is not None for x in st.infos)
        if done and self.ctx.settings.get("smart_split_on_open", True) and not st.user_cut and not st.smart_applied:
            self.apply_smart(st=st)
        if st.path == self.current:
            self.update_page_item(i)
            self.update_status(st)
            self._names_timer.start()

    def update_status(self, st):
        done = sum(x is not None for x in st.infos)
        total = len(st.infos)
        scans = sum(1 for x in st.infos if x and x.get("source") == "ocr")
        if done < total:
            self.status.setText(f"⏳ Reading page {done + 1} of {total}…  (you can already cut, rotate and rename)")
        else:
            bits = [f"{total} page(s)"]
            if scans:
                bits.append(f"{scans} scanned (OCR)")
            rot = sum(1 for p in st.pages if p["rot"])
            if rot:
                bits.append(f"{rot} straightened")
            rem = sum(1 for p in st.pages if p["removed"])
            if rem:
                bits.append(f"{rem} blank removed")
            err = [x["error"] for x in st.infos if x.get("source") == "error"]
            if err:
                bits.append(f"⚠ {err[0][:80]}")
            self.status.setText("✔ " + " · ".join(bits) + "   —   S = cut here · R/L = rotate · Del = remove · double-click = preview")

    # ================================================================ page grid
    def thumb_icon(self, st, p, doc):
        w = self.thumb_w
        src = st.thumbs[p["index"]]
        if src is None:
            img = Image.new("RGB", (w, int(w * 1.41)), "#E5E8E8")
        else:
            img = src.convert("RGB")
            if p["rot"]:
                img = img.rotate(-p["rot"], expand=True)
            img.thumbnail((w, int(w * 1.45)))
        pad = 6
        canvas = Image.new("RGB", (img.width + 2 * pad, img.height + 2 * pad), doc["color"] if doc else "#BDC3C7")
        canvas.paste(img, (pad, pad))
        d = ImageDraw.Draw(canvas)
        if p["removed"]:
            canvas = Image.blend(canvas, Image.new("RGB", canvas.size, "white"), 0.65)
            d = ImageDraw.Draw(canvas)
            d.line((pad, pad, canvas.width - pad, canvas.height - pad), fill=RED, width=5)
            d.line((canvas.width - pad, pad, pad, canvas.height - pad), fill=RED, width=5)
        elif doc and doc["pages"][0] is p and doc["n"] > 1:
            d.rectangle((0, 0, 34, 26), fill=doc["color"])
            d.text((8, 6), f"#{doc['n']}", fill="white")
        return QIcon(QPixmap.fromImage(ImageQt.ImageQt(canvas)))

    def page_label(self, st, p, doc):
        if p["removed"]:
            return f"p{p['index'] + 1} · removed"
        info = st.infos[p["index"]]
        flag = "" if info is not None else " ⏳"
        return f"p{p['index'] + 1} · doc {doc['n']}{flag}" if doc else f"p{p['index'] + 1}"

    def build_grid(self):
        st = self.states.get(self.current)
        sel = {it.data(Qt.UserRole) for it in self.grid.selectedItems()}
        self.grid.clear()
        if not st:
            return
        self.grid.setIconSize(QSize(self.thumb_w + 12, int(self.thumb_w * 1.45) + 12))
        docs = {p["index"]: d for d in st.documents() for p in d["pages"]}
        for p in st.pages:
            doc = docs.get(p["index"])
            it = QListWidgetItem(self.thumb_icon(st, p, doc), self.page_label(st, p, doc))
            it.setData(Qt.UserRole, p["index"])
            it.setTextAlignment(Qt.AlignHCenter)
            self.grid.addItem(it)
            if p["index"] in sel:
                it.setSelected(True)

    def update_page_item(self, i):
        st = self.states.get(self.current)
        if not st or i >= self.grid.count():
            return
        p = st.pages[i]
        doc = st.doc_of(i)
        it = self.grid.item(i)
        it.setIcon(self.thumb_icon(st, p, doc))
        it.setText(self.page_label(st, p, doc))

    def set_thumb_size(self, v):
        self.thumb_w = v
        self.build_grid()

    def selected_pages(self):
        st = self.states.get(self.current)
        if not st:
            return None, []
        idx = sorted(it.data(Qt.UserRole) for it in self.grid.selectedItems())
        return st, [st.pages[i] for i in idx]

    def changed(self, structure=True):
        self.build_grid()
        self.refresh_docs()

    # ---- editing
    def toggle_cut(self):
        st, pages = self.selected_pages()
        if not pages:
            return
        for p in pages:
            if p["index"] != 0:
                p["start"] = not p["start"]
        st.user_cut = True
        self.changed()

    def cut_every(self):
        st = self.states.get(self.current)
        if st:
            for p in st.pages:
                p["start"] = True
            st.user_cut = True
            self.changed()

    def cut_none(self):
        st = self.states.get(self.current)
        if st:
            for p in st.pages:
                p["start"] = p["index"] == 0
            st.user_cut = True
            self.changed()

    def rotate(self, deg):
        st, pages = self.selected_pages()
        for p in pages:
            p["rot"] = (p["rot"] + deg) % 360
            p["user_rot"] = True
        if pages:
            self.changed()

    def toggle_remove(self):
        st, pages = self.selected_pages()
        if not pages:
            return
        new = not all(p["removed"] for p in pages)
        for p in pages:
            p["removed"] = new
        self.changed()

    def apply_smart(self, st=None, force=False):
        st = st or self.states.get(self.current)
        if not st:
            return
        if any(i is None for i in st.infos):
            if force:
                QMessageBox.information(self, "Smart split", "Still reading the pages - it will run automatically when done.")
                st.user_cut = False
                st.smart_applied = False
            return
        starts, blanks = analyze.smart_split(st.infos)
        for p in st.pages:
            p["start"] = p["index"] in starts or p["index"] == 0
            if self.ctx.settings.get("remove_blank", True):
                p["removed"] = p["index"] in blanks
        st.smart_applied = True
        st.user_cut = False
        if st.path == self.current:
            self.changed()

    def page_menu(self, pos):
        it = self.grid.itemAt(pos)
        if not it:
            return
        if not it.isSelected():
            self.grid.clearSelection()
            it.setSelected(True)
        m = QMenu(self)
        for text, fn in (("✂ Start new document here  (S)", self.toggle_cut), ("↻ Rotate right  (R)", lambda: self.rotate(90)),
                         ("↺ Rotate left  (L)", lambda: self.rotate(-90)), ("🗑 Remove / restore  (Del)", self.toggle_remove),
                         ("🔍 Preview", lambda: self.preview(it))):
            a = QAction(text, m)
            a.triggered.connect(fn)
            m.addAction(a)
        m.exec(self.grid.viewport().mapToGlobal(pos))

    def preview(self, it):
        st = self.states.get(self.current)
        if st and it:
            i = it.data(Qt.UserRole)
            PreviewDialog(self, st.path, i, st.pages[i]["rot"]).exec()

    # ================================================================ documents panel
    def doc_fields(self, st, doc):
        infos = [st.infos[p["index"]] for p in doc["pages"] if st.infos[p["index"]]]
        f = analyze.merge_fields(infos)
        return f

    def suggested_values(self, st, doc, fields):
        v = naming.values(fields, self.ctx.store.names, os.path.basename(st.path), doc["n"], "%Y-%m-%d")
        return {"supplier": v["supplier"], "invoice": v["invoice"], "date": fields.get("date", "")}

    def final_name(self, st, doc, fields, edits=None):
        s = self.ctx.settings
        f = dict(fields, _multi=len(st.documents()) > 1)
        return naming.build(f, self.ctx.store.names, os.path.basename(st.path), doc["n"],
                            s.get("name_template"), s.get("date_format", "%Y-%m-%d"),
                            st.edits.get(doc["key"]) if edits is None else edits)

    def refresh_docs(self):
        st = self.states.get(self.current)
        drive = self.ctx.settings.get("drive_folder") or ""
        docs = st.documents() if st else []
        sig = (st.path if st else None, tuple((d["key"], tuple(p["index"] for p in d["pages"])) for d in docs))
        reading = bool(st) and any(i is None for i in st.infos)
        if sig != getattr(self, "_card_sig", None):
            # structure changed: rebuild the cards
            while self.docs_lay.count() > 1:
                w = self.docs_lay.takeAt(0).widget()
                if w:
                    w.deleteLater()
            self._cards = {}
            for doc in docs:
                card = self.doc_card(st, doc)
                self._cards[doc["key"]] = card
                self.docs_lay.insertWidget(self.docs_lay.count() - 1, card)
            self._card_sig = sig
        for doc in docs:   # same structure: only refresh texts, never touch a box being typed in
            self.fill_card(st, doc, self._cards[doc["key"]], reading)
        if not st:
            self.docs_title.setText("Documents")
            self.dest_label.setText("")
            return
        n = len(docs)
        self.docs_title.setText(f"{n} document(s) from {os.path.basename(st.path)}")
        self.btn_send.setText(f"☁  Send {n} file{'s' if n != 1 else ''} to Drive   (Ctrl+Enter)")
        self.btn_local.setText("Save split files to the inbox instead" if n > 1 else "Rename in the inbox instead")
        sub = self.ctx.settings.get("subfolder_template") or ""
        self.dest_label.setText(f"→ {os.path.join(drive, sub) if drive else '⚠ choose the Drive folder (top bar)'}"
                                + ("" if not drive or os.path.isdir(drive) else "   ⚠ folder not available"))
        self.btn_send.setEnabled(bool(drive) and n > 0)
        self.btn_local.setEnabled(n > 0)

    def doc_card(self, st, doc):
        card = QFrame(objectName="card")
        card.setStyleSheet(f"#card {{ border-left: 6px solid {doc['color']}; }}")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 8, 10, 10)
        card.head = QLabel()
        lay.addWidget(card.head)
        card.nf = NameFields(self.ctx.store.names.values())
        key = doc["key"]

        def typed():
            st.edits[key] = dict(card.nf.user)
            self.fill_card(st, self.doc_by_key(st, key), card, any(i is None for i in st.infos))

        def reset():
            st.edits.pop(key, None)
            card.nf.user = {}
            self.fill_card(st, self.doc_by_key(st, key), card, any(i is None for i in st.infos))

        card.nf.edited.connect(typed)
        card.nf.submitted.connect(lambda: self.send(False))
        card.nf.reset_btn.clicked.connect(reset)
        lay.addWidget(card.nf)
        card.info = QLabel(objectName="muted", wordWrap=True)
        lay.addWidget(card.info)
        return card

    @staticmethod
    def doc_by_key(st, key):
        return next((d for d in st.documents() if d["key"] == key), None)

    def fill_card(self, st, doc, card, reading):
        if doc is None:
            return
        pages = [p["index"] + 1 for p in doc["pages"]]
        if len(pages) == 1:
            rng = f"page {pages[0]}"
        elif pages == list(range(pages[0], pages[-1] + 1)):
            rng = f"pages {pages[0]}–{pages[-1]}"
        else:
            rng = "pages " + ", ".join(map(str, pages))
        card.head.setText(f"<b>Document {doc['n']}</b> · {rng}")
        fields = self.doc_fields(st, doc)
        edits = st.edits.get(doc["key"], {})
        card.nf.fill(self.suggested_values(st, doc, fields), edits, self.final_name(st, doc, fields, edits))
        bits = [x for x in (fields.get("vat") and f"ΑΦΜ {fields['vat']}", fields.get("mark") and f"ΜΑΡΚ {fields['mark']}") if x]
        card.info.setText(("⏳ reading…  " if reading else "") +
                          (" · ".join(bits) if bits else ("" if reading else
                           ("" if fields.get("invoice") or fields.get("date") else "Nothing recognised - fill in the boxes"))))

    def collect_parts(self):
        st = self.states.get(self.current)
        parts = []
        for doc in st.documents():
            fields = self.doc_fields(st, doc)
            edits = st.edits.get(doc["key"], {})
            parts.append({"name": self.final_name(st, doc, fields, edits),
                          "pages": [(p["index"], p["rot"]) for p in doc["pages"]],
                          "fields": naming.apply_overrides(fields, edits), "read": fields, "edits": edits})
        return st, parts

    # ================================================================ send
    def send(self, to_inbox=False):
        st = self.states.get(self.current)
        if not st or not st.documents():
            return
        if not to_inbox and not self.ctx.settings.get("drive_folder"):
            QMessageBox.information(self, "Drive folder", "Choose your Google Drive folder first.")
            self.pick_folder("drive_folder", "Google Drive folder")
            return
        if any(i is None for i in st.infos) and not any(st.edits.values()):
            if QMessageBox.question(self, "Still reading", "Some pages are still being read, so names may be incomplete.\n\nSend anyway?") != QMessageBox.Yes:
                return
        st, parts = self.collect_parts()
        empty = [p for p in parts if not naming.safe_name(p["name"])]
        if empty:
            QMessageBox.warning(self, "Names", "Every document needs a file name.")
            return
        if self._job:
            self._job.set()
        try:
            written = sender.send(st.path, parts, self.ctx.settings, self.ctx.store.names, self.ctx.store, to_inbox)
        except sender.SendError as e:
            QMessageBox.warning(self, "Couldn't send", str(e))
            return
        learned = False
        own = set(self.ctx.settings.get("own_vat_numbers") or [])
        for part in parts:
            if part["edits"].get("supplier"):
                learned |= naming.remember(part["read"], part["edits"]["supplier"], self.ctx.store.names, own)
        if learned:
            self.ctx.store.save_names()
        where = "the inbox" if to_inbox else "Drive"
        self.ctx.status.emit(f"✔ {len(written)} file(s) saved to {where}: " + ", ".join(os.path.basename(w) for w in written[:3])
                             + (" …" if len(written) > 3 else ""))
        self.ctx.history_changed.emit()
        row = self.queue.currentRow()
        self.states.pop(st.path, None)
        self.current = None
        self.rescan()
        if self.queue.count():
            self.queue.setCurrentRow(min(row, self.queue.count() - 1))
        else:
            self.clear_current()
            self.status.setText("🎉 Inbox empty - all done.")

    # ================================================================ adding files
    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add PDFs", os.path.expanduser("~"), "PDF (*.pdf)")
        self.import_files(files)

    def import_files(self, files):
        if not self.inbox:
            QMessageBox.information(self, "Inbox", "Choose the inbox folder first.")
            self.pick_folder("input_folder", "Inbox folder")
            if not self.inbox:
                return
        n = 0
        for p in files:
            if p.lower().endswith(".pdf") and os.path.isfile(p):
                shutil.copy2(p, naming.unique_path(os.path.join(self.inbox, os.path.basename(p))))
                n += 1
        self.ctx.status.emit(f"Added {n} PDF(s)")
        self.rescan()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.import_files([u.toLocalFile() for u in e.mimeData().urls()])
