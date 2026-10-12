"""Passwords and API keys go to Windows Credential Manager, never into the database."""
import os
import json

from .paths import data_dir

SERVICE = "MarineSpecialsERP"

try:
    import keyring
except ImportError:
    keyring = None


def _fallback_path():
    return os.path.join(data_dir(), ".secrets.json")


def _fallback_load():
    try:
        with open(_fallback_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_secret(name):
    if keyring:
        try:
            v = keyring.get_password(SERVICE, name)
            if v is not None:
                return v
        except Exception:
            pass
    return _fallback_load().get(name, "")


def set_secret(name, value):
    if keyring:
        try:
            if value:
                keyring.set_password(SERVICE, name, value)
            else:
                try:
                    keyring.delete_password(SERVICE, name)
                except Exception:
                    pass
            return
        except Exception:
            pass
    data = _fallback_load()
    data[name] = value
    with open(_fallback_path(), "w", encoding="utf-8") as f:
        json.dump(data, f)
