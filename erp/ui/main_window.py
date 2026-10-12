"""Main window: sidebar navigation, pages, background timers, updates."""
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem, QStackedWidget, QLabel,
    QPushButton, QFrame, QMessageBox, QProgressDialog, QApplication)

from .. import VERSION, DISPLAY_NAME, updater, stock, ocr
from . import common
from .inbox import InboxPage
from .ledger import LedgerPage
from .suppliers import SuppliersPage
from .reports import ReportsPage
from .settings_page import SettingsPage

PAGES = [("📥", "Inbox"), ("📒", "Ledger"), ("🏷", "Suppliers"), ("📊", "Reports"), ("⚙", "Settings")]


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(f"{DISPLAY_NAME}  v{VERSION}")
        self.resize(1500, 900)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # update banner
        self.update_bar = QFrame(objectName="updateBar")
        ub = QHBoxLayout(self.update_bar)
        ub.setContentsMargins(16, 6, 16, 6)
        self.update_label = QLabel()
        ub.addWidget(self.update_label, 1)
        self.update_btn = QPushButton("Install & restart", objectName="primary")
        self.update_btn.clicked.connect(self.install_update)
        later = QPushButton("Later")
        later.clicked.connect(self.update_bar.hide)
        ub.addWidget(self.update_btn)
        ub.addWidget(later)
        self.update_bar.hide()
        outer.addWidget(self.update_bar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        side = QFrame(objectName="sidebar")
        side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 12)
        sl.addWidget(QLabel("🌊 Marine Specials", objectName="brand"))
        sl.addWidget(QLabel(f"ERP · v{VERSION}", objectName="brandSub"))
        self.nav = QListWidget(objectName="sidebar")
        self.nav.setIconSize(QSize(0, 0))
        for icon, name in PAGES:
            self.nav.addItem(QListWidgetItem(f"{icon}   {name}"))
        sl.addWidget(self.nav, 1)
        body.addWidget(side)

        self.stack = QStackedWidget()
        self.inbox = InboxPage(ctx)
        self.ledger = LedgerPage(ctx)
        self.suppliers = SuppliersPage(ctx)
        self.reports = ReportsPage(ctx)
        self.settings = SettingsPage(ctx)
        for p in (self.inbox, self.ledger, self.suppliers, self.reports, self.settings):
            self.stack.addWidget(p)
        body.addWidget(self.stack, 1)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.setCentralWidget(central)

        self.statusBar().showMessage("Ready")
        ctx.status.connect(lambda m: self.statusBar().showMessage(m, 15000))
        self.settings.check_updates_requested.connect(lambda: self.check_updates(manual=True))
        self.settings.theme_changed.connect(lambda t: (common.apply_theme(QApplication.instance(), t), self.reports.draw()))

        # ---- background jobs
        self.email_timer = QTimer(self, timeout=lambda: self.inbox.check_email(silent=True))
        self.mydata_timer = QTimer(self, interval=6 * 3600 * 1000, timeout=lambda: self.settings.sync_mydata(quiet=True))
        self.stock_timer = QTimer(self, interval=5 * 60 * 1000, timeout=self.retry_stock)
        self.stock_timer.start()
        ctx.settings_changed.connect(self.apply_timers)
        self.apply_timers()
        self.update_info = None

        QTimer.singleShot(1500, self.startup_checks)

    def apply_timers(self):
        s = self.ctx.settings
        if s.get("imap_enabled") and s.get("imap_host"):
            self.email_timer.start(max(1, int(s.get("imap_interval_min") or 10)) * 60 * 1000)
        else:
            self.email_timer.stop()
        if s.get("mydata_enabled"):
            if not self.mydata_timer.isActive():
                self.mydata_timer.start()
        else:
            self.mydata_timer.stop()

    def startup_checks(self):
        s = self.ctx.settings
        if not s.get("input_folder") or not s.get("output_folder"):
            self.statusBar().showMessage("Welcome! Choose your inbox and archive folders to start.")
        for p in ocr.problems():
            self.statusBar().showMessage("⚠ " + p, 20000)
        if s.get("update_check", True):
            self.check_updates(manual=False)
        if s.get("mydata_enabled"):
            self.settings.sync_mydata(quiet=True)
        if s.get("imap_enabled"):
            self.inbox.check_email(silent=True)

    def retry_stock(self):
        s = self.ctx.settings
        if s.get("stock_enabled") and s.get("stock_url") and self.ctx.db.pending_stock():
            key = self.ctx.secret("stock_api_key")
            common.run_async(lambda: stock.flush(self.ctx.db, s["stock_url"], key),
                             lambda r: r[0] and self.ctx.invoices_changed.emit())

    # ------------------------------------------------------------------ updates
    def check_updates(self, manual=False):
        def done(info):
            self.update_info = info
            if info:
                self.update_label.setText(f"⬆  Version {info['version']} is available (you have v{VERSION}).")
                self.update_bar.show()
            elif manual:
                QMessageBox.information(self, "Updates", f"You're up to date (v{VERSION}).")

        def failed(e):
            if manual:
                QMessageBox.warning(self, "Updates", f"Couldn't check for updates:\n{e}")

        common.run_async(updater.check, done, failed)

    def install_update(self):
        info = self.update_info
        if not info:
            return
        ok, why = updater.can_self_update()
        if not ok:
            import webbrowser
            QMessageBox.information(self, "Update", f"{why}\n\nThe download page will open instead.")
            webbrowser.open(info["page"])
            return
        dlg = QProgressDialog("Downloading update…", "Cancel", 0, 100, self)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setAutoClose(False)
        dlg.show()

        def progress(done, total):
            if total:
                common.on_main(lambda: dlg.setValue(int(done * 100 / total)))

        def ready(res):
            dlg.close()
            if dlg.wasCanceled():
                return
            updater.install_and_restart(*res)
            QApplication.instance().quit()

        def failed(e):
            dlg.close()
            QMessageBox.warning(self, "Update failed", str(e))

        common.run_async(lambda: updater.download_and_verify(info, progress), ready, failed)

    def closeEvent(self, e):
        self.inbox.doc.close()
        super().closeEvent(e)
