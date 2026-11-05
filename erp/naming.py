"""File names: suggestions from the page contents, safe names, learning supplier names."""
import os
import re
import datetime

_BAD = '<>:"/\\|?*\x00'
DEFAULT_TEMPLATE = "{supplier}_{invoice}_{date}"
TOKENS = ("supplier", "invoice", "date", "vat", "mark", "original", "n", "year", "month")


def safe_name(s):
    """Make any text usable as a Windows file name (keeps Greek)."""
    s = "".join("-" if c in _BAD or ord(c) < 32 else c for c in (s or ""))
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:150]


def strip_pdf(name):
    return name[:-4] if name.lower().endswith(".pdf") else name


def unique_path(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


def _clean_company(s):
    s = re.sub(r"\s{2,}.*$", "", s or "").strip()
    s = re.sub(r"\.(?=\w)", "", s)                 # Α.Ε. -> ΑΕ, S.A. -> SA
    s = re.sub(r"[^\w\s&'-]", "", s).strip(" .-")
    return s.replace(" ", "_")[:40]


def fmt_date(iso, fmt="%Y-%m-%d"):
    try:
        return datetime.date.fromisoformat(iso).strftime(fmt)
    except (TypeError, ValueError):
        return ""


def values(fields, names, original, n, date_format="%Y-%m-%d"):
    vat = fields.get("vat", "")
    supplier = names.get(vat) if vat else None
    return {
        "supplier": supplier or _clean_company(fields.get("company", "")),
        "invoice": re.sub(r"\s+", "", fields.get("invoice", "")).replace("/", "-"),
        "date": fmt_date(fields.get("date", ""), date_format),
        "year": (fields.get("date") or "")[:4],
        "month": (fields.get("date") or "")[5:7],
        "vat": vat, "mark": fields.get("mark", ""),
        "original": strip_pdf(original), "n": str(n),
    }


def render(template, vals):
    """Fill a template like "{supplier}_{invoice}_{date}".
    An empty field disappears together with the separator in front of it."""
    parts = re.split(r"(\{\w+\})", template or DEFAULT_TEMPLATE)
    lead, trail = parts[0], (parts[-1] if len(parts) > 1 else "")
    pieces, pending = [], ""
    for p in parts[1:-1]:
        m = re.fullmatch(r"\{(\w+)\}", p)
        if m:
            v = vals.get(m.group(1), "")
            if v:
                pieces.append((pending, v))
            pending = ""
        else:
            pending = p
    body = "".join((sep if i else "") + v for i, (sep, v) in enumerate(pieces))
    return f"{lead}{body}{trail}" if body else ""


def suggest(fields, names, original, n, template=DEFAULT_TEMPLATE, date_format="%Y-%m-%d"):
    vals = values(fields, names, original, n, date_format)
    name = safe_name(render(template, vals))
    if not name or name == vals["supplier"]:
        # nothing useful found - fall back to the original name
        base = strip_pdf(original)
        name = safe_name(f"{name}_{base}" if name else base)
        if n > 1 or fields.get("_multi"):
            name += f"_{n}"
    return name


def subfolder(template, fields, names, original, n, date_format="%Y-%m-%d"):
    if not template:
        return ""
    vals = values(fields, names, original, n, date_format)
    parts = [safe_name(render(p, vals)) for p in re.split(r"[\\/]", template)]
    return os.path.join(*[p for p in parts if p]) if any(parts) else ""


def learn(final_name, fields, names, template=DEFAULT_TEMPLATE):
    """Remember the supplier name the user typed, keyed by ΑΦΜ, for next time."""
    vat = fields.get("vat")
    if not vat or "{supplier}" not in (template or ""):
        return False
    t_parts = (template or "").split("_")
    f_parts = strip_pdf(final_name).split("_")
    try:
        pos = t_parts.index("{supplier}")
    except ValueError:
        return False
    # supplier names may contain "_" themselves: take what's left after the other fields
    tail = len(t_parts) - pos - 1
    chosen = "_".join(f_parts[pos:len(f_parts) - tail if tail else None]).strip()
    if chosen and re.search(r"[^\W\d_]", chosen) and names.get(vat) != chosen:
        names[vat] = chosen
        return True
    return False
