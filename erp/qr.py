"""Read QR codes printed on invoices (Greek e-invoices carry one linked to the ΜΑΡΚ)."""
from . import pdf

try:
    import zxingcpp
except ImportError:
    zxingcpp = None


def read_qr_codes(path, index=0, dpi=200, image=None):
    """Return the texts of all QR codes on a page (usually a verification URL)."""
    if zxingcpp is None:
        return []
    try:
        img = image if image is not None else pdf.render(path, index, dpi, grayscale=True)
        results = zxingcpp.read_barcodes(img, formats=zxingcpp.BarcodeFormat.QRCode)
        return [r.text for r in results if r.text]
    except Exception:
        return []
