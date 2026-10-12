"""Tiny HTTP helper on the standard library (no extra dependency)."""
import json
import ssl
import urllib.request
import urllib.error

from . import VERSION

USER_AGENT = f"MarineSpecialsERP/{VERSION}"


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(f"HTTP {status}: {message}" if status else message)
        self.status = status


def request(url, method="GET", headers=None, data=None, timeout=30):
    h = {"User-Agent": USER_AGENT}
    h.update(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        h.setdefault("Content-Type", "application/json; charset=utf-8")
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise HttpError(e.code, detail or e.reason) from None
    except urllib.error.URLError as e:
        raise HttpError(0, f"Can't connect: {e.reason}") from None
    except TimeoutError:
        raise HttpError(0, "Timed out") from None


def download(url, dest, progress=None, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r, \
            open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return dest
