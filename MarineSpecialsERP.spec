# PyInstaller build:  pyinstaller MarineSpecialsERP.spec --noconfirm
# Produces dist/MarineSpecialsERP/ (one folder = fast start, and easy to update in place).
import os
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

datas = [("assets", "assets")]
if os.path.isdir(os.path.join("build", "tesseract")):      # filled by the GitHub workflow
    datas.append((os.path.join("build", "tesseract"), "tesseract"))
datas += collect_data_files("pypdfium2_raw") + collect_data_files("pypdfium2")
binaries = collect_dynamic_libs("pypdfium2_raw")

a = Analysis(
    ["main.py"],
    binaries=binaries,
    datas=datas,
    hiddenimports=["keyring.backends.Windows", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtCharts"],
    excludes=["tkinter", "matplotlib", "pandas", "customtkinter",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
              "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtQuick3D", "PySide6.QtMultimedia",
              "PySide6.QtDesigner", "PySide6.QtBluetooth", "PySide6.QtLocation", "PySide6.QtSensors"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="MarineSpecialsERP",
    console=False,
    icon=os.path.join("assets", "app.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="MarineSpecialsERP")
