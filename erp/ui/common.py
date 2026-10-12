"""Shared UI plumbing: background jobs, theme, small widgets."""
import traceback

from PySide6.QtCore import QObject, Signal, Slot, Qt, QThreadPool, QDate
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import (QFrame, QLabel, QVBoxLayout, QDateEdit, QApplication, QMessageBox, QStyleFactory)

NAVY = "#0B3C5D"
BLUE = "#1A5276"
ACCENT = "#1D7FA6"
GREEN = "#1E8449"
ORANGE = "#D68910"
RED = "#C0392B"


# ------------------------------------------------------------------ threads
class _Bridge(QObject):
    run = Signal(object)

    def __init__(self):
        super().__init__()
        self.run.connect(self._exec, Qt.QueuedConnection)

    @Slot(object)
    def _exec(self, fn):
        try:
            fn()
        except Exception:
            traceback.print_exc()


_bridge = None
analysis_pool = None   # OCR / PDF reading
network_pool = None    # email, myDATA, stock, updates


def init_bridge():
    """Call once after QApplication exists."""
    global _bridge, analysis_pool, network_pool
    _bridge = _Bridge()
    analysis_pool = QThreadPool()
    analysis_pool.setMaxThreadCount(2)
    network_pool = QThreadPool()
    network_pool.setMaxThreadCount(3)


def on_main(fn):
    """Run fn on the GUI thread (safe to call from any thread)."""
    _bridge.run.emit(fn)


def run_async(fn, done=None, error=None, pool=None):
    """Run fn() in the background; done(result) / error(exc) run on the GUI thread."""
    def task():
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            if error:
                on_main(lambda e=e: error(e))
            return
        if done:
            on_main(lambda: done(result))
    (pool or network_pool).start(task)


# ------------------------------------------------------------------ formatting
def money(v):
    if v is None or v == "":
        return ""
    s = f"{float(v):,.2f}"
    return "€ " + s.replace(",", "X").replace(".", ",").replace("X", ".")   # Greek format 1.234,56


def error_box(parent, title, err):
    QMessageBox.warning(parent, title, str(err))


# ------------------------------------------------------------------ widgets
class Card(QFrame):
    """KPI card: small title + big value."""

    def __init__(self, title, color=BLUE):
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.value = QLabel("–")
        self.value.setObjectName("cardValue")
        self.value.setStyleSheet(f"color: {color};")
        self.sub = QLabel("")
        self.sub.setObjectName("cardSub")
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        lay.addWidget(self.sub)

    def set(self, value, sub=""):
        self.value.setText(value)
        self.sub.setText(sub)


class DateField(QDateEdit):
    """Date picker that can also be empty."""
    EMPTY = QDate(2000, 1, 1)

    def __init__(self):
        super().__init__()
        self.setCalendarPopup(True)
        self.setDisplayFormat("dd/MM/yyyy")
        self.setMinimumDate(self.EMPTY)
        self.setSpecialValueText("—")
        self.set_iso("")

    def set_iso(self, iso):
        d = QDate.fromString(iso or "", "yyyy-MM-dd")
        self.setDate(d if d.isValid() else self.EMPTY)

    def iso(self):
        return "" if self.date() == self.EMPTY else self.date().toString("yyyy-MM-dd")


