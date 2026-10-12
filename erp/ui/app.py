"""Start the desktop app."""
import os
import sys
import logging
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon

from .. import paths, DISPLAY_NAME, VERSION
from ..db import Database
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


def first_run_import(db):
    """If an old v1 supplier_rules.json sits next to the app, bring it in once."""
    if db.get("v1_imported"):
        return
    for folder in (paths.install_dir(), os.path.join(os.environ.get("APPDATA", ""), "MarineSpecialsERP")):
        rules = os.path.join(folder, "supplier_rules.json")
        if os.path.exists(rules):
            db.import_legacy(rules_path=rules)
            break
    db.set("v1_imported", True)


def build(argv=None):
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName(DISPLAY_NAME)
    app.setApplicationVersion(VERSION)
    icon = os.path.join(paths.resource_dir(), "assets", "app.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    common.init_bridge()
    db = Database(os.path.join(paths.data_dir(), "erp.db"))
    first_run_import(db)
    ctx = Context(db)
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
