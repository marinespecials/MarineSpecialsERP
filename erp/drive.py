"""Find the Google Drive for desktop folder (G:\\My Drive etc.)."""
import os
import string

DRIVE_NAMES = ("My Drive", "Το Drive μου", "Το δικό μου Drive", "Mon Drive", "Mi unidad", "Meine Ablage")


def candidates():
    found = []
    if os.name == "nt":
        for letter in string.ascii_uppercase[2:]:
            root = f"{letter}:\\"
            for name in DRIVE_NAMES:
                p = os.path.join(root, name)
                if os.path.isdir(p):
                    found.append(p)
    home = os.path.expanduser("~")
    for p in (os.path.join(home, "Google Drive"), os.path.join(home, "My Drive"),
              os.path.join(home, "Google Drive", "My Drive")):
        if os.path.isdir(p) and p not in found:
            found.append(p)
    return found


def looks_like_drive(path):
    p = os.path.normpath(path or "")
    return any(name in p for name in DRIVE_NAMES) or "Google Drive" in p
