"""Turn invoice text into fields. Greek-aware (accents, ΑΦΜ, ΜΑΡΚ)."""
import re
import datetime
import unicodedata


# ---------------------------------------------------------------- text
def normalize(s):
    """Upper-case, accents removed: 'Τιμολόγιο' -> 'ΤΙΜΟΛΟΓΙΟ'. Length is preserved."""
    decomposed = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").upper()


_W = r"A-Z0-9Α-Ω"


def keyword_regex(key):
    return re.compile(rf"(?<![{_W}]){re.escape(normalize(key))}(?![{_W}])")


# ---------------------------------------------------------------- patterns
DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\s?[/\-.]\s?(\d{1,2})\s?[/\-.]\s?(\d{4}|\d{2})(?!\d)")
ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
DATE_LABEL_RE = re.compile(r"(ΗΜΕΡΟΜΗΝΙΑ|ΗΜ/ΝΙΑ|ΗΜ\.?\s*ΕΚΔ|ΗΜΕΡ\.|INVOICE DATE|DATE OF ISSUE|DATE)")
VAT_RE = re.compile(r"(?:Α\.?\s?Φ\.?\s?Μ\.?|VAT\s*(?:NO|NUMBER|REG)?\.?|TAX\s*ID)\s*[:.]?\s*(?:EL|ΕL|GR)?\s*(\d{9})(?!\d)")
MARK_RE = re.compile(r"(?:Μ\W{0,2}Α\W{0,2}Ρ\W{0,2}Κ|MARK)\W{0,4}(\d{15})(?!\d)")

INVOICE_LABELS = [
    r"ΑΡΙΘΜΟΣ\s+(?:ΠΑΡΑΣΤΑΤΙΚΟΥ|ΤΙΜΟΛΟΓΙΟΥ)",
    r"ΑΡ\.?\s*(?:ΠΑΡΑΣΤΑΤΙΚΟΥ|ΠΑΡ/ΚΟΥ|ΤΙΜΟΛΟΓΙΟΥ|ΤΙΜ\.)",
    r"INVOICE\s*(?:NO\.?|NUMBER|NUM\.?|#)",
    r"ΑΡΙΘΜΟΣ",
    r"ΑΡ\.",
    r"ΤΙΜΟΛΟΓΙΟ(?:\s+(?:ΠΩΛΗΣΗΣ|ΠΑΡΟΧΗΣ\s+ΥΠΗΡΕΣΙΩΝ))?(?:\s*-\s*ΔΕΛΤΙΟ\s+ΑΠΟΣΤΟΛΗΣ)?",
    r"INVOICE",
    r"(?<![A-ZΑ-Ω])(?:NO|ΝΟ)\.?",
]
_INV_TOKEN = r"((?:[A-ZΑ-Ω]{1,4}[\-/ ]?)?\d[0-9A-ZΑ-Ω\-/]{0,19})"
_SEP = r"[\s#:.№°\-]{0,6}(?:(?:NO|ΝΟ|ΑΡ|NUMBER|ΑΡΙΘΜΟΣ)\b\.?[\s#:.№°\-]{0,4})?"
INVOICE_RES = [re.compile(l + _SEP + _INV_TOKEN) for l in INVOICE_LABELS]

TOTAL_LABEL_RE = re.compile(r"(ΠΛΗΡΩΤΕΟ|ΓΕΝΙΚΟ\s+ΣΥΝΟΛΟ|ΤΕΛΙΚΟ\s+ΠΟΣΟ|ΣΥΝΟΛΟ|GRAND\s+TOTAL|AMOUNT\s+DUE|TOTAL)")
TOTAL_EXCLUDE_RE = re.compile(r"(ΠΟΣΟΤ|QTY|QUANTITY|ΤΕΜΑΧ|ΚΙΛ|ΒΑΡΟΣ|WEIGHT)")
NOT_ITEM_RE = re.compile(r"(ΣΥΝΟΛ|TOTAL|ΚΑΘΑΡΗ\s+ΑΞΙΑ|ΜΙΚΤΗ|NET\s+(?:AMOUNT|VALUE)|ΑΞΙΑ\s*:|Φ\.?Π\.?Α|VAT|ΠΛΗΡΩΤΕΟ|ΕΚΠΤΩΣ|DISCOUNT|ΥΠΟΛΟΙΠ|BALANCE|ΚΡΑΤΗΣ|ΠΡΟΚΑΤΑΒ)")
MONEY_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,\s]\d{3})+[.,]\d{2}|\d+[.,]\d{2})(?!\d)")
MONEY_TOKEN_RE = re.compile(r"^€?(\d{1,3}(?:[.,]\d{3})+[.,]\d{2,3}|\d+[.,]\d{2,3})€?$")
NUMBER_TOKEN_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
UNIT_WORDS = {"ΤΕΜ", "ΤΕΜ.", "ΤΜΧ", "ΤΜΧ.", "ΤΕΜΑΧΙΑ", "PCS", "PC", "PCS.", "EA", "UNIT", "UNITS",
              "KG", "ΚΙΛΑ", "ΚΓΡ", "LT", "L", "ΛΙΤ", "M", "Μ", "MT", "ΜΕΤ", "SET", "ΣΕΤ", "BOX", "ΚΙΒ"}
