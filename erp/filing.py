"""Move approved PDFs into the archive, record them, print labels."""
import os
import re
import shutil
import datetime
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageFont

_BAD = '<>:"/\\|?*'


def safe_part(s, keep_underscore=True):
    s = (s or "").strip()
    for c in _BAD:
        s = s.replace(c, "-")
    s = re.sub(r"\s+", "-", s)
    if not keep_underscore:
        s = s.replace("_", "-")
    return s.strip(".-") or "UNKNOWN"


def build_filename(supplier, invoice, date):
    return f"{safe_part(supplier)}_{safe_part(invoice, False)}_{safe_part(date or 'undated', False)}.pdf"


def unique_path(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


def target_folder(output_folder, supplier, date, layout="year_supplier"):
    if layout == "flat":
        return output_folder
    year = (date or "")[:4] if re.match(r"\d{4}", date or "") else "undated"
    return os.path.join(output_folder, year, safe_part(supplier))


def file_invoice(db, src_path, output_folder, f, mode="manual", layout="year_supplier"):
    """f: dict with supplier, supplier_id, supplier_vat, invoice, date, total, net, vat_amount,
    mark, qr_url, due_date, items, source. Returns (invoice_id, destination path)."""
    folder = target_folder(output_folder, f["supplier"], f.get("date"), layout)
    os.makedirs(folder, exist_ok=True)
    dest = unique_path(os.path.join(folder, build_filename(f["supplier"], f["invoice"], f.get("date"))))
    shutil.move(src_path, dest)
    iid = db.add_invoice(
        supplier_id=f.get("supplier_id"), supplier_name=f["supplier"], supplier_vat=f.get("supplier_vat", ""),
        invoice_no=f["invoice"], invoice_date=f.get("date", ""), total=f.get("total"), net=f.get("net"),
        vat_amount=f.get("vat_amount"), mark=f.get("mark", ""), qr_url=f.get("qr_url", ""),
        due_date=f.get("due_date", ""), file_path=dest, original_name=os.path.basename(src_path),
        read_by=f.get("source", ""), mode=mode, items_json=f.get("items", []),
        stock_status=f.get("stock_status", ""),
    )
    return iid, dest


# ---------------------------------------------------------------- labels
def _font(size):
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def generate_label(supplier, invoice, date, output_folder, url_template):
    import qrcode
    folder = os.path.join(output_folder, "Warehouse_Labels")
    os.makedirs(folder, exist_ok=True)
    url = (url_template or "{invoice}").format(invoice=quote(invoice), supplier=quote(supplier))
    q = qrcode.QRCode(box_size=10, border=4)
    q.add_data(url)
    q.make(fit=True)
    img = q.make_image(fill_color="#0B3C5D", back_color="white").convert("RGB")
    w = max(img.width, 600)
    label = Image.new("RGB", (w, img.height + 150), "white")
    label.paste(img, ((w - img.width) // 2, 0))
    draw = ImageDraw.Draw(label)
    y = img.height + 5
    for text, font in ((supplier.replace("_", " "), _font(34)), (f"Invoice {invoice}   {date}", _font(26))):
        draw.text(((w - draw.textlength(text, font=font)) / 2, y), text, fill="black", font=font)
        y += 55
    path = os.path.join(folder, f"LABEL_{build_filename(supplier, invoice, date)[:-4]}.png")
    label.save(path)
    return path


def open_path(path):
    """Open a file/folder with the default Windows app."""
    if os.name == "nt":
        os.startfile(path)  # noqa: S606
    else:
        import subprocess
        subprocess.Popen(["xdg-open", path])


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")
