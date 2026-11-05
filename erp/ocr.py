"""Tesseract OCR (bundled with the app in the release build)."""
import os
import re

from PIL import ImageOps

from . import paths

try:
    import pytesseract
except ImportError:
    pytesseract = None

OCR_DPI = 300

TESSERACT_CMD = paths.find_tesseract()
TESSDATA = paths.tessdata_dir(TESSERACT_CMD)
if pytesseract and TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
if TESSDATA:
    # Tell Tesseract where the bundled language files are via the environment.
    # (Passing --tessdata-dir "path" breaks on Windows: pytesseract keeps the quote
    # characters, so Tesseract looked for ...\tessdata"/ell.traineddata.)
    os.environ["TESSDATA_PREFIX"] = TESSDATA


def available():
    return pytesseract is not None and TESSERACT_CMD is not None


_lang_cache = {}


def installed_languages():
    if "all" not in _lang_cache:
        try:
            _lang_cache["all"] = set(pytesseract.get_languages(config=""))
        except Exception:
            _lang_cache["all"] = set()
    return _lang_cache["all"]


def languages(preferred="ell+eng"):
    if not available():
        return None
    wanted = [l for l in preferred.split("+") if l in installed_languages()]
    return "+".join(wanted) if wanted else "eng"


def problems():
    if not available():
        return ["Tesseract not found - scanned pages can't be read (splitting still works)."]
    langs = installed_languages()
    if not langs:
        return [f"Tesseract can't find its language files ({TESSDATA or 'tessdata'})."]
    if "ell" not in langs:
        return ["Tesseract Greek language (ell) missing - Greek scans will read badly."]
    return []


def detect_rotation(img):
    """Degrees to turn the page clockwise so the text is upright (0/90/180/270)."""
    if not available() or "osd" not in installed_languages():
        return 0
    try:
        osd = pytesseract.image_to_osd(img, config="--psm 0")
    except Exception:
        return 0   # too little text to tell
    rot = re.search(r"Rotate:\s*(\d+)", osd)
    conf = re.search(r"Orientation confidence:\s*([\d.]+)", osd)
    if rot and conf and float(conf.group(1)) >= 1.5:
        return int(rot.group(1)) % 360
    return 0


def ocr_image(img, lang="ell+eng"):
    if not available():
        raise RuntimeError("Tesseract is not available")
    img = ImageOps.autocontrast(img.convert("L"))
    # psm 4: single column of variable-size text - works well on invoices
    return pytesseract.image_to_string(img, lang=languages(lang), config="--psm 4")
