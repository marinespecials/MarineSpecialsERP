"""Read each page (text layer or OCR), straighten scans, and find where documents start."""
import re

from . import pdf, ocr, qr
from .parser import parse_invoice, normalize, guess_company

MIN_TEXT_CHARS = 40
PAGE_RE = re.compile(r"(?:ΣΕΛΙΔΑ|ΣΕΛ\.|PAGE)\s*:?\s*(\d{1,3})\s*(?:/|ΑΠΟ|OF)\s*(\d{1,3})")


def has_usable_text(text):
    return sum(ch.isalnum() for ch in text or "") >= MIN_TEXT_CHARS


def analyze_page(path, index, lang="ell+eng", own_vats=(), auto_rotate=True):
    """Everything we can learn about one page. Slow for scans (OCR) - run in the background."""
    info = {"index": index, "blank": False, "rotation": 0, "source": "text", "text": ""}
    text = pdf.page_text(path, index)
    qr_texts = []
    if has_usable_text(text):
        qr_texts = qr.read_qr_codes(path, index)
    else:
        img = pdf.render(path, index, ocr.OCR_DPI, grayscale=True)
        if pdf.is_blank(img):
            info.update(blank=True, source="blank")
            return info
        if ocr.available():
            if auto_rotate:
                info["rotation"] = ocr.detect_rotation(img)
                if info["rotation"]:
                    img = img.rotate(-info["rotation"], expand=True)
            text = ocr.ocr_image(img, lang)
            info["source"] = "ocr"
        else:
            info["source"] = "none"
        qr_texts = qr.read_qr_codes(None, image=img)

    f = parse_invoice(text, [], set(own_vats), qr_texts)
    lines = [l for l in text.splitlines() if l.strip()]
    m = PAGE_RE.search(normalize(text))
    info.update(
        text=text, vat=f["supplier_vat"], invoice=f["invoice"], date=f["date"], mark=f["mark"],
        total=f["total"], company=guess_company(lines), qr=qr_texts[0] if qr_texts else "",
        page_no=int(m.group(1)) if m else None, page_of=int(m.group(2)) if m else None,
    )
    return info


def _same(a, b):
    return re.sub(r"[^0-9A-ZΑ-Ω]", "", normalize(a)) == re.sub(r"[^0-9A-ZΑ-Ω]", "", normalize(b))


def smart_split(infos):
    """Given page infos in order, return (start_indices, blank_indices).

    A page starts a new document when it says "Page 1 of N", or its ΜΑΡΚ /
    invoice number / supplier ΑΦΜ differs from the document being built.
    Pages without any of those (terms, continuation pages) stay attached.
    """
    starts, blanks = [], []
    cur = None
    for info in infos:
        if info.get("blank"):
            blanks.append(info["index"])
            continue
        if cur is None:
            new = True
        elif info.get("page_no"):
            new = info["page_no"] == 1
        elif info.get("mark") and cur.get("mark"):
            new = info["mark"] != cur["mark"]
        elif info.get("invoice") and cur.get("invoice"):
            new = not _same(info["invoice"], cur["invoice"])
        elif info.get("vat") and cur.get("vat"):
            new = info["vat"] != cur["vat"]
        elif (info.get("invoice") or info.get("mark")) and not (cur.get("invoice") or cur.get("mark")):
            new = True
        else:
            new = False
        if new:
            starts.append(info["index"])
            cur = dict(info)
        else:
            for k in ("vat", "invoice", "date", "mark", "total", "company", "qr"):
                if not cur.get(k) and info.get(k):
                    cur[k] = info[k]
    return starts or [0], blanks


def merge_fields(infos):
    """Combine what several pages of one document say (first value wins)."""
    out = {}
    for info in infos:
        for k in ("vat", "invoice", "date", "mark", "total", "company", "qr"):
            if not out.get(k) and info.get(k):
                out[k] = info[k]
    return out
