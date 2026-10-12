"""Pull PDF attachments from an email inbox (IMAP) into the input folder.

Gmail: turn on 2-step verification and create an "App password".
Microsoft 365 / Outlook.com no longer allow password IMAP - use a
forwarding rule to a Gmail/other mailbox, or a shared folder instead.
"""
import os
import re
import email
import imaplib
from email import policy

from .filing import unique_path


def _safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name or "attachment.pdf").strip(" .")
    return name if name.lower().endswith(".pdf") else name + ".pdf"


def fetch_pdfs(host, port, user, password, folder, dest_dir, mark_read=True, limit=50):
    """Save PDFs from unread messages. Returns list of saved file paths."""
    saved = []
    box = imaplib.IMAP4_SSL(host, int(port or 993))
    try:
        box.login(user, password)
        typ, _ = box.select(f'"{folder or "INBOX"}"')
        if typ != "OK":
            raise RuntimeError(f"Mailbox folder '{folder}' not found")
        typ, data = box.search(None, "UNSEEN")
        ids = data[0].split()[:limit] if typ == "OK" else []
        for mid in ids:
            typ, msg_data = box.fetch(mid, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email.message_from_bytes(msg_data[0][1], policy=policy.default)
            found = False
            for part in msg.walk():
                fname = part.get_filename()
                is_pdf = part.get_content_type() == "application/pdf" or (fname or "").lower().endswith(".pdf")
                if not is_pdf:
                    continue
                payload = part.get_payload(decode=True)
                if not payload or not payload.startswith(b"%PDF"):
                    continue
                path = unique_path(os.path.join(dest_dir, _safe_name(fname)))
                with open(path, "wb") as f:
                    f.write(payload)
                saved.append(path)
                found = True
            if mark_read or found:
                box.store(mid, "+FLAGS", "\\Seen")
    finally:
        try:
            box.logout()
        except Exception:
            pass
    return saved


def test(host, port, user, password, folder):
    try:
        box = imaplib.IMAP4_SSL(host, int(port or 993))
        box.login(user, password)
        typ, _ = box.select(f'"{folder or "INBOX"}"', readonly=True)
        box.logout()
        return (typ == "OK"), ("Connected" if typ == "OK" else f"Folder '{folder}' not found")
    except Exception as e:
        return False, str(e)
