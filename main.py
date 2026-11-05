"""Marine Specials PDF - desktop app entry point.

    MarineSpecialsERP.exe                    start the app
    MarineSpecialsERP.exe --check a.pdf      read a PDF and write what was found to check_result.json
                                             in the data folder (support / diagnostics)
"""
import sys


def check(path):
    import os
    import json
    from erp import paths, ocr, pdf, analyze
    pages = [analyze.analyze_page(path, i) for i in range(pdf.page_count(path))]
    for p in pages:
        p.pop("text", None)
    starts, blanks = analyze.smart_split(pages)
    result = {"pages": pages, "documents_start_at": starts, "blank_pages": blanks,
              "ocr_problems": ocr.problems(), "tesseract": ocr.TESSERACT_CMD, "tessdata": ocr.TESSDATA}
    out = os.path.join(paths.data_dir(), "check_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--check":
        check(sys.argv[2])
    else:
        from erp.ui.app import run
        run()
