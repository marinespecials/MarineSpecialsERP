"""Main window: sidebar, pages, updates."""
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
                               QStackedWidget, QLabel, QPushButton, QFrame, QMessageBox, QProgressDialog, QApplication)

from .. import VERSION, DISPLAY_NAME, updater, ocr
from . import common
from .work import WorkPage
from .history import HistoryPage
from .settings import SettingsPage

PAGES = [("✂", "Split & Send"), ("🕘", "History"), ("⚙", "Settings")]


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

        self.update_bar = QFrame(objectName="updateBar")
        ub = QHBoxLayout(self.update_bar)
        ub.setContentsMargins(16, 6, 16, 6)
        self.update_label = QLabel()
        ub.addWidget(self.update_label, 1)
        btn = QPushButton("Install && restart", objectName="primary")
        btn.clicked.connect(self.install_update)
        later = QPushButton("Later")
        later.clicked.connect(self.update_bar.hide)
        ub.addWidget(btn)
        ub.addWidget(later)
        self.update_bar.hide()
        outer.addWidget(self.update_bar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)
        side = QFrame(objectName="sidebar")
        side.setFixedWidth(200)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 12)
        sl.addWidget(QLabel("🌊 Marine Specials", objectName="brand"))
        sl.addWidget(QLabel(f"PDF · v{VERSION}", objectName="brandSub"))
        self.nav = QListWidget(objectName="sidebar")
        self.nav.setIconSize(QSize(0, 0))
        for icon, name in PAGES:
            self.nav.addItem(QListWidgetItem(f"{icon}   {name}"))
        sl.addWidget(self.nav, 1)
        body.addWidget(side)

        self.stack = QStackedWidget()
        self.work = WorkPage(ctx)
        self.history = HistoryPage(ctx)
        self.settings = SettingsPage(ctx)
        for p in (self.work, self.history, self.settings):
            self.stack.addWidget(p)
        body.addWidget(self.stack, 1)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.setCentralWidget(central)

        self.statusBar().showMessage("Ready")
        ctx.status.connect(lambda m: self.statusBar().showMessage(m, 20000))
        self.settings.check_updates_requested.connect(lambda: self.check_updates(manual=True))
        self.settings.theme_changed.connect(lambda t: common.apply_theme(QApplication.instance(), t))
        self.update_info = None
        QTimer.singleShot(1500, self.startup_checks)

    def startup_checks(self):
        s = self.ctx.settings
        if not s.get("input_folder") or not s.get("drive_folder"):
            self.statusBar().showMessage("Welcome! Choose the Inbox and Google Drive folders (top bar or Settings).")
        for p in ocr.problems():
            self.statusBar().showMessage("⚠ " + p, 30000)
        if s.get("update_check", True):
            self.check_updates(manual=False)

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

        def ready(setup):
            dlg.close()
            if dlg.wasCanceled():
                return
            try:
                updater.install_and_restart(setup)
            except Exception as e:
                QMessageBox.warning(self, "Update failed", f"Couldn't start the installer:\n{e}\n\n"
                                    "Download it from the Releases page instead.")
                return
            self.statusBar().showMessage("Installing the update - the app will reopen in a moment…")
            QTimer.singleShot(300, QApplication.instance().quit)

        def failed(e):
            dlg.close()
            QMessageBox.warning(self, "Update failed", str(e))

        common.run_async(lambda: updater.download_and_verify(info, progress), ready, failed)
