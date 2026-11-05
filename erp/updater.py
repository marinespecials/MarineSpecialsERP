"""Self-update from GitHub Releases.

The release build (.github/workflows/release.yml) attaches:
    MarineSpecialsERP-Setup.exe           the installer
    MarineSpecialsERP-Setup.exe.sha256    its checksum
    MarineSpecialsERP-win64.zip (+ .sha256)  portable copy (kept for older app versions)

Updating = download the installer, check its SHA-256, run it silently and quit.
Inno Setup closes the app if needed, replaces the files and starts the new version.
(v2.0's own file-copy script didn't work on every PC; the installer always does.)
"""
import os
import re
import json
import hashlib
import tempfile
import subprocess

from . import VERSION, GITHUB_REPO, net, paths

SETUP_NAME = "MarineSpecialsERP-Setup.exe"
ASSET_NAME = "MarineSpecialsERP-win64.zip"
EXE_NAME = "MarineSpecialsERP.exe"


def parse_version(v):
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def check(repo=GITHUB_REPO, current=VERSION):
    """Return info about a newer release, or None if up to date."""
    _, body = net.request(f"https://api.github.com/repos/{repo}/releases/latest",
                          headers={"Accept": "application/vnd.github+json"}, timeout=15)
    rel = json.loads(body)
    latest = rel.get("tag_name", "")
    if parse_version(latest) <= parse_version(current):
        return None
    assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
    if SETUP_NAME not in assets:
        return None
    return {"version": latest.lstrip("v"), "notes": rel.get("body") or "", "page": rel.get("html_url", ""),
            "setup_url": assets[SETUP_NAME], "sha_url": assets.get(SETUP_NAME + ".sha256")}


def can_self_update():
    if not (paths.FROZEN and paths.IS_WINDOWS):
        return False, "Automatic install works only in the installed Windows app."
    return True, ""


def download_and_verify(info, progress=None):
    """Download the installer to a temp folder and check its checksum. Returns its path."""
    work = tempfile.mkdtemp(prefix="mserp_update_")
    setup = net.download(info["setup_url"], os.path.join(work, SETUP_NAME), progress)
    if info.get("sha_url"):
        _, sha_body = net.request(info["sha_url"], timeout=30)
        expected = sha_body.decode().split()[0].lower()
        h = hashlib.sha256()
        with open(setup, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest().lower() != expected:
            raise RuntimeError("The downloaded update is corrupted (checksum mismatch). Please try again later.")
    with open(setup, "rb") as f:
        if f.read(2) != b"MZ":
            raise RuntimeError("The downloaded file isn't a Windows installer.")
    return setup


def install_and_restart(setup):
    """Run the installer silently; the caller must quit the app right after.

    /CLOSEAPPLICATIONS lets the installer close this app if it is still running,
    and the installer's [Run] section starts the new version when it's done.
    """
    log = os.path.join(paths.data_dir(), "update.log")
    flags = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
                      "/FORCECLOSEAPPLICATIONS", f"/LOG={log}"],
                     creationflags=flags, close_fds=True, cwd=os.path.dirname(setup))
