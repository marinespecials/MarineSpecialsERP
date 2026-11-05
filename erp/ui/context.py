"""Shared state for the pages."""
from PySide6.QtCore import QObject, Signal


class Context(QObject):
    settings_changed = Signal()
    history_changed = Signal()
    status = Signal(str)

    def __init__(self, store):
        super().__init__()
        self.store = store

    @property
    def settings(self):
        return self.store.settings

    def save_settings(self, values):
        self.store.save_settings(values)
        self.settings_changed.emit()