# ------------------------------------------------------------------ theme
QSS = """
* { font-family: "Segoe UI", "Noto Sans", sans-serif; font-size: 10pt; }
#sidebar { background: %(side)s; border: none; }
#sidebar::item { color: #D6EAF8; padding: 12px 18px; border-radius: 8px; margin: 2px 8px; }
#sidebar::item:selected { background: %(accent)s; color: white; }
#sidebar::item:hover:!selected { background: rgba(255,255,255,0.08); }
#brand { color: white; font-size: 13pt; font-weight: 700; padding: 18px 16px 4px 18px; }
#brandSub { color: #85C1E9; padding: 0 18px 14px 18px; font-size: 9pt; }
#card { background: %(card)s; border: 1px solid %(border)s; border-radius: 10px; }
#cardTitle { color: %(muted)s; font-size: 9pt; }
#cardValue { font-size: 18pt; font-weight: 700; }
#cardSub { color: %(muted)s; font-size: 9pt; }
#pageTitle { font-size: 16pt; font-weight: 700; }
#muted { color: %(muted)s; }
#banner { border-radius: 8px; padding: 8px 12px; font-weight: 600; }
#updateBar { background: #FEF5E7; color: #7E5109; border-bottom: 1px solid #F5CBA7; }
QPushButton { padding: 6px 14px; border-radius: 6px; border: 1px solid %(border)s; background: %(card)s; }
QPushButton:hover { border-color: %(accent)s; }
QPushButton:disabled { color: %(muted)s; }
QPushButton#primary { background: %(accent)s; color: white; border: none; font-weight: 600; }
QPushButton#primary:hover { background: %(blue)s; }
QPushButton#approve { background: %(green)s; color: white; border: none; font-weight: 700; padding: 10px; font-size: 11pt; }
QPushButton#approve:hover { background: #196F3D; }
QPushButton#approve:disabled { background: %(border)s; }
QLineEdit, QComboBox, QDateEdit, QSpinBox, QPlainTextEdit, QTextEdit { padding: 4px 6px; border: 1px solid %(border)s; border-radius: 5px; background: %(input)s; }
QLineEdit:focus, QComboBox:focus, QDateEdit:focus { border-color: %(accent)s; }
QLineEdit[state="ok"], QComboBox[state="ok"] { border: 2px solid %(green)s; }
QLineEdit[state="warn"], QComboBox[state="warn"] { border: 2px solid %(orange)s; }
QTableView, QTableWidget, QListWidget#queue { border: 1px solid %(border)s; border-radius: 6px; background: %(input)s; gridline-color: %(border)s; selection-background-color: %(accent)s; }
QListWidget#queue::item { padding: 6px 4px; border-bottom: 1px solid %(border)s; color: %(text)s; }
QListWidget#queue::item:selected { background: %(accent)s; color: white; }
QListWidget#queue::item:hover:!selected { background: %(card)s; }
QHeaderView::section { background: %(card)s; padding: 6px; border: none; border-bottom: 1px solid %(border)s; font-weight: 600; }
QGroupBox { border: 1px solid %(border)s; border-radius: 8px; margin-top: 14px; padding: 12px 10px 10px 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
"""

LIGHT = dict(side=NAVY, accent=ACCENT, blue=BLUE, green=GREEN, orange=ORANGE, card="#FFFFFF", border="#D5D8DC",
             muted="#7F8C8D", input="#FFFFFF", window="#F4F6F7", text="#1C2833")
DARK = dict(side="#0A1A26", accent=ACCENT, blue=BLUE, green="#239B56", orange="#E59866", card="#1F2A33",
            border="#34495E", muted="#95A5A6", input="#17202A", window="#121B22", text="#ECF0F1")


def is_dark(theme):
    if theme == "dark":
        return True
    if theme == "light":
        return False
    hints = QApplication.styleHints()
    try:
        return hints.colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return False


def apply_theme(app, theme="system"):
    c = DARK if is_dark(theme) else LIGHT
    app.setStyle(QStyleFactory.create("Fusion"))
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(c["window"]))
    pal.setColor(QPalette.WindowText, QColor(c["text"]))
    pal.setColor(QPalette.Base, QColor(c["input"]))
    pal.setColor(QPalette.AlternateBase, QColor(c["card"]))
    pal.setColor(QPalette.Text, QColor(c["text"]))
    pal.setColor(QPalette.Button, QColor(c["card"]))
    pal.setColor(QPalette.ButtonText, QColor(c["text"]))
    pal.setColor(QPalette.Highlight, QColor(c["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor("white"))
    pal.setColor(QPalette.ToolTipBase, QColor(c["card"]))
    pal.setColor(QPalette.ToolTipText, QColor(c["text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(c["muted"]))
    app.setPalette(pal)
    app.setStyleSheet(QSS % c)
    return c


def restyle(widget):
    """Re-apply QSS after changing a dynamic property like state=ok/warn."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
