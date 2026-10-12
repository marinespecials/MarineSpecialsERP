"""Tesseract OCR (bundled with the app in the release build)."""
from PIL import ImageOps

from . import pdf, paths

try:
    import pytesseract
except ImportError:
    pytesseract = None

OCR_DPI = 300

TESSERACT_CMD = paths.find_tesseract()
TESSDATA = paths.tessdata_dir(TESSERACT_CMD)
if pytesseract and TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


def _config(extra=""):
    cfg = extra
    if TESSDATA:
        cfg += f' --tessdata-dir "{TESSDATA}"'
    return cfg.strip()


def available():
    return pytesseract is not None and TESSERACT_CMD is not None


_lang_cache = {}


def languages(preferred="ell+eng"):
    if not available():
        return None
    if preferred not in _lang_cache:
        try:
            installed = set(pytesseract.get_languages(config=_config()))
        except Exception:
            installed = {"eng"}
        wanted = [l for l in preferred.split("+") if l in installed]
        _lang_cache[preferred] = "+".join(wanted) if wanted else "eng"
    return _lang_cache[preferred]


def problems():
    if not available():
        return ["Tesseract not found - scanned PDFs can't be read (digital PDFs and ΜΑΡΚ lookups still work)."]
    if "ell" not in (languages() or ""):
        return ["Tesseract Greek language (ell) missing - Greek scans will read badly."]
    return []


def ocr_page(path, index=0, lang="ell+eng"):
    if not available():
        raise RuntimeError("Tesseract is not available")
    img = pdf.render(path, index, OCR_DPI, grayscale=True)
    img = ImageOps.autocontrast(img)
    # psm 4: single column of variable-size text - works well on invoices
    return pytesseract.image_to_string(img, lang=languages(lang), config=_config("--psm 4"))
