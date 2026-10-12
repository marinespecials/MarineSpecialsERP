"""SQLite storage: invoices, suppliers, payments, myDATA cache, settings."""
import os
import csv
import json
import sqlite3
import datetime
import threading
from contextlib import contextmanager

from .parser import normalize

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    vats TEXT NOT NULL DEFAULT '[]',
    keywords TEXT NOT NULL DEFAULT '[]',
    payment_terms_days INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY,
    supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    supplier_name TEXT NOT NULL,
    supplier_vat TEXT NOT NULL DEFAULT '',
    invoice_no TEXT NOT NULL,
    invoice_date TEXT NOT NULL DEFAULT '',
    total REAL,
    net REAL,
    vat_amount REAL,
    mark TEXT NOT NULL DEFAULT '',
    qr_url TEXT NOT NULL DEFAULT '',
    due_date TEXT NOT NULL DEFAULT '',
    paid_date TEXT NOT NULL DEFAULT '',
    payment_notes TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL DEFAULT '',
    original_name TEXT NOT NULL DEFAULT '',
    read_by TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT '',
    filed_at TEXT NOT NULL,
    items_json TEXT NOT NULL DEFAULT '[]',
    stock_status TEXT NOT NULL DEFAULT '',
    stock_error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_inv_supplier ON invoices(supplier_name, invoice_no);
CREATE INDEX IF NOT EXISTS ix_inv_mark ON invoices(mark);
CREATE TABLE IF NOT EXISTS mydata_docs (
    mark TEXT PRIMARY KEY,
    uid TEXT, issuer_vat TEXT, issuer_name TEXT, series TEXT, aa TEXT,
    issue_date TEXT, invoice_type TEXT, net REAL, vat REAL, gross REAL,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "input_folder": "",
    "output_folder": "",
    "folder_layout": "year_supplier",   # or "flat"
    "own_vat_numbers": [],
    "default_terms_days": 0,          # payment terms when the supplier has none set
    "ocr_languages": "ell+eng",
    "label_url": "https://marine-specials-tracker.onrender.com/invoice/{invoice}",
    "theme": "system",
    "auto_file": False,              # inbox watcher files confident invoices on its own
    "imap_enabled": False, "imap_host": "", "imap_port": 993, "imap_user": "",
    "imap_folder": "INBOX", "imap_interval_min": 10, "imap_mark_read": True,
    "mydata_enabled": False, "mydata_user": "", "mydata_test_env": False,
    "stock_enabled": False, "stock_url": "", "stock_auto_send": True,
    "update_check": True,
}


def today():
    return datetime.date.today().isoformat()


