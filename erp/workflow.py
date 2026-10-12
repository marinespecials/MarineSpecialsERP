"""Approve-and-file in one place, shared by manual, bulk and automatic filing."""
import os
import re

from . import filing
from .extract import due_date


class DuplicateInvoice(Exception):
    def __init__(self, existing):
        super().__init__(f"Already filed as {os.path.basename(existing.get('file_path', ''))}")
        self.existing = existing


def learn_supplier(db, name, vat="", keyword="", own_vats=()):
    """Create/extend a supplier so it's recognised automatically next time."""
    vat = vat if vat and vat not in own_vats and re.fullmatch(r"\d{9}", vat) else ""
    keyword = keyword.strip() if keyword and len(keyword.strip()) >= 4 else ""
    if not vat and not keyword and db.supplier_by_name(name):
        return db.supplier_by_name(name)
    return db.ensure_supplier(name, vat=vat, keyword=keyword)


def approve(db, settings, src_path, f, mode="manual", remember=False, learn_keyword="",
            allow_duplicate=False, send_to_stock=None):
    """f: fields from the form / analysis. Returns (invoice_id, dest_path, supplier_changed)."""
    if not f.get("supplier") or not f.get("invoice"):
        raise ValueError("Supplier and invoice number are required.")
    if not allow_duplicate:
        dup = db.find_duplicate(f["supplier"], f["invoice"], f.get("mark", ""), f.get("supplier_vat", ""))
        if dup:
            raise DuplicateInvoice(dup)

    own = set(settings.get("own_vat_numbers") or [])
    changed = False
    if remember:
        before = db.supplier_by_name(f["supplier"])
        sup = learn_supplier(db, f["supplier"], f.get("supplier_vat", ""), learn_keyword, own)
        changed = before is None or before["vats"] != sup["vats"] or before["keywords"] != sup["keywords"]
    else:
        sup = db.supplier_by_name(f["supplier"])
    f = dict(f)
    if sup:
        f["supplier_id"], f["supplier"] = sup["id"], sup["name"]
    if not f.get("due_date"):
        f["due_date"] = due_date(f.get("date"), sup, settings)
    if send_to_stock is None:
        send_to_stock = settings.get("stock_enabled") and settings.get("stock_auto_send") and bool(f.get("items"))
    f["stock_status"] = "pending" if send_to_stock and settings.get("stock_enabled") else ""

    iid, dest = filing.file_invoice(db, src_path, settings["output_folder"], f, mode,
                                    settings.get("folder_layout", "year_supplier"))
    try:
        filing.generate_label(f["supplier"], f["invoice"], f.get("date", ""), settings["output_folder"],
                              settings.get("label_url"))
    except Exception:
        pass   # a label problem must never block filing
    return iid, dest, changed
