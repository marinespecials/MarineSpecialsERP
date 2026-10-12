"""Where things live: bundled resources, user data, bundled Tesseract."""
import os
import sys
import shutil

from . import APP_NAME

FROZEN = getattr(sys, "frozen", False)
IS_WINDOWS = os.name == "nt"


def resource_dir():
    """Read-only bundled files (PyInstaller puts them in _MEIPASS)."""
    if FROZEN:
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def install_dir():
    """Folder containing the running .exe (what the updater replaces)."""
    if FROZEN:
        return os.path.dirname(sys.executable)
    return resource_dir()


def data_dir():
    """Writable per-user folder: database, logs. Survives updates."""
    override = os.environ.get("MSERP_DATA_DIR")
    if override:
        path = override
    elif IS_WINDOWS:
        path = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME)
    else:
        path = os.path.join(os.path.expanduser("~"), ".local", "share", APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def find_tesseract():
    """Prefer the copy bundled with the app, so nothing needs installing."""
    candidates = [
        os.environ.get("TESSERACT_CMD", ""),
        os.path.join(resource_dir(), "tesseract", "tesseract.exe"),
        os.path.join(install_dir(), "tesseract", "tesseract.exe"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR", "tesseract.exe"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return shutil.which("tesseract")


def tessdata_dir(tesseract_cmd):
    """Bundled Tesseract keeps its language files next to it."""
    if not tesseract_cmd:
        return None
    d = os.path.join(os.path.dirname(tesseract_cmd), "tessdata")
    return d if os.path.isdir(d) else None
