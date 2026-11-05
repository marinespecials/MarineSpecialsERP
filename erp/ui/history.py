"""History: every file the app has saved, with quick open / show in folder."""
import os
import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTableWidget,
                               QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox)

from . import common


class HistoryPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        head = QHBoxLayout()
        t = QLabel("History")
        t.setObjectName("pageTitle")
        head.addWidget(t)
        head.addStretch()
        self.search = QLineEdit(placeholderText="🔍 Search file names…")
        self.search.setFixedWidth(300)
        self.search.textChanged.connect(self.reload)
        head.addWidget(self.search)
        root.addLayout(head)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["When", "Saved as", "Pages", "From"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(lambda _: self.open_file())
        root.addWidget(self.table, 1)

        bar = QHBoxLayout()
        self.summary = QLabel("", objectName="muted")
        bar.addWidget(self.summary)
        bar.addStretch()
        for text, fn in (("Show in folder", self.show_folder), ("Open file", self.open_file)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        root.addLayout(bar)
        ctx.history_changed.connect(self.reload)
        self.reload()

    def reload(self):
        term = self.search.text().lower()
        rows = [h for h in self.ctx.store.history
                if not term or term in os.path.basename(h["file"]).lower() or term in h["original"].lower()]
        self.table.setRowCount(0)
        for h in rows[:2000]:
            r = self.table.rowCount()
            self.table.insertRow(r)
            try:
                when = datetime.datetime.fromisoformat(h["time"]).strftime("%d/%m/%Y %H:%M")
            except ValueError:
                when = h["time"]
            for c, v in enumerate((when, os.path.basename(h["file"]), str(h["pages"]), h["original"])):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, h["file"])
                it.setToolTip(h["file"])
                self.table.setItem(r, c, it)
        today = datetime.date.today().isoformat()
        n_today = sum(1 for h in self.ctx.store.history if h["time"].startswith(today))
        self.summary.setText(f"{len(self.ctx.store.history)} files saved · {n_today} today")

    def selected(self):
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        return it.data(Qt.UserRole) if it else None

    def open_file(self):
        p = self.selected()
        if p and os.path.exists(p):
            common.open_path(p)
        elif p:
            QMessageBox.information(self, "Not found", f"The file is no longer there:\n{p}")

    def show_folder(self):
        p = self.selected()
        if p and os.path.exists(p):
            common.reveal(p)
        elif p and os.path.isdir(os.path.dirname(p)):
            common.open_path(os.path.dirname(p))
