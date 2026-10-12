"""AADE myDATA: download the invoices suppliers registered *to you* (RequestDocs).

Every Greek invoice now has a ΜΑΡΚ. With the ΜΑΡΚ (printed on the PDF / in
its QR code) we look up the exact supplier ΑΦΜ, number, date and amounts
here - no OCR guessing.

Credentials: myDATA portal -> "Εγγραφή στο myDATA REST API" gives a
username (aade-user-id) and subscription key (Κωδικός API).
"""
import datetime
import urllib.parse
import xml.etree.ElementTree as ET

from . import net

PROD_URL = "https://mydatapi.aade.gr/myDATA"
TEST_URL = "https://mydataapidev.aade.gr"


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child(el, *path):
    """Namespace-agnostic child lookup: _child(inv, 'invoiceHeader', 'aa')."""
    for name in path:
        if el is None:
            return None
        el = next((c for c in el if _local(c.tag) == name), None)
    return el


def _text(el, *path):
    c = _child(el, *path)
    return (c.text or "").strip() if c is not None and c.text else ""


def _num(el, *path):
    t = _text(el, *path)
    try:
        return float(t) if t else None
    except ValueError:
        return None


def parse_requested_doc(xml_bytes):
    """Returns (docs, cancelled_marks, continuation (pk, rk) or None)."""
    root = ET.fromstring(xml_bytes)
    docs, cancelled = [], []
    invoices_doc = _child(root, "invoicesDoc")
    for inv in (invoices_doc if invoices_doc is not None else []):
        if _local(inv.tag) != "invoice":
            continue
        mark = _text(inv, "mark")
        if not mark:
            continue
        docs.append({
            "mark": mark,
            "uid": _text(inv, "uid"),
            "issuer_vat": _text(inv, "issuer", "vatNumber"),
            "issuer_name": _text(inv, "issuer", "name"),
            "series": _text(inv, "invoiceHeader", "series"),
            "aa": _text(inv, "invoiceHeader", "aa"),
            "issue_date": _text(inv, "invoiceHeader", "issueDate")[:10],
            "invoice_type": _text(inv, "invoiceHeader", "invoiceType"),
            "net": _num(inv, "invoiceSummary", "totalNetValue"),
            "vat": _num(inv, "invoiceSummary", "totalVatAmount"),
            "gross": _num(inv, "invoiceSummary", "totalGrossValue"),
        })
    cancelled_doc = _child(root, "cancelledInvoicesDoc")
    for c in (cancelled_doc if cancelled_doc is not None else []):
        m = _text(c, "invoiceMark")
        if m:
            cancelled.append(m)
    token = _child(root, "continuationToken")
    cont = None
    if token is not None and _text(token, "nextPartitionKey"):
        cont = (_text(token, "nextPartitionKey"), _text(token, "nextRowKey"))
    return docs, cancelled, cont


def request_docs(user, key, date_from, date_to, test=False, max_pages=50):
    """Download all received documents issued between two dates (datetime.date)."""
    base = TEST_URL if test else PROD_URL
    headers = {"aade-user-id": user, "ocp-apim-subscription-key": key}
    params = {"mark": "0", "dateFrom": date_from.strftime("%d/%m/%Y"), "dateTo": date_to.strftime("%d/%m/%Y")}
    all_docs, all_cancelled = [], []
    for _ in range(max_pages):
        _, body = net.request(f"{base}/RequestDocs?{urllib.parse.urlencode(params)}", headers=headers, timeout=60)
        docs, cancelled, cont = parse_requested_doc(body)
        all_docs += docs
        all_cancelled += cancelled
        if not cont:
            break
        params["nextPartitionKey"], params["nextRowKey"] = cont
    return all_docs, all_cancelled


def sync(db, user, key, days=120, test=False):
    """Refresh the local ΜΑΡΚ cache. Returns number of documents stored."""
    to = datetime.date.today()
    docs, cancelled = request_docs(user, key, to - datetime.timedelta(days=days), to, test)
    cancelled = set(cancelled)
    docs = [d for d in docs if d["mark"] not in cancelled]
    db.save_mydata_docs(docs)
    return len(docs)