class Database:
    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with self._db() as c:
            c.executescript(SCHEMA)
            c.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA journal_mode=WAL")
        return c

    @contextmanager
    def _db(self):
        c = self._conn()
        try:
            with c:
                yield c
        finally:
            c.close()

    def _q(self, sql, args=(), one=False):
        with self._lock, self._db() as c:
            rows = c.execute(sql, args).fetchall()
        rows = [dict(r) for r in rows]
        return (rows[0] if rows else None) if one else rows

    def _x(self, sql, args=()):
        with self._lock, self._db() as c:
            cur = c.execute(sql, args)
            return cur.lastrowid

    # ------------------------------------------------------------ settings
    def settings(self):
        out = dict(DEFAULT_SETTINGS)
        for r in self._q("SELECT key, value FROM settings"):
            out[r["key"]] = json.loads(r["value"])
        return out

    def get(self, key):
        return self.settings().get(key)

    def set(self, key, value):
        self._x("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)))

    def set_many(self, d):
        for k, v in d.items():
            self.set(k, v)

    # ------------------------------------------------------------ suppliers
    @staticmethod
    def _sup(r):
        r["vats"] = json.loads(r["vats"])
        r["keywords"] = json.loads(r["keywords"])
        return r

    def suppliers(self):
        return [self._sup(r) for r in self._q("SELECT * FROM suppliers ORDER BY name COLLATE NOCASE")]

    def supplier(self, sid):
        r = self._q("SELECT * FROM suppliers WHERE id=?", (sid,), one=True)
        return self._sup(r) if r else None

    def supplier_by_name(self, name):
        target = normalize(name).strip()
        for s in self.suppliers():
            if normalize(s["name"]).strip() == target:
                return s
        return None

    def supplier_by_vat(self, vat):
        for s in self.suppliers():
            if vat in s["vats"]:
                return s
        return None

    def save_supplier(self, name, vats=(), keywords=(), payment_terms_days=0, notes="", sid=None):
        vats = sorted({v.strip() for v in vats if v.strip()})
        keywords = [k.strip() for k in dict.fromkeys(keywords) if k.strip()]
        args = (name.strip(), json.dumps(vats), json.dumps(keywords, ensure_ascii=False),
                int(payment_terms_days or 0), notes)
        if sid:
            self._x("UPDATE suppliers SET name=?, vats=?, keywords=?, payment_terms_days=?, notes=? WHERE id=?",
                    args + (sid,))
            self._x("UPDATE invoices SET supplier_name=? WHERE supplier_id=?", (name.strip(), sid))
            return sid
        return self._x("INSERT INTO suppliers(name, vats, keywords, payment_terms_days, notes) VALUES(?,?,?,?,?)", args)

    def ensure_supplier(self, name, vat="", keyword=""):
        """Get-or-create by name, adding a VAT / keyword so it's recognised next time."""
        s = self.supplier_by_name(name)
        if s is None:
            sid = self.save_supplier(name, [vat] if vat else [], [keyword] if keyword else [])
            return self.supplier(sid)
        changed = False
        if vat and vat not in s["vats"]:
            s["vats"].append(vat)
            changed = True
        if keyword and keyword not in s["keywords"]:
            s["keywords"].append(keyword)
            changed = True
        if changed:
            self.save_supplier(s["name"], s["vats"], s["keywords"], s["payment_terms_days"], s["notes"], s["id"])
        return self.supplier(s["id"])

    def delete_supplier(self, sid):
        self._x("DELETE FROM suppliers WHERE id=?", (sid,))

    # ------------------------------------------------------------ invoices
    INVOICE_FIELDS = ["supplier_id", "supplier_name", "supplier_vat", "invoice_no", "invoice_date", "total",
                      "net", "vat_amount", "mark", "qr_url", "due_date", "paid_date", "payment_notes",
                      "file_path", "original_name", "read_by", "mode", "filed_at", "items_json",
                      "stock_status", "stock_error"]

    def add_invoice(self, **f):
        f.setdefault("filed_at", datetime.datetime.now().isoformat(timespec="seconds"))
        if isinstance(f.get("items_json"), list):
            f["items_json"] = json.dumps(f["items_json"], ensure_ascii=False)
        cols = [k for k in self.INVOICE_FIELDS if k in f and f[k] is not None]
        return self._x(f"INSERT INTO invoices({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                       [f[k] for k in cols])

    def update_invoice(self, iid, **f):
        if isinstance(f.get("items_json"), list):
            f["items_json"] = json.dumps(f["items_json"], ensure_ascii=False)
        cols = [k for k in f if k in self.INVOICE_FIELDS]
        if cols:
            self._x(f"UPDATE invoices SET {','.join(c + '=?' for c in cols)} WHERE id=?",
                    [f[c] for c in cols] + [iid])

    def delete_invoice(self, iid):
        self._x("DELETE FROM invoices WHERE id=?", (iid,))

    def invoice(self, iid):
        return self._q("SELECT * FROM invoices WHERE id=?", (iid,), one=True)

    def invoices(self):
        rows = self._q("SELECT * FROM invoices ORDER BY invoice_date DESC, id DESC")
        t = today()
        for r in rows:
            r["status"] = "paid" if r["paid_date"] else ("overdue" if r["due_date"] and r["due_date"] < t else "unpaid")
        return rows

    def find_duplicate(self, supplier_name, invoice_no, mark="", supplier_vat=""):
        if mark:
            r = self._q("SELECT * FROM invoices WHERE mark=?", (mark,), one=True)
            if r:
                return r
        inv = normalize(invoice_no).replace(" ", "")
        sname = normalize(supplier_name)
        for r in self._q("SELECT * FROM invoices"):
            if normalize(r["invoice_no"]).replace(" ", "") != inv:
                continue
            if normalize(r["supplier_name"]) == sname or (supplier_vat and r["supplier_vat"] == supplier_vat):
                return r
        return None

    def mark_paid(self, ids, date=None, notes=None):
        for iid in ids:
            if notes is None:
                self._x("UPDATE invoices SET paid_date=? WHERE id=?", (date or "", iid))
            else:
                self._x("UPDATE invoices SET paid_date=?, payment_notes=? WHERE id=?", (date or "", notes, iid))

    def pending_stock(self):
        return self._q("SELECT * FROM invoices WHERE stock_status IN ('pending','failed')")

    # ------------------------------------------------------------ myDATA cache
    def save_mydata_docs(self, docs):
        now = datetime.datetime.now().isoformat(timespec="seconds")
        with self._lock, self._db() as c:
            for d in docs:
                c.execute("""INSERT OR REPLACE INTO mydata_docs(mark, uid, issuer_vat, issuer_name, series, aa,
                             issue_date, invoice_type, net, vat, gross, fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (d["mark"], d.get("uid"), d.get("issuer_vat"), d.get("issuer_name"), d.get("series"),
                           d.get("aa"), d.get("issue_date"), d.get("invoice_type"), d.get("net"), d.get("vat"),
                           d.get("gross"), now))

    def mydata_doc(self, mark):
        return self._q("SELECT * FROM mydata_docs WHERE mark=?", (mark,), one=True)

    def mydata_find(self, issuer_vat, aa):
        """Match a PDF without a printed ΜΑΡΚ by supplier ΑΦΜ + invoice number."""
        digits = "".join(ch for ch in aa if ch.isdigit()).lstrip("0")
        for r in self._q("SELECT * FROM mydata_docs WHERE issuer_vat=?", (issuer_vat,)):
            if "".join(ch for ch in (r["aa"] or "") if ch.isdigit()).lstrip("0") == digits and digits:
                return r
        return None

    def mydata_count(self):
        return self._q("SELECT COUNT(*) AS n FROM mydata_docs", one=True)["n"]

    # ------------------------------------------------------------ legacy import
    def import_legacy(self, rules_path=None, ledger_csv=None):
        """Bring in v1.x supplier_rules.json and invoice_ledger.csv (idempotent)."""
        added_s = added_i = 0
        if rules_path and os.path.exists(rules_path):
            with open(rules_path, encoding="utf-8") as f:
                rules = json.load(f)
            for key, name in rules.items():
                before = self.supplier_by_name(name)
                is_vat = key.isdigit() and len(key) == 9
                self.ensure_supplier(name, vat=key if is_vat else "", keyword="" if is_vat else key)
                added_s += before is None
        if ledger_csv and os.path.exists(ledger_csv):
            out_dir = os.path.dirname(ledger_csv)
            with open(ledger_csv, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    if self.find_duplicate(row.get("Supplier", ""), row.get("Invoice", "")):
                        continue
                    total = row.get("Total") or None
                    self.add_invoice(
                        supplier_name=row.get("Supplier", ""), invoice_no=row.get("Invoice", ""),
                        invoice_date=row.get("Invoice Date", ""), total=float(total) if total else None,
                        supplier_vat=row.get("Supplier VAT", ""),
                        file_path=os.path.join(out_dir, row.get("File", "")),
                        original_name=row.get("Original File", ""), read_by=row.get("Read By", ""),
                        mode="imported", filed_at=row.get("Filed At") or datetime.datetime.now().isoformat())
                    added_i += 1
        return added_s, added_i

    # ------------------------------------------------------------ reports
    def monthly_spend(self, months=12):
        rows = self._q("""SELECT substr(invoice_date,1,7) AS ym, SUM(total) AS spend, COUNT(*) AS n
                          FROM invoices WHERE invoice_date != '' GROUP BY ym ORDER BY ym DESC LIMIT ?""", (months,))
        return list(reversed(rows))

    def supplier_spend(self, year=None):
        where, args = ("WHERE substr(invoice_date,1,4)=?", (str(year),)) if year else ("", ())
        return self._q(f"""SELECT supplier_name, SUM(total) AS spend, COUNT(*) AS n FROM invoices {where}
                           GROUP BY supplier_name ORDER BY spend DESC""", args)
