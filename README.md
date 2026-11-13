# Marine Specials PDF 3.0

Scan a pile of invoices into one PDF → the app **splits it into documents, straightens the pages, names each
file from its contents and saves it to Google Drive.**

## What it does
- **Smart split:** finds where each document starts from its page numbers ("Σελίδα 1/3"), invoice number, ΜΑΡΚ or
  ΑΦΜ. You can also cut every page, or click a page and press **S** to cut there.
- **Straightens scans:** sideways or upside-down pages are turned upright automatically.
- **Removes blank pages:** the empty backs of double-sided scans are dropped.
- **Names files for you:** for example `ΙΣΧΥΣ_ΑΕ_4587_2026-09-03.pdf`, built from supplier, invoice number and date.
  Correct a supplier name once and it's remembered by ΑΦΜ.
- **Sends to Google Drive:** files go into your Drive for desktop folder, optionally into `{year}` / `{month}`
  subfolders. The original scan moves to `Inbox\_done`.
- **Name boxes like v1:** each document has **Company**, **Invoice #** and **Date** boxes, filled in from the page.
  The file name (`COMPANY_INVOICE_DATE.pdf`) updates as you type. *✎ Type full name* lets you write any name.
- **Rename anything:** press **F2** on a file in the list to rename it with the same three boxes. The app never keeps
  files locked.
- **Keeps a history** of everything it saved, with Open / Show in folder.
- **Updates itself** from GitHub Releases.

Everything is lossless: pages are copied, not re-scanned, so the files stay small and keep any text.

## Setup
1. Install **Google Drive for desktop** (google.com/drive/download) and sign in. Drive then appears as `G:\My Drive`.
2. Install the app with `MarineSpecialsERP-Setup.exe` from the GitHub *Releases* page.
3. In the app's top bar, choose the **Inbox** (where your scanner saves) and the **Drive** folder,
   e.g. `G:\My Drive\Τιμολόγια`. **Settings → Find Drive** locates it for you.

## Daily use
1. Scan into the inbox, or drag PDFs onto the window.
2. Click the PDF. Pages appear with a coloured frame per document, and the names fill in as pages are read.
3. Fix anything you want:
   - **S** = cut here
   - **R / L** = rotate right / left
   - **Del** = remove a page
   - **double-click** = big preview
   - type in the name boxes
4. Press **Ctrl+Enter** (or *Send to Drive*). The next PDF opens automatically.

## Settings worth knowing
- **Name pattern:** default `{supplier}_{invoice}_{date}`. Available fields are `{supplier} {invoice} {date} {year}
  {month} {vat} {mark} {original} {n}`. Empty fields are skipped.
- **Subfolders in Drive:** e.g. `{year}` or `{year}/{month}`.
- **Our ΑΦΜ:** enter it so it's never taken as the supplier's.

## Releasing an update
```
git add .
git commit -m "What changed"
git tag v3.0.1
git push origin main v3.0.1
```
GitHub Actions builds the app (with Tesseract, Greek + English inside) and publishes a Release. Installed apps show
**Install & restart**.

## Developers
```
pip install -r requirements.txt
python main.py
python -m pytest tests
pyinstaller MarineSpecialsERP.spec --noconfirm
```
`MarineSpecialsERP.exe --check file.pdf` writes what the app reads from each page to
`%APPDATA%\MarineSpecialsERP\check_result.json`.

| File | Purpose |
|---|---|
| `erp/pdf.py` | open / render / save pages (PDFium, no locks) |
| `erp/analyze.py` | per-page reading, rotation, blank pages, smart split |
| `erp/naming.py` | file-name suggestions and learning |
| `erp/sender.py` | write documents to Drive, move the original to `_done` |
| `erp/ocr.py` `erp/qr.py` `erp/parser.py` | Tesseract, QR / ΜΑΡΚ, invoice fields |
| `erp/ui/` | the window: `work.py` (Split & Send), `history.py`, `settings.py` |
