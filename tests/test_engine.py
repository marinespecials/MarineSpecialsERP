"""Engine tests: parsing, database, myDATA XML, updater, email. Run: python -m pytest tests"""
import os
import io
import sys
import json
import hashlib
import zipfile
import threading
from email.message import EmailMessage
from http.server import SimpleHTTPRequestHandler, HTTPServer
from functools import partial

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from erp import parser, db as dbm, mydata, updater, email_inbox, net, workflow, extract  # noqa: E402


# ------------------------------------------------------------------ parser
GREEK = """Ισχύς Α.Ε.
ΑΦΜ: 094123456 ΔΟΥ: Πειραιά
ΠΡΟΣ: Marine Specials Α.Φ.Μ.: 800555111
Τιμολόγιο Πώλησης - Δελτίο Αποστολής
Σειρά: Α Αρ.: 4587
Ημερομηνία: 03/09/2026
Σχοινί πρόσδεσης 12mm 10 τεμ 12,50 € 125,00 €
Σωσίβιο SOLAS 4 τεμ 85,00 € 340,00 €
Σύνολο αξίας: 465,00
Φ.Π.Α. 24%: 111,60
Πληρωτέο: 576,60 €
ΜΑΡΚ: 400001234567890
"""


def sup(i, name, vats=(), kws=()):
    return {"id": i, "name": name, "vats": list(vats), "keywords": list(kws), "payment_terms_days": 0}


def test_parse_greek_invoice():
    d = parser.parse_invoice(GREEK, [sup(1, "ΙΣΧΥΣ_ΑΕ", kws=["ΙΣΧΥΣ"])], {"800555111"})
    assert d["supplier"] == "ΙΣΧΥΣ_ΑΕ" and d["supplier_vat"] == "094123456"
    assert (d["invoice"], d["date"], d["total"], d["mark"]) == ("4587", "2026-09-03", 576.6, "400001234567890")
    assert [i["qty"] for i in d["items"]] == [10, 4] and d["items"][1]["amount"] == 340.0


def test_vat_rule_beats_keyword_and_own_vat_ignored():
    sups = [sup(1, "WRONG", kws=["ΙΣΧΥΣ"]), sup(2, "RIGHT", vats=["094123456"]), sup(3, "US", vats=["800555111"])]
    d = parser.parse_invoice(GREEK, sups, {"800555111"})
    assert d["supplier"] == "RIGHT"


def test_keyword_needs_whole_word():
    s = [sup(1, "RIDTEC_AG", kws=["RIDTEC"]), sup(2, "OFFGRIDTEC_AG", kws=["OFFGRIDTEC"])]
    assert parser.parse_invoice("OFFGRIDTEC AG\nInvoice No: 5", s)["supplier"] == "OFFGRIDTEC_AG"


@pytest.mark.parametrize("text,expected", [
    ("Invoice Date: 14.08.2026\nInvoice No: OG-2026-0193", "OG-2026-0193"),
    ("INVOICE\nInvoice Number: R-5521\nDate: 2026-07-01", "R-5521"),
    ("Τιμολόγιο Παροχής Υπηρεσιών Νο 778", "778"),
])
def test_invoice_numbers(text, expected):
    assert parser.parse_invoice(text, [])["invoice"] == expected


@pytest.mark.parametrize("s,v", [("576,60", 576.6), ("1.234,56", 1234.56), ("1,234.56", 1234.56), ("€ 99", 99.0), ("", None)])
def test_money(s, v):
    assert parser.parse_money(s) == v


# ------------------------------------------------------------------ database / workflow
@pytest.fixture
def db(tmp_path):
    return dbm.Database(str(tmp_path / "t.db"))


def test_legacy_import_and_learning(db, tmp_path):
    rules = tmp_path / "supplier_rules.json"
    rules.write_text(json.dumps({"ΙΣΧΥΣ": "ΙΣΧΥΣ_ΑΕ", "094000000": "ΙΣΧΥΣ_ΑΕ", "RIDTEC": "RIDTEC_AG"}), encoding="utf-8")
    assert db.import_legacy(str(rules)) == (2, 0)
    s = db.supplier_by_name("ισχυς_αε")
    assert s["vats"] == ["094000000"] and s["keywords"] == ["ΙΣΧΥΣ"]
    workflow.learn_supplier(db, "ΙΣΧΥΣ_ΑΕ", vat="094123456")
    assert "094123456" in db.supplier_by_name("ΙΣΧΥΣ_ΑΕ")["vats"]


def test_approve_files_and_blocks_duplicates(db, tmp_path):
    src = tmp_path / "in.pdf"
    src.write_bytes(b"%PDF-1.4 test")
    out = tmp_path / "archive"
    settings = dict(dbm.DEFAULT_SETTINGS, output_folder=str(out), default_terms_days=30)
    f = {"supplier": "ΙΣΧΥΣ_ΑΕ", "supplier_vat": "094123456", "invoice": "4587", "date": "2026-09-03",
         "total": 576.6, "items": [], "mark": ""}
    iid, dest, _ = workflow.approve(db, settings, str(src), f, remember=True)
    assert os.path.exists(dest) and dest.endswith(os.path.join("2026", "ΙΣΧΥΣ_ΑΕ", "ΙΣΧΥΣ_ΑΕ_4587_2026-09-03.pdf"))
    inv = db.invoice(iid)
    assert inv["due_date"] == "2026-10-03" and inv["supplier_id"]
    src.write_bytes(b"%PDF-1.4 again")
    with pytest.raises(workflow.DuplicateInvoice):
        workflow.approve(db, settings, str(src), dict(f, supplier="Ισχύς_ΑΕ"))


