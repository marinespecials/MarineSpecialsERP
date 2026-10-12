"""PDF access through PDFium (pip package pypdfium2) - replaces Poppler.

PDFium is not thread-safe, so every call goes through one lock. Calls are
short (open, read text, render one page), so this costs almost nothing.
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
            raise PdfError(f"Can't open PDF (damaged or still being written?): {e}") from None
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


def render(path, index=0, dpi=150, grayscale=False):
    """Render one page to a PIL image."""
    with _open(path) as doc:
        page = doc[index]
        try:
            bitmap = page.render(scale=dpi / 72, grayscale=grayscale)
            return bitmap.to_pil()
        finally:
            page.close()


def split(path, out_dir):
    """Write each page to its own PDF (lossless - text layer kept)."""
    stem = os.path.splitext(os.path.basename(path))[0]
    out = []
    with _open(path) as doc:
        for i in range(len(doc)):
            new = pdfium.PdfDocument.new()
            new.import_pages(doc, [i])
            target = os.path.join(out_dir, f"{stem}_page_{i + 1}.pdf")
            new.save(target)
            new.close()
            out.append(target)
    return out
