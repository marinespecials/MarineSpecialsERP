"""Start the desktop app."""
import os
import sys
import logging
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon

from .. import paths, DISPLAY_NAME, VERSION
from ..store import Store
from . import common
from .context import Context
from .main_window import MainWindow


def _setup_logging():
    log = os.path.join(paths.data_dir(), "app.log")
    logging.basicConfig(filename=log, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    def hook(exc_type, exc, tb):
        logging.error("Unhandled error:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = hook


def migrate_v2(store):
    """Keep the inbox folder and our ΑΦΜ from v2 settings (stored in erp.db)."""
    if store.settings.get("_migrated_v2"):
        return
    db = os.path.join(store.folder, "erp.db")
    if os.path.exists(db):
        try:
            import json
            import sqlite3
            con = sqlite3.connect(db)
            rows = dict(con.execute("SELECT key, value FROM settings").fetchall())
            con.close()
            for key in ("input_folder", "own_vat_numbers", "ocr_languages", "theme"):
                if key in rows and not store.settings.get(key):
                    store.settings[key] = json.loads(rows[key])
        except Exception:
            pass
    store.save_settings({"_migrated_v2": True})


def build(argv=None):
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName(DISPLAY_NAME)
    app.setApplicationVersion(VERSION)
    icon = os.path.join(paths.resource_dir(), "assets", "app.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    common.init_bridge()
    store = Store()
    migrate_v2(store)
    ctx = Context(store)
    common.apply_theme(app, ctx.settings.get("theme", "system"))
    win = MainWindow(ctx)
    return app, win, ctx


def run():
    _setup_logging()
    try:
        app, win, _ = build()
    except Exception as e:
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, DISPLAY_NAME, f"The app couldn't start:\n\n{e}")
        raise
    win.show()
    sys.exit(app.exec())
