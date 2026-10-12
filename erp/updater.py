"""Self-update from GitHub Releases.

Release build (see .github/workflows/release.yml) attaches:
    MarineSpecialsERP-win64.zip          the app folder
    MarineSpecialsERP-win64.zip.sha256   its checksum

Flow: check latest release -> download zip -> verify SHA-256 -> unzip to temp
-> a small PowerShell script waits for the app to close, replaces the
program files (your data in %APPDATA% is never touched), and restarts it.
"""
import os
import re
import sys
import json
import hashlib
import zipfile
import tempfile
import subprocess

from . import VERSION, GITHUB_REPO, net, paths

ASSET_NAME = "MarineSpecialsERP-win64.zip"
EXE_NAME = "MarineSpecialsERP.exe"
INSTALL_MARKER = ".mserp-install"   # shipped in the zip; we only overwrite folders that have it


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
    if ASSET_NAME not in assets:
        return None
    return {"version": latest.lstrip("v"), "notes": rel.get("body") or "", "page": rel.get("html_url", ""),
            "zip_url": assets[ASSET_NAME], "sha_url": assets.get(ASSET_NAME + ".sha256")}


def can_self_update():
    """Only a packaged build in a folder we installed can replace itself."""
    if not (paths.FROZEN and paths.IS_WINDOWS):
        return False, "Auto-install works only in the installed Windows app."
    folder = paths.install_dir()
    if not os.path.exists(os.path.join(folder, INSTALL_MARKER)):
        return False, "App folder isn't a Marine Specials ERP install folder."
    test = os.path.join(folder, ".write_test")
    try:
        open(test, "w").close()
        os.remove(test)
    except OSError:
        return False, f"No write permission to {folder}. Install it in your user folder (the Setup does this)."
    return True, ""


def download_and_verify(info, progress=None):
    work = tempfile.mkdtemp(prefix="mserp_update_")
    zip_path = net.download(info["zip_url"], os.path.join(work, ASSET_NAME), progress)
    if info.get("sha_url"):
        _, sha_body = net.request(info["sha_url"], timeout=30)
        expected = sha_body.decode().split()[0].lower()
        h = hashlib.sha256()
        with open(zip_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest().lower() != expected:
            raise RuntimeError("Downloaded update is corrupted (checksum mismatch). Try again later.")
    extract = os.path.join(work, "new")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(extract)
    # zip contains a single top folder "MarineSpecialsERP"
    entries = os.listdir(extract)
    src = os.path.join(extract, entries[0]) if len(entries) == 1 else extract
    if not os.path.exists(os.path.join(src, EXE_NAME)):
        raise RuntimeError("Update package doesn't contain the program.")
    return work, src


PS_SCRIPT = r"""
param([int]$AppPid, [string]$Src, [string]$Dst, [string]$Work, [string]$Exe)
try { Wait-Process -Id $AppPid -Timeout 60 -ErrorAction SilentlyContinue } catch {}
Start-Sleep -Milliseconds 800
if (Test-Path (Join-Path $Dst '.mserp-install')) {
    $internal = Join-Path $Dst '_internal'
    for ($i = 0; $i -lt 10 -and (Test-Path $internal); $i++) {
        Remove-Item $internal -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path $internal) { Start-Sleep -Seconds 1 }
    }
    robocopy $Src $Dst /E /R:5 /W:1 /NFL /NDL /NJH /NJS | Out-Null
}
Start-Process (Join-Path $Dst $Exe)
Start-Sleep -Seconds 3
Remove-Item $Work -Recurse -Force -ErrorAction SilentlyContinue
"""


def install_and_restart(work, src):
    """Start the swap script; the caller must quit the app right after."""
    script = os.path.join(work, "apply_update.ps1")
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write(PS_SCRIPT)
    flags = 0x08000000 | 0x00000008  # CREATE_NO_WINDOW | DETACHED_PROCESS
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", script,
         "-AppPid", str(os.getpid()), "-Src", src, "-Dst", paths.install_dir(), "-Work", work, "-Exe", EXE_NAME],
        creationflags=flags, close_fds=True)


def running_exe():
    return sys.executable
