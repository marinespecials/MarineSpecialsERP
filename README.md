# Marine Specials ERP 2.0

Desktop app for supplier invoices: **drop PDFs in → check → approve → filed, paid, in stock.**

- **Reads invoices exactly.** Digital PDFs are read directly. Scanned PDFs are read with OCR (Greek + English, built in). Greek e-invoices are **verified against AADE myDATA by ΜΑΡΚ**.
- **Inbox:** a folder watcher and an email inbox (IMAP). Drag and drop works, and so does *File all ready*.
- **Ledger:** search, filters, paid/unpaid/overdue, due dates from supplier payment terms, Excel export.
- **Suppliers:** learned automatically by ΑΦΜ, with keywords and payment terms.
- **Reports:** spend per month and per supplier.
- **Stock tracker sync:** line items are sent to your Render app.
- **Warehouse QR labels.**
- **Self-updating:** every GitHub release reaches all PCs with one click.

No Poppler, and no separate Tesseract install. Everything ships inside the app.

---

## 1. Install (on each PC)
Download **MarineSpecialsERP-Setup.exe** from the repo's *Releases* page and run it. It needs no admin rights and installs to
`%LOCALAPPDATA%\Programs\MarineSpecialsERP`.

> The first time, Windows SmartScreen may say "unrecognised app": click *More info → Run anyway*.
> A code-signing certificate removes this warning (see §8).

Your data (database, settings, logs) lives in `%APPDATA%\MarineSpecialsERP`, so updates never touch it.

## 2. First run
1. **Settings → Folders:** set the *Inbox* folder (where new PDFs arrive) and the *Archive* folder.
2. **Settings → Our company ΑΦΜ:** enter it, so it's never mistaken for a supplier.
3. Coming from v1.x? Use **Settings → Data → Import from v1.x** to load `supplier_rules.json` and `invoice_ledger.csv`.
   If `supplier_rules.json` sits next to the app, it is imported automatically.

## 3. Daily use
- PDFs in the inbox are read in the background. ✅ = ready, ⚠️ = check, ⧉ = already filed.
- Click one, check the fields (green = sure, orange = check) and press **Enter**. It's filed as
  `Archive\2026\SUPPLIER\SUPPLIER_INVOICE_DATE.pdf`, logged, labelled, and the next one opens.
- New supplier? Tick *Remember…* and it's recognised by ΑΦΜ from then on.
- **File all ready** files everything the app is confident about. **Settings → Auto-file** does this continuously.
- **Ledger:** right-click for Open PDF, Mark paid, Edit, Label, Send to stock, and the e-invoice link.

## 4. AADE myDATA (Greek invoices, exact data)
Since Oct 2026 every Greek invoice carries a **ΜΑΡΚ**. With myDATA enabled, the app downloads the invoices your
suppliers registered to your ΑΦΜ and matches each PDF by ΜΑΡΚ (or ΑΦΜ + number). Supplier, number, date and amounts
then come from AADE, not OCR.

1. At mydata.aade.gr → **«Εγγραφή στο myDATA REST API»** you get a *username* and a *subscription key*.
2. **Settings → AADE myDATA:** enter both, tick *Download received invoices*, and click **Sync now**.

The app only *reads* (`RequestDocs`). It never sends anything to AADE.

## 5. Email inbox
**Settings → Email inbox:** server, user, password and folder. New emails' PDF attachments land in the inbox.
- Gmail: `imap.gmail.com`, port 993, with an **App Password** (needs 2-step verification).
- Microsoft 365 / Outlook.com block password IMAP. Forward invoices to a Gmail mailbox, or save attachments to the inbox folder.

## 6. Stock tracker (your Render app)
When an invoice is filed, its line items are POSTed to the URL in **Settings → Stock tracker**:

```http
POST https://marine-specials-tracker.onrender.com/api/receipts
Authorization: Bearer <API key>
Content-Type: application/json

{"external_id": "094123456:4587", "supplier": "ΙΣΧΥΣ_ΑΕ", "supplier_vat": "094123456",
 "invoice": "4587", "date": "2026-09-03", "mark": "", "total": 576.60,
 "items": [{"description": "Σχοινί 12mm", "qty": 10, "unit": "τεμ", "unit_price": 12.5, "amount": 125.0}]}
```
Any 2xx answer counts as received. Failures are retried every 5 minutes. Use `external_id` to ignore repeats.
Minimal Flask endpoint for the tracker:

```python
@app.post("/api/receipts")
def receipts():
    if request.headers.get("Authorization") != f"Bearer {os.environ['ERP_API_KEY']}":
        return {"error": "unauthorized"}, 401
    data = request.get_json()
    if Receipt.query.filter_by(external_id=data["external_id"]).first():
        return {"status": "duplicate"}, 200
    for item in data["items"]:
        add_stock(item["description"], item["qty"], item["unit"], source=data["external_id"])
    db.session.add(Receipt(external_id=data["external_id"])); db.session.commit()
    return {"status": "ok"}, 201
```

## 7. Releasing an update (all PCs update themselves)
One-time: push this folder to GitHub as **`marinespecials/MarineSpecialsERP`**, as a public repo.
If the repo has another name, change `GITHUB_REPO` in `erp/__init__.py`.

For every new version:
```bash
git commit -am "What changed"
git tag v2.0.1
git push origin main v2.0.1
```
GitHub Actions (`.github/workflows/release.yml`) then:
1. runs the tests;
2. builds the app on Windows with Tesseract (Greek + English) inside;
3. publishes a Release with `MarineSpecialsERP-Setup.exe`, `MarineSpecialsERP-win64.zip` and its SHA-256.

Each running app checks on startup and shows **"Version 2.0.1 is available → Install & restart"**. It then downloads
the zip, verifies the checksum, swaps the program files and restarts. **Settings → Updates → Check now** also works.
To test a build without releasing it, run the workflow manually (*Actions → Build & Release → Run workflow*) and
download the artifact.

## 8. Good to know
- **Code signing:** an unsigned .exe triggers SmartScreen and sometimes antivirus false alarms. An OV/EV code-signing
  certificate, added as a `signtool` step in the workflow, fixes that.
- **One database per Windows user.** Each PC has its own ledger. If several people need the same ledger, the next step
  would be a small shared server (e.g. your Render app). SQLite on a network drive isn't safe.
- **myDATA:** built from AADE's published API (v1.0.x). It was tested against sample data, not your live account yet,
  so run *Sync now* once and check the count.
- **Diagnostics:** `MarineSpecialsERP.exe --check invoice.pdf` writes `check_result.json` to the data folder.
  The log is `%APPDATA%\MarineSpecialsERP\app.log`.

## 9. Developers
```bash
pip install -r requirements.txt
python main.py                 # run from source (uses an installed Tesseract if present)
python -m pytest tests         # engine + services tests
pyinstaller MarineSpecialsERP.spec --noconfirm   # local build -> dist/MarineSpecialsERP
```
```
erp/
  pdf.py        PDFium: text, render, split (replaces Poppler)
  ocr.py        Tesseract (bundled copy preferred)
  qr.py         QR codes on e-invoices
  parser.py     fields from text: supplier, ΑΦΜ, number, date, total, ΜΑΡΚ, line items
  extract.py    read (slow, cached) + interpret (fast) + myDATA enrichment
  workflow.py   approve → learn supplier → file → label
  db.py         SQLite: invoices, suppliers, myDATA cache, settings
  mydata.py  email_inbox.py  stock.py  updater.py  credentials.py
  ui/           PySide6 pages: inbox, ledger, suppliers, reports, settings
```
