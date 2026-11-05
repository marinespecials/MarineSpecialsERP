"""PDF access through PDFium (pip package pypdfium2) - no Poppler needed.

Every call opens the file, does its job and closes it again, so the app never
keeps a PDF locked: you can rename, move or delete files at any time.
PDFium is not thread-safe, so all calls go through one lock.
"""
import os
import threading
from contextlib import contextmanager

import pypdfium2 as pdfium

_LOCK = threading.RLock()


class PdfError(Exception):
    pass


@contextmanager
def _open(path):
    with _LOCK:
        try:
            doc = pdfium.PdfDocument(path)
        except Exception as e:
            raise PdfError(f"Can't open PDF (damaged or still being copied?): {e}") from None
        try:
            yield doc
        finally:
            doc.close()


def page_count(path):
    with _open(path) as doc:
        return len(doc)


def page_text(path, index=0):
    """Embedded text of one page ('' for scanned pages)."""
    with _open(path) as doc:
        if index >= len(doc):
            return ""
        page = doc[index]
        tp = page.get_textpage()
        try:
            return tp.get_text_range().replace("\r\n", "\n").replace("\r", "\n")
        finally:
            tp.close()
            page.close()


def render(path, index=0, dpi=150, grayscale=False, rotation=0):
    """Render one page to a PIL image, optionally turned clockwise by `rotation` degrees."""
    with _open(path) as doc:
        page = doc[index]
        try:
            img = page.render(scale=dpi / 72, grayscale=grayscale).to_pil()
        finally:
            page.close()
    if rotation % 360:
        img = img.rotate(-(rotation % 360), expand=True)
    return img


def render_all(path, dpi=40):
    """Small images of every page (for thumbnails), in one open/close."""
    out = []
    with _open(path) as doc:
        for i in range(len(doc)):
            page = doc[i]
            try:
                out.append(page.render(scale=dpi / 72).to_pil())
            finally:
                page.close()
    return out


def is_blank(img, threshold=0.0015):
    """True if a page has (almost) no ink - e.g. the empty back of a duplex scan.

    Works at ~100 DPI (thin text survives) and ignores a 4% border where scanner
    edges and shadows live. Real pages measure ~1-2% ink, empty ones ~0%.
    """
    g = img.convert("L")
    if g.width > 900:
        g = g.resize((850, int(850 * g.height / g.width)))
    w, h = g.size
    g = g.crop((int(w * .04), int(h * .04), int(w * .96), int(h * .96)))
    hist = g.histogram()
    return sum(hist[:180]) / max(1, g.width * g.height) < threshold


def save_part(src, pages, dest):
    """Write the given pages to a new PDF, losslessly.

    pages: list of (page_index, extra_rotation_clockwise) in the order wanted.
    """
    with _open(src) as doc:
        new = pdfium.PdfDocument.new()
        try:
            for n, (idx, rot) in enumerate(pages):
                new.import_pages(doc, [idx])
                if rot % 360:
                    p = new[n]
                    p.set_rotation((p.get_rotation() + rot) % 360)
                    p.close()
            tmp = dest + ".part"
            new.save(tmp)
        finally:
            new.close()
    os.replace(tmp, dest)
    return dest


def split(path, out_dir):
    """Every page to its own PDF (used by tests / simple callers)."""
    stem = os.path.splitext(os.path.basename(path))[0]
    n = page_count(path)
    return [save_part(path, [(i, 0)], os.path.join(out_dir, f"{stem}_page_{i + 1}.pdf")) for i in range(n)]
