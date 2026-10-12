"""Real PDF samples end to end (OCR ones are skipped where Tesseract isn't installed)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from erp import extract, ocr, db as dbm  # noqa: E402

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")


@pytest.fixture
def db(tmp_path):
    d = dbm.Database(str(tmp_path / "t.db"))
    d.save_supplier("ΙΣΧΥΣ_ΑΕ", keywords=["ΙΣΧΥΣ"])
    d.save_supplier("ΜΕΡΙΑ_ΑΕ", vats=["099887766"])
    d.save_supplier("OFFGRIDTEC_AG", keywords=["OFFGRIDTEC"])
    d.set("own_vat_numbers", ["800555111"])
    return d


@pytest.mark.parametrize("name,supplier,invoice,date,total,mark", [
    ("einvoice.pdf", "ΜΕΡΙΑ_ΑΕ", "00312", "2026-09-21", 391.84, "400001234567890"),
    ("scan_0001.pdf", "ΙΣΧΥΣ_ΑΕ", "4587", "2026-09-03", 576.6, ""),
    ("doc_17.pdf", "OFFGRIDTEC_AG", "OG-2026-0193", "2026-08-14", 2840.0, ""),
    pytest.param("SCANNED_EINVOICE.PDF", "ΜΕΡΙΑ_ΑΕ", "00312", "2026-09-21", 391.84, "400001234567890",
                 marks=pytest.mark.skipif(not ocr.available(), reason="Tesseract not installed")),
])
def test_sample(db, name, supplier, invoice, date, total, mark):
    d = extract.analyze(os.path.join(HERE, name), db)
    assert (d["supplier"], d["invoice"], d["date"], d["total"], d["mark"]) == (supplier, invoice, date, total, mark)
    assert d["confident"]


def test_qr_on_einvoice():
    from erp import qr
    codes = qr.read_qr_codes(os.path.join(HERE, "einvoice.pdf"))
    assert codes and "400001234567890" in codes[0]
