"""Settings, learned supplier names and send history - small JSON files in the data folder."""
import os
import json
import datetime

from . import paths

DEFAULT_SETTINGS = {
    "input_folder": "",
    "drive_folder": "",
    "subfolder_template": "",                 # e.g. "{year}" or "{year}/{supplier}"
    "name_template": "{supplier}_{invoice}_{date}",
    "date_format": "%Y-%m-%d",
    "after_send": "done",                     # "done" = move original to Inbox\_done, "keep" = leave it
    "auto_rotate": True,
    "remove_blank": True,
    "smart_split_on_open": True,
    "own_vat_numbers": [],
    "ocr_languages": "ell+eng",
    "theme": "system",
    "update_check": True,
}


class Store:
    def __init__(self, folder=None):
        self.folder = folder or paths.data_dir()
        os.makedirs(self.folder, exist_ok=True)
        self.settings = {**DEFAULT_SETTINGS, **self._load("settings.json", {})}
        self.names = self._load("names.json", {})
        self.history = self._load("history.json", [])

    def _path(self, name):
        return os.path.join(self.folder, name)

    def _load(self, name, default):
        try:
            with open(self._path(name), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _save(self, name, data):
        tmp = self._path(name) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._path(name))

    def save_settings(self, values=None):
        if values:
            self.settings.update(values)
        self._save("settings.json", self.settings)

    def save_names(self):
        self._save("names.json", self.names)

    def add_history(self, original, dest, pages):
        self.history.insert(0, {"time": datetime.datetime.now().isoformat(timespec="seconds"),
                                "original": original, "file": dest, "pages": pages})
        del self.history[5000:]
        self._save("history.json", self.history)