FILLER_TOKENS = {"€", "EUR", "%", "X", "-"}

COMPANY_SKIP_RE = re.compile(
    r"(ΤΙΜΟΛΟΓΙΟ|INVOICE|ΣΕΛΙΔΑ|PAGE|ΗΜΕΡΟΜΗΝΙΑ|DATE|ΑΦΜ|Α\.Φ\.Μ|ΔΟΥ|Δ\.Ο\.Υ|ΤΗΛ|TEL|FAX|EMAIL|E-MAIL|WWW|"
    r"ΠΡΩΤΟΤΥΠΟ|ORIGINAL|COPY|ΑΝΤΙΓΡΑΦΟ|ΜΑΡΚ|MARK)")


# ---------------------------------------------------------------- numbers
def parse_amount(s):
    s = s.replace(" ", "").replace("€", "")
    last = max(s.rfind(","), s.rfind("."))
    if last < 0:
        try:
            return float(s)
        except ValueError:
            return None
    whole, dec = re.sub(r"[.,]", "", s[:last]), s[last + 1:]
    try:
        return float(f"{whole}.{dec}")
    except ValueError:
        return None


def parse_money(s):
    """'576,60' '576.60' '1.234,56' '1,234.56' '576' '€ 576,60' '1.234' -> float or None."""
    s = re.sub(r"[^\d.,]", "", s or "")
    if not s:
        return None
    if re.search(r"[.,]\d{2}$", s):
        return parse_amount(s)
    if re.search(r"[.,]\d{3}$", s) and not re.search(r"[.,]\d{1,2}[.,]", s):
        return float(re.sub(r"[.,]", "", s))
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


# ---------------------------------------------------------------- fields
def parse_date(text_norm):
    def valid(d, m, y):
        y = int(y) + (2000 if int(y) < 100 else 0)
        try:
            return datetime.date(y, int(m), int(d)).isoformat()
        except ValueError:
            return None

    found = [(m.start(), valid(*m.groups())) for m in DATE_RE.finditer(text_norm)]
    found += [(m.start(), valid(m.group(3), m.group(2), m.group(1))) for m in ISO_DATE_RE.finditer(text_norm)]
    found = sorted(f for f in found if f[1])
    if not found:
        return ""
    for lbl in DATE_LABEL_RE.finditer(text_norm):
        for pos, iso in found:
            if 0 <= pos - lbl.end() <= 40:
                return iso
    return found[0][1]


def parse_vats(text_norm):
    out = []
    for m in VAT_RE.finditer(text_norm):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def parse_mark(text_norm, qr_texts=()):
    m = MARK_RE.search(text_norm)
    if m:
        return m.group(1)
    for q in qr_texts:  # some providers put the ΜΑΡΚ in the QR link
        m = re.search(r"mark[=/:](\d{15})", q, re.I)
        if m:
            return m.group(1)
    return ""


def parse_invoice_number(text, text_norm):
    for rx in INVOICE_RES:
        for m in rx.finditer(text_norm):
            token = m.group(1).strip(" -/")
            if DATE_RE.fullmatch(token) or ISO_DATE_RE.fullmatch(token):
                continue
            digits = re.sub(r"\D", "", token)
            if len(digits) == 9 and "ΦΜ" in text_norm[max(0, m.start() - 8):m.start(1)]:
                continue
            if len(digits) >= 10:
                continue
            if len(text) == len(text_norm):
                token = text[m.start(1):m.start(1) + len(m.group(1))].strip(" -/")
            return re.sub(r"\s+", "", token)
    return ""


def parse_total(lines_norm):
    best = None
    for i, line in enumerate(lines_norm):
        lab = TOTAL_LABEL_RE.search(line)
        if not lab or TOTAL_EXCLUDE_RE.search(line):
            continue
        amounts = MONEY_RE.findall(line[lab.end():])
        if not amounts and i + 1 < len(lines_norm):
            amounts = MONEY_RE.findall(lines_norm[i + 1])
        for a in amounts:
            v = parse_amount(a)
            if v is not None and (best is None or v > best):
                best = v
    return best


