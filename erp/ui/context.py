"""Shared state for all pages: database, settings, change notifications."""
from PySide6.QtCore import QObject, Signal

from .. import credentials


class Context(QObject):
    invoices_changed = Signal()
    suppliers_changed = Signal()
    settings_changed = Signal()
    status = Signal(str)          # status-bar message
    busy = Signal(bool)

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.settings = db.settings()
        self._suppliers = None

    # settings
    def reload_settings(self):
        self.settings = self.db.settings()
        self.settings_changed.emit()

    def save_settings(self, values):
        self.db.set_many(values)
        self.reload_settings()

    def secret(self, name):
        return credentials.get_secret(name)

    def set_secret(self, name, value):
        credentials.set_secret(name, value)

    # suppliers (cached - read a lot during analysis)
    def suppliers(self):
        if self._suppliers is None:
            self._suppliers = self.db.suppliers()
        return self._suppliers

    def suppliers_updated(self):
        self._suppliers = None
        self.suppliers_changed.emit()

    @property
    def own_vats(self):
        return set(self.settings.get("own_vat_numbers") or [])
