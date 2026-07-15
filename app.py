import customtkinter as ctk
from tkinter import filedialog, Listbox, messagebox
import os
import sys
import re
import threading
import subprocess
import json
import requests
import shutil
import datetime

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from PIL import Image, ImageTk
from pdf2image import convert_from_path
import pytesseract
import qrcode

# ================= DYNAMIC CONFIG =================
CURRENT_VERSION = "v1.4.0"
GITHUB_REPO = "marinespecials/MarineSpecialsERP"

if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

POPPLER_PATH = os.path.join(BASE_DIR, "poppler", "Library", "bin")
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("dark-blue")

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

class App(ctk.CTk):

    def __init__(self):
        super().__init__()

        self.title(f"Marine Specials ERP - PDF Automation {CURRENT_VERSION}")
        self.geometry("1800x950")
        
        self.input_folder = ""
        self.output_folder = ""
        self.files = []
        self.filtered_files = []
        self.current_file = None
        self.zoom = 0.55
        self.images = []
        self.preview_cache = {}
        self.analytics_df = pd.DataFrame()
        
        self.supplier_rules = {}
        self.load_supplier_rules()

        self.build_ui()
        self.setup_clipboard_bindings()
        
        threading.Thread(target=self.check_for_updates, daemon=True).start()

    def load_supplier_rules(self):
        self.rules_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'supplier_rules.json')
        if os.path.exists(self.rules_path):
            try:
                with open(self.rules_path, 'r', encoding='utf-8') as f:
                    self.supplier_rules = json.load(f)
            except Exception as e:
                print(f"Failed to load supplier rules: {e}")

    def save_supplier_rules(self):
        try:
            new_rules = json.loads(self.rules_textbox.get("1.0", "end"))
            with open(self.rules_path, 'w', encoding='utf-8') as f:
                json.dump(new_rules, f, indent=4, ensure_ascii=False)
            self.supplier_rules = new_rules
            messagebox.showinfo("Success", "Supplier rules updated successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Invalid JSON format.\n\n{e}")

    # ================= UI ARCHITECTURE =================

    def build_ui(self):
        main_container = ctk.CTkFrame(self, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Header Area
        header = ctk.CTkFrame(main_container, fg_color="transparent")
        header.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(header, text="🌊 Marine Specials ERP", font=ctk.CTkFont(size=28, weight="bold"), text_color="#1A5276").pack(side="left")
        ctk.CTkSwitch(header, text="Dark Mode", command=self.toggle_mode).pack(side="right")

        # Tabview
        self.tabs = ctk.CTkTabview(main_container, corner_radius=10)
        self.tabs.pack(fill="both", expand=True)
        
        self.tab_processing = self.tabs.add("📄 Processing")
        self.tab_analytics = self.tabs.add("📊 Analytics & Reports")
        self.tab_settings = self.tabs.add("⚙️ Settings & Rules")

        self.build_processing_tab()
        self.build_analytics_tab()
        self.build_settings_tab()

        # Bottom Status Bar
        status_bar = ctk.CTkFrame(self, height=30, corner_radius=0, fg_color="#D3D3D3")
        status_bar.pack(side="bottom", fill="x")

        self.status_label = ctk.CTkLabel(status_bar, text="Ready", text_color="black", font=("Segoe UI", 12))
        self.status_label.pack(side="left", padx=10)

        self.progress = ctk.CTkProgressBar(status_bar, width=200, mode="indeterminate", progress_color="#1A5276")
        self.progress.pack(side="right", padx=10, pady=5)
        self.progress.set(0)

    def build_processing_tab(self):
        left = ctk.CTkFrame(self.tab_processing, width=320, corner_radius=10, fg_color="#F2F3F4")
        left.pack(side="left", fill="y", padx=(0, 10))

        btn_frame = ctk.CTkFrame(left, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=15)

        ctk.CTkButton(btn_frame, text="📁 Select Input Folder", command=self.select_input, fg_color="#2980B9", hover_color="#1A5276").pack(fill="x", pady=5)
        ctk.CTkButton(btn_frame, text="📂 Select Output Folder", command=self.select_output, fg_color="#2980B9", hover_color="#1A5276").pack(fill="x", pady=5)
        
        self.btn_bulk = ctk.CTkButton(btn_frame, text="🚀 Run Bulk Auto-Sort", fg_color="#8E44AD", hover_color="#6C3483", font=("Segoe UI", 14, "bold"), command=self.run_bulk_sort)
        self.btn_bulk.pack(fill="x", pady=(15, 5))
        
        ctk.CTkButton(btn_frame, text="✂ Split PDFs", fg_color="#D35400", hover_color="#A04000", command=self.split_pdfs).pack(fill="x", pady=5)

        self.search = ctk.CTkEntry(left, placeholder_text="🔍 Search PDFs...")
        self.search.pack(fill="x", padx=15, pady=10)
        self.search.bind("<KeyRelease>", self.filter_files)

        self.listbox = Listbox(left, font=("Segoe UI", 11), activestyle="none", bg="#FFFFFF", selectbackground="#1A5276", selectforeground="white", relief="flat", borderwidth=0, highlightthickness=1)
        self.listbox.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        right = ctk.CTkFrame(self.tab_processing, fg_color="transparent")
        right.pack(side="right", fill="both", expand=True)

        form = ctk.CTkFrame(right, corner_radius=10, fg_color="#F8F9F9", border_width=1, border_color="#D5D8DC")
        form.pack(fill="x", pady=(0, 10))

        inputs_frame = ctk.CTkFrame(form, fg_color="transparent")
        inputs_frame.pack(fill="x", padx=10, pady=15)

        self.company_entry = ctk.CTkEntry(inputs_frame, placeholder_text="Company Name", height=45, font=("Segoe UI", 14))
        self.company_entry.pack(side="left", expand=True, fill="x", padx=5)

        self.invoice_entry = ctk.CTkEntry(inputs_frame, placeholder_text="Invoice #", height=45, font=("Segoe UI", 14))
        self.invoice_entry.pack(side="left", expand=True, fill="x", padx=5)

        self.date_entry = ctk.CTkEntry(inputs_frame, placeholder_text="Date", height=45, font=("Segoe UI", 14))
        self.date_entry.pack(side="left", expand=True, fill="x", padx=5)

        self.btn_rename = ctk.CTkButton(inputs_frame, text="✔ Approve & Move", height=45, font=("Segoe UI", 14, "bold"), fg_color="#27AE60", hover_color="#1E8449", command=self.rename_move)
        self.btn_rename.pack(side="left", padx=5)

        ctk.CTkLabel(form, text="Extracted Line Items (Auto-Detected):", font=("Segoe UI", 12, "bold"), text_color="#5D6D7E").pack(anchor="w", padx=15)
        self.items_textbox = ctk.CTkTextbox(form, height=60, font=("Consolas", 12), fg_color="#EAEDED")
        self.items_textbox.pack(fill="x", padx=15, pady=(0, 15))

        viewer_layout = ctk.CTkFrame(right, fg_color="transparent")
        viewer_layout.pack(fill="both", expand=True)

        thumb_frame = ctk.CTkFrame(viewer_layout, width=180, corner_radius=10, fg_color="#F2F3F4")
        thumb_frame.pack(side="left", fill="y", padx=(0, 10))

        ctk.CTkLabel(thumb_frame, text="📑 Pages", font=ctk.CTkFont(size=16, weight="bold"), text_color="#34495E").pack(pady=10)

        self.thumb_canvas = ctk.CTkCanvas(thumb_frame, width=160, bg="#F2F3F4", highlightthickness=0)
        self.thumb_canvas.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=(0, 5))
        
        thumb_scroll = ctk.CTkScrollbar(thumb_frame, orientation="vertical", command=self.thumb_canvas.yview)
        thumb_scroll.pack(side="right", fill="y", pady=(0, 5))
        self.thumb_canvas.configure(yscrollcommand=thumb_scroll.set)

        preview_container = ctk.CTkFrame(viewer_layout, corner_radius=10, fg_color="#EBEDEF")
        preview_container.pack(side="right", fill="both", expand=True)

        self.canvas = ctk.CTkCanvas(preview_container, bg="#EBEDEF", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True, padx=2, pady=2)

        scrollbar = ctk.CTkScrollbar(preview_container, orientation="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.bind_all("<MouseWheel>", self.scroll_canvas)
        self.canvas.bind_all("<Control-MouseWheel>", self.zoom_mouse)

    def build_analytics_tab(self):
        container = ctk.CTkFrame(self.tab_analytics, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=20, pady=20)

        kpi_frame = ctk.CTkFrame(container, fg_color="transparent")
        kpi_frame.pack(fill="x", pady=(0, 20))

        self.kpi_total = ctk.CTkLabel(kpi_frame, text="Total Invoices: 0", font=ctk.CTkFont(size=24, weight="bold"))
        self.kpi_total.pack(side="left", padx=(0, 40))

        self.kpi_top_supplier = ctk.CTkLabel(kpi_frame, text="Top Supplier: N/A", font=ctk.CTkFont(size=24, weight="bold"), text_color="#1A5276")
        self.kpi_top_supplier.pack(side="left")

        self.chart_frame = ctk.CTkFrame(container, corner_radius=10)
        self.chart_frame.pack(fill="both", expand=True, pady=(0, 20))
        
        self.fig, self.ax = plt.subplots(figsize=(6, 4))
        self.fig.patch.set_facecolor('#EBEBEB')
        self.ax.set_facecolor('#EBEBEB')
        self.chart_canvas = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
        self.chart_canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

        export_btn = ctk.CTkButton(container, text="📥 Export Full Ledger to Excel", height=50, font=("Segoe UI", 16, "bold"), fg_color="#27AE60", hover_color="#1E8449", command=self.export_excel)
        export_btn.pack(fill="x")

    def build_settings_tab(self):
        container = ctk.CTkFrame(self.tab_settings, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=20, pady=20)
        
        ctk.CTkLabel(container, text="Supplier OCR Mapping Rules", font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", pady=(0, 5))
        ctk.CTkLabel(container, text="Format: \"OCR Text\": \"Official Database Name\"", text_color="gray").pack(anchor="w", pady=(0, 10))
        
        self.rules_textbox = ctk.CTkTextbox(container, font=("Consolas", 14))
        self.rules_textbox.pack(fill="both", expand=True, pady=(0, 15))
        
        formatted_json = json.dumps(self.supplier_rules, indent=4, ensure_ascii=False)
        self.rules_textbox.insert("1.0", formatted_json)
        
        ctk.CTkButton(container, text="💾 Save Rules", font=("Segoe UI", 14, "bold"), fg_color="#2980B9", hover_color="#1A5276", command=self.save_supplier_rules).pack(anchor="e")

    # ================= CLIPBOARD FIX =================
    def setup_clipboard_bindings(self):
        self.bind_all("<<Copy>>", self.copy_text)
        self.bind_all("<<Paste>>", self.paste_text)
        self.bind_all("<<Cut>>", self.cut_text)
        self.bind_all("<Control-c>", self.copy_text)
        self.bind_all("<Control-v>", self.paste_text)
        self.bind_all("<Control-x>", self.cut_text)
        self.bind_all("<Control-C>", self.copy_text)
        self.bind_all("<Control-V>", self.paste_text)
        self.bind_all("<Control-X>", self.cut_text)

    def copy_text(self, event=None):
        widget = self.focus_get()
        if hasattr(widget, 'selection_get'):
            try: self.clipboard_clear(); self.clipboard_append(widget.selection_get())
            except: pass

    def paste_text(self, event=None):
        widget = self.focus_get()
        if hasattr(widget, 'insert'):
            try: widget.insert("insert", self.clipboard_get())
            except: pass

    def cut_text(self, event=None):
        widget = self.focus_get()
        if hasattr(widget, 'selection_get') and hasattr(widget, 'delete'):
            try: self.clipboard_clear(); self.clipboard_append(widget.selection_get()); widget.delete("sel.first", "sel.last")
            except: pass

    # ================= CORE LOGIC & ANALYTICS =================
    def update_status(self, text):
        self.after(0, lambda: self.status_label.configure(text=text))

    def select_input(self):
        folder = filedialog.askdirectory()
        if folder:
            self.input_folder = folder
            self.load_files()

    def select_output(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_folder = folder
            self.update_status(f"Output set to: {os.path.basename(folder)}")
            self.refresh_analytics()

    def load_files(self):
        self.listbox.delete(0, "end")
        if not self.input_folder: return
        pdfs = [f for f in os.listdir(self.input_folder) if f.lower().endswith(".pdf")]
        pdfs.sort(key=natural_sort_key)
        self.files = pdfs
        self.filtered_files = pdfs.copy()
        for file in self.filtered_files:
            self.listbox.insert("end", file)
        self.update_status(f"Loaded {len(pdfs)} PDFs.")

    def filter_files(self, event=None):
        term = self.search.get().lower()
        self.listbox.delete(0, "end")
        self.filtered_files = []
        for file in self.files:
            if term in file.lower():
                self.filtered_files.append(file)
                self.listbox.insert("end", file)

    def on_select(self, event):
        try:
            selection = self.listbox.curselection()
            if not selection: return
            selected = self.filtered_files[selection[0]]
            if selected == self.current_file: return
            self.current_file = selected
            
            self.company_entry.delete(0, "end")
            self.invoice_entry.delete(0, "end")
            self.date_entry.delete(0, "end")
            self.items_textbox.delete("1.0", "end")
            self.canvas.delete("all")
            self.thumb_canvas.delete("all")

            threading.Thread(target=self.process_pdf_thread, args=(selected,), daemon=True).start()
        except: pass

    def refresh_analytics(self):
        if not self.output_folder or not os.path.exists(self.output_folder): return
        processed = [f for f in os.listdir(self.output_folder) if f.lower().endswith(".pdf")]
        data = []
        for f in processed:
            name_no_ext = os.path.splitext(f)[0]
            parts = name_no_ext.split("_")
            if len(parts) >= 3:
                data.append({"Supplier": parts[0].replace("-", " "), "Invoice Number": parts[1], "Date Processed": parts[2], "Original File": f})
        self.analytics_df = pd.DataFrame(data)
        
        if self.analytics_df.empty:
            self.kpi_total.configure(text="Total Invoices: 0")
            self.kpi_top_supplier.configure(text="Top Supplier: N/A")
            self.ax.clear()
            self.ax.text(0.5, 0.5, "No data available.", ha='center', va='center', fontsize=12)
            self.chart_canvas.draw()
            return
            
        total_inv = len(self.analytics_df)
        top_sup = self.analytics_df["Supplier"].value_counts().idxmax()
        self.kpi_total.configure(text=f"Total Invoices: {total_inv}")
        self.kpi_top_supplier.configure(text=f"Top Supplier: {top_sup}")
        
        self.ax.clear()
        supplier_counts = self.analytics_df["Supplier"].value_counts().head(5)
        text_color = 'white' if ctk.get_appearance_mode() == "dark" else 'black'
        bg_color = '#2C3E50' if ctk.get_appearance_mode() == "dark" else '#EBEBEB'
        self.fig.patch.set_facecolor(bg_color)
        self.ax.pie(supplier_counts, labels=supplier_counts.index, autopct='%1.1f%%', startangle=90, textprops={'color': text_color})
        self.ax.axis('equal')
        self.ax.set_title("Top 5 Suppliers by Volume", color=text_color, fontweight='bold')
        self.chart_canvas.draw()

    def export_excel(self):
        if self.analytics_df.empty:
            messagebox.showwarning("Warning", "No data to export.")
            return
        try:
            desktop = os.path.join(os.path.join(os.environ['USERPROFILE']), 'Desktop')
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
            filepath = os.path.join(desktop, f"Marine_Specials_Ledger_{timestamp}.xlsx")
            self.analytics_df.to_excel(filepath, index=False)
            messagebox.showinfo("Export Successful", f"Saved to Desktop:\n\n{os.path.basename(filepath)}")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    # ================= PDF & OCR PROCESSING =================
    def safe_convert(self, path, dpi):
        try:
            return convert_from_path(path, dpi=dpi, first_page=1, last_page=10, poppler_path=POPPLER_PATH)
        except:
            fixed_path = path.replace(".pdf", "_fixed.pdf")
            try:
                subprocess.run([os.path.join(POPPLER_PATH, "pdftocairo.exe"), "-pdf", path, fixed_path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return convert_from_path(fixed_path, dpi=dpi, first_page=1, last_page=10, poppler_path=POPPLER_PATH)
            except Exception as e2:
                raise Exception(f"Repair failed: {e2}")

    def process_pdf_thread(self, filename):
        self.after(0, self.progress.start)
        self.update_status(f"Loading {filename}...")
        path = os.path.join(self.input_folder, filename)
        cache_key = f"{path}_{self.zoom}"

        try:
            if cache_key in self.preview_cache:
                pages = self.preview_cache[cache_key]
            else:
                pages = self.safe_convert(path, int(60 * self.zoom))
                self.preview_cache[cache_key] = pages

            if pages:
                self.update_status("Running OCR...")
                company, invoice, date, line_items = self.extract_invoice_data(pages[0])
                self.after(0, lambda: self.populate_form(company, invoice, date, line_items))

            self.after(0, lambda: self.render_images(pages))
            self.update_status("Ready")
        except Exception as e:
            self.update_status(f"Error: {e}")
        finally:
            self.after(0, self.progress.stop)

    def extract_invoice_data(self, image):
        try:
            text = pytesseract.image_to_string(image, lang='ell+eng')
            company, invoice, date, extracted_items = "", "", "", []
            lines = text.split("\n")
            
            for line in lines[:15]:
                line = line.strip()
                if len(line) > 5 and "invoice" not in line.lower():
                    company = line
                    break
                    
            for key, official_name in self.supplier_rules.items():
                if key.upper() in company.upper() or key.upper() in text.upper():
                    company = official_name
                    break

            invoice_match = re.search(r"(?:invoice|τιμολογιο|αρ\.)[\s#:]*([A-Z0-9\-]+)", text, re.IGNORECASE)
            if invoice_match: invoice = invoice_match.group(1)

            date_match = re.search(r"\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4}", text)
            if date_match: date = date_match.group(0)

            for line in lines:
                if re.search(r'\d', line) and re.search(r'(€|eur|qty|pcs|tem|τεμ|ποσοτ)', line.lower()):
                    clean_line = re.sub(r'[^\w\s\.,€\-]', '', line).strip()
                    if len(clean_line) > 5:
                        extracted_items.append(clean_line)

            items_text = "\n".join(extracted_items) if extracted_items else "No clear items detected."
            return company, invoice, date, items_text
        except:
            return "", "", "", "OCR Error"

    def populate_form(self, company, invoice, date, line_items):
        self.company_entry.insert(0, company)
        self.invoice_entry.insert(0, invoice)
        self.date_entry.insert(0, date)
        self.items_textbox.insert("1.0", line_items)

    def render_images(self, pages):
        self.images.clear()
        y, thumb_y = 10, 10
        for i, img in enumerate(pages):
            display_img = img.resize((int(img.width * self.zoom), int(img.height * self.zoom)))
            tk_img = ImageTk.PhotoImage(display_img)
            self.images.append(tk_img)
            self.canvas.create_image(20, y, anchor="nw", image=tk_img)

            thumb = img.resize((120, 160))
            tk_thumb = ImageTk.PhotoImage(thumb)
            self.images.append(tk_thumb)
            self.thumb_canvas.create_image(20, thumb_y, anchor="nw", image=tk_thumb)
            self.thumb_canvas.create_text(80, thumb_y + 170, text=f"Page {i+1}", font=("Segoe UI", 10))

            thumb_y += 210
            y += display_img.height + 20

        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.thumb_canvas.configure(scrollregion=self.thumb_canvas.bbox("all"))

    # ================= LABEL GENERATOR =================
    def generate_qr_label(self, company, invoice, output_dir):
        """Generates a scannable warehouse QR code pointing to the web tracker"""
        labels_folder = os.path.join(output_dir, "Warehouse_Labels")
        os.makedirs(labels_folder, exist_ok=True)

        # Dynamic routing to your Render stock tracking application
        tracking_url = f"https://marine-specials-tracker.onrender.com/invoice/{invoice}"

        qr = qrcode.QRCode(box_size=10, border=4)
        qr.add_data(tracking_url)
        qr.make(fit=True)
        
        # Color matching the marine theme
        qr_img = qr.make_image(fill_color="#1A5276", back_color="white")

        filename = f"LABEL_{company}_{invoice}.png"
        for c in '<>:"/\\|?* ': filename = filename.replace(c, "_")
        
        filepath = os.path.join(labels_folder, filename)
        qr_img.save(filepath)

    # ================= OPERATIONS =================
    def run_bulk_sort(self):
        if not self.input_folder or not self.output_folder:
            messagebox.showwarning("Warning", "Select Input and Output folders.")
            return

        self.update_status("Running Bulk Auto-Sort & Generating Labels...")
        self.progress.start()
        self.btn_bulk.configure(state="disabled")

        def process_bulk():
            success_count = 0
            for i, filename in enumerate(self.files):
                path = os.path.join(self.input_folder, filename)
                self.update_status(f"Bulk Processing [{i+1}/{len(self.files)}]: {filename}")
                
                try:
                    pages = self.safe_convert(path, dpi=70) 
                    if not pages: continue
                    company, invoice, date, _ = self.extract_invoice_data(pages[0])
                    
                    if company in self.supplier_rules.values() and invoice:
                        new_name = f"{company}_{invoice}_{date}.pdf"
                        for c in '<>:"/\\|?* ': new_name = new_name.replace(c, "_")
                        
                        new_path = os.path.join(self.output_folder, new_name)
                        shutil.move(path, new_path)
                        
                        # Generate the physical label
                        self.generate_qr_label(company, invoice, self.output_folder)
                        
                        success_count += 1
                except Exception as e:
                    print(f"Failed to bulk process {filename}: {e}")

            self.after(0, self.load_files)
            self.after(0, self.refresh_analytics) 
            self.after(0, self.progress.stop)
            self.after(0, lambda: self.btn_bulk.configure(state="normal"))
            self.update_status(f"Bulk Complete. Auto-filed & Generated Labels for {success_count} invoices.")

        threading.Thread(target=process_bulk, daemon=True).start()

    def split_pdfs(self):
        if not self.input_folder: return
        self.update_status("✂ Splitting PDFs...")
        self.progress.start()
        def run_split():
            for file in os.listdir(self.input_folder):
                if not file.lower().endswith(".pdf"): continue
                path = os.path.join(self.input_folder, file)
                try:
                    pages = convert_from_path(path, poppler_path=POPPLER_PATH)
                    for i, img in enumerate(pages):
                        new_name = f"{os.path.splitext(file)[0]}_page_{i+1}.pdf"
                        new_path = os.path.join(self.input_folder, new_name)
                        if not os.path.exists(new_path): img.save(new_path, "PDF")
                except: pass
            self.after(0, self.load_files)
            self.after(0, self.progress.stop)
            self.update_status("Ready")
        threading.Thread(target=run_split, daemon=True).start()

    def rename_move(self):
        if not self.current_file or not self.output_folder:
            messagebox.showwarning("Warning", "Select a file and output folder.")
            return

        company = self.company_entry.get().strip()
        invoice = self.invoice_entry.get().strip()
        date = self.date_entry.get().strip()

        new_name = f"{company}_{invoice}_{date}.pdf"
        for c in '<>:"/\\|?* ': new_name = new_name.replace(c, "_")

        old_path = os.path.join(self.input_folder, self.current_file)
        new_path = os.path.join(self.output_folder, new_name)

        try:
            shutil.move(old_path, new_path)
            
            # Generate the physical label
            self.generate_qr_label(company, invoice, self.output_folder)
            
            self.update_status(f"✔ Moved & Label Generated: {new_name}")
            self.canvas.delete("all")
            self.thumb_canvas.delete("all")
            self.current_file = None
            self.load_files()
            self.refresh_analytics() 
        except Exception as e:
            messagebox.showerror("Rename Error", str(e))

    # ================= SCROLL & ZOOM =================
    def scroll_canvas(self, event):
        scroll_speed = int(-1 * (event.delta / 90))
        self.canvas.yview_scroll(scroll_speed, "units")
        self.thumb_canvas.yview_scroll(scroll_speed, "units")

    def zoom_mouse(self, event):
        self.zoom += 0.1 if event.delta > 0 else -0.1
        self.zoom = max(0.2, self.zoom)
        if self.current_file:
            self.canvas.delete("all")
            self.thumb_canvas.delete("all")
            threading.Thread(target=self.process_pdf_thread, args=(self.current_file,), daemon=True).start()

    def toggle_mode(self):
        mode = "dark" if ctk.get_appearance_mode() == "Light" else "light"
        ctk.set_appearance_mode(mode)
        bg_color = "#2C3E50" if mode == "dark" else "#EBEDEF"
        listbox_bg = "#34495E" if mode == "dark" else "#FFFFFF"
        
        self.canvas.configure(bg=bg_color)
        self.thumb_canvas.configure(bg=bg_color)
        self.listbox.configure(bg=listbox_bg)
        self.refresh_analytics()
        
    def check_for_updates(self):
        # Disabled for deployment simulation
        pass


if __name__ == "__main__":
    app = App()
    app.mainloop()