import os
import sys
import pandas as pd
import subprocess
from pdf2image import convert_from_path

# ================= DYNAMIC CONFIG =================
# Safely resolve path regardless of standard script or PyInstaller bundle
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

POPPLER_PATH = os.path.join(BASE_DIR, "poppler", "Library", "bin")


def repair_pdf(input_path):
    fixed_path = input_path.replace(".pdf", "_fixed.pdf")

    try:
        subprocess.run([
            os.path.join(POPPLER_PATH, "pdftocairo.exe"),
            "-pdf",
            input_path,
            fixed_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        print(f"🔧 Repaired corrupted file: {os.path.basename(fixed_path)}")
        return fixed_path
    except Exception as e:
        print(f"🔥 Repair failed for {os.path.basename(input_path)}: {e}")
        return None


def safe_convert(pdf_path, dpi=150):
    try:
        return convert_from_path(
            pdf_path,
            dpi=dpi,
            poppler_path=POPPLER_PATH
        )
    except Exception as e:
        print(f"⚠️ Initial extraction failed for {os.path.basename(pdf_path)}. Attempting Cairo rebuild...")

        fixed = repair_pdf(pdf_path)

        if fixed and os.path.exists(fixed):
            try:
                pages = convert_from_path(
                    fixed,
                    dpi=dpi,
                    poppler_path=POPPLER_PATH
                )
                print("🔁 Successfully parsed repaired PDF.")
                return pages
            except Exception as e2:
                print("🔥 Repaired file also failed:", e2)

        raise e


def process_folder(input_folder, output_folder, log=print):

    data = []

    files = [
        os.path.join(input_folder, f)
        for f in os.listdir(input_folder)
        if f.lower().endswith(".pdf")
    ]

    if not files:
        log("❌ No PDFs found in directory.")
        return

    for i, file in enumerate(files):
        filename = os.path.basename(file)
        log(f"📄 [{i+1}/{len(files)}] Processing: {filename}")

        try:
            pages = safe_convert(file, dpi=120)

            # Placeholder logic for extraction
            supplier = "Unknown"
            invoice = filename[:10]
            date = "NoDate"

            data.append({
                "Supplier": supplier,
                "Invoice": invoice,
                "Date": date,
                "File": filename
            })

        except Exception as e:
            log(f"🔥 FATAL ERROR reading {filename}: {e}")

    if not data:
        log("❌ No data extracted.")
        return

    df = pd.DataFrame(data)

    os.makedirs(output_folder, exist_ok=True)
    out_file = os.path.join(output_folder, "invoice_log.xlsx")

    df.to_excel(out_file, index=False)

    log(f"📊 Excel saved successfully at: {out_file}")
    log("🎉 Processing Complete!")