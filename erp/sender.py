"""Write the finished documents to Google Drive (or any folder) and tidy up the original."""
import os
import shutil

from . import pdf, naming


class SendError(Exception):
    pass


def send(src, parts, settings, names, store=None, to_inbox=False):
    """parts: [{"name": str, "pages": [(index, rotation), ...], "fields": {...}}].

    Returns a list of destination paths. The original is only moved away when
    every part was written successfully.
    """
    if to_inbox:
        root = os.path.dirname(src)
    else:
        root = settings.get("drive_folder") or ""
        if not root or not os.path.isdir(root):
            raise SendError("The Google Drive folder isn't set or isn't available.\n"
                            "Check Settings → Drive folder (is Google Drive for desktop running?).")
    written = []
    try:
        for n, part in enumerate(parts, 1):
            if not part["pages"]:
                continue
            folder = root
            if not to_inbox:
                sub = naming.subfolder(settings.get("subfolder_template", ""), part.get("fields", {}), names,
                                       os.path.basename(src), n, settings.get("date_format", "%Y-%m-%d"))
                folder = os.path.join(root, sub) if sub else root
            os.makedirs(folder, exist_ok=True)
            name = naming.safe_name(naming.strip_pdf(part["name"])) or f"document_{n}"
            dest = naming.unique_path(os.path.join(folder, name + ".pdf"))
            pdf.save_part(src, part["pages"], dest)
            written.append(dest)
    except Exception as e:
        raise SendError(f"Stopped after {len(written)} file(s): {e}") from None

    if store is not None:
        for dest, part in zip(written, [p for p in parts if p["pages"]]):
            store.add_history(os.path.basename(src), dest, len(part["pages"]))

    if settings.get("after_send", "done") == "done" or to_inbox:
        done = os.path.join(os.path.dirname(src), "_done")
        os.makedirs(done, exist_ok=True)
        shutil.move(src, naming.unique_path(os.path.join(done, os.path.basename(src))))
    return written