# ------------------------------------------------------------------ myDATA
MYDATA_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<RequestedDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0" xmlns:icls="https://www.aade.gr/myDATA/incomeClassificaton/v1.0">
  <continuationToken><nextPartitionKey>PK1</nextPartitionKey><nextRowKey>RK1</nextRowKey></continuationToken>
  <invoicesDoc>
    <invoice>
      <uid>ABC</uid><mark>400001234567890</mark>
      <issuer><vatNumber>099887766</vatNumber><country>GR</country><branch>0</branch></issuer>
      <invoiceHeader><series>TP</series><aa>312</aa><issueDate>2026-09-21</issueDate><invoiceType>1.1</invoiceType></invoiceHeader>
      <invoiceSummary><totalNetValue>316.00</totalNetValue><totalVatAmount>75.84</totalVatAmount><totalGrossValue>391.84</totalGrossValue></invoiceSummary>
    </invoice>
  </invoicesDoc>
  <cancelledInvoicesDoc><cancelledInvoice><invoiceMark>400000000000001</invoiceMark></cancelledInvoice></cancelledInvoicesDoc>
</RequestedDoc>"""


def test_mydata_parse():
    docs, cancelled, cont = mydata.parse_requested_doc(MYDATA_XML)
    assert docs[0]["mark"] == "400001234567890" and docs[0]["issuer_vat"] == "099887766"
    assert docs[0]["aa"] == "312" and docs[0]["gross"] == 391.84 and docs[0]["issue_date"] == "2026-09-21"
    assert cancelled == ["400000000000001"] and cont == ("PK1", "RK1")


def test_mydata_paging_and_headers(monkeypatch):
    calls = []
    last = MYDATA_XML.replace(b"<continuationToken><nextPartitionKey>PK1</nextPartitionKey><nextRowKey>RK1</nextRowKey></continuationToken>", b"")

    def fake(url, headers=None, timeout=0, **k):
        calls.append((url, headers))
        return 200, MYDATA_XML if len(calls) == 1 else last
    monkeypatch.setattr(net, "request", fake)
    import datetime
    docs, _ = mydata.request_docs("user", "key", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
    assert len(calls) == 2 and len(docs) == 2
    assert calls[0][1] == {"aade-user-id": "user", "ocp-apim-subscription-key": "key"}
    assert "dateFrom=01%2F09%2F2026" in calls[0][0] and "nextPartitionKey=PK1" in calls[1][0]


def test_mydata_overrides_ocr(db):
    db.save_mydata_docs(mydata.parse_requested_doc(MYDATA_XML)[0])
    raw = {"text": "ΜΕΡΙΑ Α.Ε.\nΑΦΜ 099887766\nΑριθμός: 00312\nΠληρωτέο: 391,00\nΜΑΡΚ 400001234567890", "source": "ocr", "qr_texts": []}
    d = extract.interpret(raw, db, dbm.DEFAULT_SETTINGS, [])
    assert d["mydata"] and d["total"] == 391.84 and d["date"] == "2026-09-21" and d["invoice"] == "00312"


# ------------------------------------------------------------------ updater
def test_updater_check_download_verify(tmp_path, monkeypatch):
    pkg = tmp_path / "srv"
    pkg.mkdir()
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("MarineSpecialsERP/MarineSpecialsERP.exe", b"MZ fake")
        z.writestr("MarineSpecialsERP/.mserp-install", b"")
    (pkg / updater.ASSET_NAME).write_bytes(zbuf.getvalue())
    (pkg / (updater.ASSET_NAME + ".sha256")).write_text(hashlib.sha256(zbuf.getvalue()).hexdigest() + "  x\n")
    srv = HTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(pkg)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}/"
    release = {"tag_name": "v2.1.0", "html_url": "x", "body": "notes", "assets": [
        {"name": updater.ASSET_NAME, "browser_download_url": base + updater.ASSET_NAME},
        {"name": updater.ASSET_NAME + ".sha256", "browser_download_url": base + updater.ASSET_NAME + ".sha256"}]}
    real = net.request
    monkeypatch.setattr(net, "request", lambda url, **k: (200, json.dumps(release).encode()) if "api.github.com" in url else real(url, **k))
    info = updater.check(current="2.0.0")
    assert info["version"] == "2.1.0"
    assert updater.check(current="2.1.0") is None
    work, src = updater.download_and_verify(info)
    assert os.path.exists(os.path.join(src, "MarineSpecialsERP.exe"))
    (pkg / (updater.ASSET_NAME + ".sha256")).write_text("0" * 64)
    with pytest.raises(RuntimeError, match="checksum"):
        updater.download_and_verify(info)
    srv.shutdown()


def test_version_compare():
    assert updater.parse_version("v2.10.0") > updater.parse_version("2.9.9")


# ------------------------------------------------------------------ email
def test_email_fetch(tmp_path, monkeypatch):
    msg = EmailMessage()
    msg["Subject"] = "Τιμολόγιο"
    msg.set_content("see attached")
    msg.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="Τιμολόγιο 4587.pdf")
    raw = msg.as_bytes()
    flags = []

    class FakeIMAP:
        def __init__(self, host, port): pass
        def login(self, u, p): assert p == "pw"
        def select(self, folder, readonly=False): return "OK", [b"1"]
        def search(self, *a): return "OK", [b"1"]
        def fetch(self, mid, what): return "OK", [(b"1", raw)]
        def store(self, mid, op, flag): flags.append(flag)
        def logout(self): pass
    monkeypatch.setattr(email_inbox.imaplib, "IMAP4_SSL", FakeIMAP)
    saved = email_inbox.fetch_pdfs("h", 993, "u", "pw", "INBOX", str(tmp_path))
    assert [os.path.basename(p) for p in saved] == ["Τιμολόγιο 4587.pdf"] and flags == ["\\Seen"]