def parse_item_line(line):
    """'Σχοινί 12mm 10 τεμ 12,50 € 125,00 €' -> dict(description, qty, unit, unit_price, amount)."""
    n = normalize(line)
    if NOT_ITEM_RE.search(n):
        return None
    tokens = line.split()
    ntok = n.split()

    def numericish(t):
        return bool(MONEY_TOKEN_RE.match(t) or NUMBER_TOKEN_RE.match(t) or t in UNIT_WORDS
                    or t in FILLER_TOKENS or re.fullmatch(r"\d+%", t))

    i = len(ntok)
    while i > 0 and numericish(ntok[i - 1]):
        i -= 1
    desc, tail = " ".join(tokens[:i]), ntok[i:]
    if sum(ch.isalpha() for ch in desc) < 3 or not tail or desc.rstrip().endswith(":"):
        return None
    money = [parse_amount(t.strip("€")) for t in tail if MONEY_TOKEN_RE.match(t)]
    if not money:
        return None
    qty, unit = None, ""
    for j, t in enumerate(tail):
        if NUMBER_TOKEN_RE.match(t) and j + 1 < len(tail) and tail[j + 1] in UNIT_WORDS:
            qty, unit = parse_amount(t) if re.search(r"[.,]", t) else float(t), tokens[i + j + 1]
            break
    if qty is None and i > 0:
        # OCR often glues quantity and unit onto the description end: 'Αλυσίδα 8mm 30μ'
        m = re.fullmatch(r"(\d+(?:[.,]\d+)?)(\D+)", ntok[i - 1])
        if m and m.group(2) in UNIT_WORDS and len(tokens[:i]) > 1:
            qty = float(m.group(1).replace(",", "."))
            unit = tokens[i - 1][len(m.group(1)):]
            desc = " ".join(tokens[:i - 1])
    if qty is None:
        plain = [t for t in tail if NUMBER_TOKEN_RE.match(t) and not MONEY_TOKEN_RE.match(t)]
        if plain:
            qty = float(plain[0].replace(",", "."))
        elif len(money) >= 3:
            qty = money[0]
            money = money[1:]
    amount = money[-1]
    unit_price = money[-2] if len(money) >= 2 else (amount / qty if qty else amount)
    return {"description": desc, "qty": qty if qty is not None else 1.0, "unit": unit,
            "unit_price": round(unit_price, 4), "amount": amount}


def parse_items(lines):
    out = []
    for l in lines:
        item = parse_item_line(l)
        if item:
            out.append(item)
    return out


# ---------------------------------------------------------------- supplier
def match_supplier(text_norm, vats, suppliers, own_vats=()):
    """suppliers: [{'id', 'name', 'vats': [...], 'keywords': [...]}]. Returns (supplier, how)."""
    for vat in vats:
        if vat in own_vats:
            continue
        for s in suppliers:
            if vat in s["vats"]:
                return s, f"ΑΦΜ {vat}"
    best = None
    for s in suppliers:
        for kw in s["keywords"]:
            m = keyword_regex(kw).search(text_norm)
            if m and (best is None or (m.start(), -len(kw)) < best[0]):
                best = ((m.start(), -len(kw)), s, kw)
    if best:
        return best[1], f"keyword “{best[2]}”"
    return None, ""


def guess_company(lines):
    for line in lines[:15]:
        clean = line.strip()
        n = normalize(clean)
        if sum(ch.isalpha() for ch in clean) >= 4 and not COMPANY_SKIP_RE.search(n) and not DATE_RE.search(n):
            return re.sub(r"\s{2,}.*$", "", clean)
    return ""


def parse_invoice(text, suppliers, own_vats=(), qr_texts=()):
    text = text or ""
    text_norm = normalize(text)
    lines = [l for l in text.splitlines() if l.strip()]
    lines_norm = [normalize(l) for l in lines]
    vats = parse_vats(text_norm)
    supplier, how = match_supplier(text_norm, vats, suppliers, own_vats)
    return {
        "supplier": supplier["name"] if supplier else guess_company(lines),
        "supplier_id": supplier["id"] if supplier else None,
        "matched_by": how,
        "supplier_vat": next((v for v in vats if v not in own_vats), ""),
        "invoice": parse_invoice_number(text, text_norm),
        "date": parse_date(text_norm),
        "total": parse_total(lines_norm),
        "mark": parse_mark(text_norm, qr_texts),
        "items": parse_items(lines),
    }
