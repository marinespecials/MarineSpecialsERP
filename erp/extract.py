"""One call to read an invoice PDF: text layer -> OCR fallback -> QR -> myDATA."""
import datetime

from . import pdf, ocr, qr
from .parser import parse_invoice

MIN_TEXT_CHARS = 40


def has_usable_text(text):
    return sum(ch.isalnum() for ch in text or "") >= MIN_TEXT_CHARS


def first_page_text(path, lang="ell+eng"):
    text = pdf.page_text(path, 0)
    if has_usable_text(text):
        return text, "text"
    if ocr.available():
        return ocr.ocr_page(path, 0, lang), "ocr"
    return text, "none"


def add_days(iso, days):
    try:
        return (datetime.date.fromisoformat(iso) + datetime.timedelta(days=int(days))).isoformat()
    except (ValueError, TypeError):
        return ""


def due_date(invoice_date, supplier, settings):
    """Supplier's payment terms, else the default terms, else no due date."""
    days = (supplier or {}).get("payment_terms_days") or settings.get("default_terms_days") or 0
    return add_days(invoice_date, days) if invoice_date and days else ""


def read(path, lang="ell+eng"):
    """The slow part (OCR, QR scan). Cache the result per file."""
    text, source = first_page_text(path, lang)
    return {"text": text, "source": source, "qr_texts": qr.read_qr_codes(path, 0)}


def interpret(raw, db, settings, suppliers):
    """The fast part: turn cached text into fields using current suppliers + myDATA."""
    own = set(settings.get("own_vat_numbers") or [])
    qr_texts = raw["qr_texts"]
    d = parse_invoice(raw["text"], suppliers, own, qr_texts)
    d.update(source=raw["source"], text=raw["text"], qr_url=qr_texts[0] if qr_texts else "",
             net=None, vat_amount=None, mydata=False)

    # ---- myDATA: exact data registered with AADE beats anything read off the page
    doc = None
    if d["mark"]:
        doc = db.mydata_doc(d["mark"])
    if doc is None and d["supplier_vat"] and d["invoice"]:
        doc = db.mydata_find(d["supplier_vat"], d["invoice"])
    if doc:
        d["mydata"] = True
        d["mark"] = doc["mark"]
        d["supplier_vat"] = doc["issuer_vat"] or d["supplier_vat"]
        digits = "".join(c for c in d["invoice"] if c.isdigit()).lstrip("0")
        if not digits or digits != "".join(c for c in (doc["aa"] or "") if c.isdigit()).lstrip("0"):
            d["invoice"] = doc["aa"] or d["invoice"]
        d["date"] = doc["issue_date"] or d["date"]
        d["total"], d["net"], d["vat_amount"] = doc["gross"], doc["net"], doc["vat"]
        sup = next((s for s in suppliers if d["supplier_vat"] in s["vats"]), None)
        if sup:
            d["supplier"], d["supplier_id"], d["matched_by"] = sup["name"], sup["id"], f"ΑΦΜ {d['supplier_vat']} (myDATA)"
        elif doc["issuer_name"] and not d["supplier_id"]:
            d["supplier"] = doc["issuer_name"]

    sup = next((s for s in suppliers if s["id"] == d["supplier_id"]), None)
    d["due_date"] = due_date(d["date"], sup, settings)
    d["confident"] = bool(d["supplier_id"] and d["invoice"] and d["date"])
    return d


def analyze(path, db, settings=None, suppliers=None):
    """read() + interpret() in one go (used by the command-line tool and bulk jobs)."""
    settings = settings or db.settings()
    suppliers = suppliers if suppliers is not None else db.suppliers()
    return interpret(read(path, settings.get("ocr_languages", "ell+eng")), db, settings, suppliers)
