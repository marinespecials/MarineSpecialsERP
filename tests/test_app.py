"""Engine tests. Run: python -m pytest tests"""
import os
import sys
import json
import hashlib
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, HTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from erp import pdf, analyze, naming, sender, store, ocr, updater, net  # noqa: E402

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
BATCH = os.path.join(HERE, "batch_scan.pdf")    # 7 pages: 4 documents, 1 blank, last page sideways
needs_ocr = pytest.mark.skipif(not ocr.available() or "osd" not in ocr.installed_languages(),
                               reason="Tesseract with osd/ell not installed")


# ------------------------------------------------------------------ pdf
def test_save_part_keeps_pages_and_rotation(tmp_path):
    dest = str(tmp_path / "out.pdf")
    pdf.save_part(BATCH, [(1, 0), (2, 0), (6, 90)], dest)
    assert pdf.page_count(dest) == 3
    assert "R-5521" in pdf.page_text(dest, 0)          # text layer survives (lossless)
    img = pdf.render(dest, 2, 50)
    assert img.height > img.width                       # sideways page now portrait


def test_blank_detection():
    assert pdf.is_blank(pdf.render(BATCH, 5, 100, grayscale=True))
    assert not pdf.is_blank(pdf.render(BATCH, 4, 100, grayscale=True))   # sparse scanned invoice


def test_files_are_not_locked(tmp_path):
    p = tmp_path / "a.pdf"
    p.write_bytes(open(BATCH, "rb").read())
    pdf.render_all(str(p), 20)
    os.rename(p, tmp_path / "b.pdf")                    # would fail on Windows if a handle stayed open


# ------------------------------------------------------------------ smart split
def fake(i, **k):
    return {"index": i, "blank": False, **k}


def test_smart_split_rules():
    pages = [fake(0, invoice="1", page_no=1), fake(1, invoice="1", page_no=2), fake(2, invoice="2"),
             fake(3), fake(4, blank=True), fake(5, mark="400000000000001"), fake(6, mark="400000000000002"),
             fake(7, vat="111111111"), fake(8, vat="222222222")]
    starts, blanks = analyze.smart_split(pages)
    # page 5 (ΜΑΡΚ, no number) stays with doc 2: the ΜΑΡΚ is often printed on the last page
    assert starts == [0, 2, 6, 8] and blanks == [4]


@needs_ocr
def test_batch_scan_end_to_end():
    infos = [analyze.analyze_page(BATCH, i, own_vats={"800555111"}) for i in range(pdf.page_count(BATCH))]
    assert analyze.smart_split(infos) == ([0, 1, 4, 6], [5])
    assert infos[6]["rotation"] == 90 and infos[6]["invoice"] == "OG-2026-0193"
    assert infos[0]["mark"] == "400001234567890"


# ------------------------------------------------------------------ naming
F = {"vat": "094123456", "invoice": "4587", "date": "2026-09-03", "company": "Ισχύς Α.Ε."}


def test_suggest_and_learn():
    names = {}
    assert naming.suggest(F, names, "Scan1.pdf", 1) == "Ισχύς_ΑΕ_4587_2026-09-03"
    assert naming.learn("ΙΣΧΥΣ_ΑΕ_4587_2026-09-03", F, names) and names == {"094123456": "ΙΣΧΥΣ_ΑΕ"}
    assert naming.suggest(F, names, "Scan1.pdf", 1, "{date}_{supplier}", "%d-%m-%Y") == "03-09-2026_ΙΣΧΥΣ_ΑΕ"
    assert naming.suggest({}, {}, "Scan1.pdf", 2, ) == "Scan1_2"
    assert naming.subfolder("{year}/{month}", F, names, "x", 1) == os.path.join("2026", "09")
    assert naming.safe_name('a/b:c*?"<>|') == "a-b-c------"


# ------------------------------------------------------------------ sending
def test_send_to_drive(tmp_path):
    inbox, drive = tmp_path / "in", tmp_path / "My Drive"
    inbox.mkdir()
    drive.mkdir()
    src = inbox / "Scan1.pdf"
    src.write_bytes(open(BATCH, "rb").read())
    st = store.Store(str(tmp_path / "data"))
    settings = dict(st.settings, drive_folder=str(drive), subfolder_template="{year}")
    parts = [{"name": "A", "pages": [(0, 0)], "fields": {"date": "2026-09-21"}},
             {"name": "A", "pages": [(1, 0), (2, 0), (3, 0)], "fields": {"date": "2026-07-01"}}]
    out = sender.send(str(src), parts, settings, {}, st)
    assert [os.path.relpath(p, drive) for p in out] == [os.path.join("2026", "A.pdf"), os.path.join("2026", "A (2).pdf")]
    assert not src.exists() and (inbox / "_done" / "Scan1.pdf").exists()
    assert len(st.history) == 2 and store.Store(str(tmp_path / "data")).history[0]["pages"] == 3


def test_send_without_drive_fails_safely(tmp_path):
    src = tmp_path / "x.pdf"
    src.write_bytes(open(BATCH, "rb").read())
    with pytest.raises(sender.SendError):
        sender.send(str(src), [{"name": "a", "pages": [(0, 0)]}], {"drive_folder": str(tmp_path / "missing")}, {})
    assert src.exists()


# ------------------------------------------------------------------ updater
def test_updater_check_download_verify(tmp_path, monkeypatch):
    pkg = tmp_path / "srv"
    pkg.mkdir()
    setup = b"MZ" + b"fake installer" * 100
    (pkg / updater.SETUP_NAME).write_bytes(setup)
    (pkg / (updater.SETUP_NAME + ".sha256")).write_text(hashlib.sha256(setup).hexdigest() + "  x\n")
    srv = HTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(pkg)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}/"
    release = {"tag_name": "v3.1.0", "html_url": "x", "body": "", "assets": [
        {"name": updater.SETUP_NAME, "browser_download_url": base + updater.SETUP_NAME},
        {"name": updater.SETUP_NAME + ".sha256", "browser_download_url": base + updater.SETUP_NAME + ".sha256"}]}
    real = net.request
    monkeypatch.setattr(net, "request", lambda url, **k: (200, json.dumps(release).encode()) if "api.github.com" in url else real(url, **k))
    info = updater.check(current="3.0.1")
    assert info["version"] == "3.1.0" and updater.check(current="3.1.0") is None
    path = updater.download_and_verify(info)
    assert open(path, "rb").read() == setup
    (pkg / (updater.SETUP_NAME + ".sha256")).write_text("0" * 64)
    with pytest.raises(RuntimeError, match="checksum"):
        updater.download_and_verify(info)
    srv.shutdown()
