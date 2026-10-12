"""Marine Specials ERP - desktop app entry point.

    MarineSpecialsERP.exe                    start the app
    MarineSpecialsERP.exe --check a.pdf      read one invoice, write the result to check_result.json
                                             in the data folder (support / diagnostics)
"""
import sys


def check(path):
    import os
    import json
    from erp import paths, ocr
    from erp.db import Database
    from erp.extract import analyze
    db = Database(os.path.join(paths.data_dir(), "erp.db"))
    d = analyze(path, db)
    d.pop("text", None)
    d["ocr_problems"] = ocr.problems()
    d["tesseract"] = ocr.TESSERACT_CMD
    out = os.path.join(paths.data_dir(), "check_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps(d, ensure_ascii=False, default=str))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--check":
        check(sys.argv[2])
    else:
        from erp.ui.app import run
        run()
